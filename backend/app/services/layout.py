"""Page layout from the PDF's vector drawings: shaded heading bands, boxed notes and ruled tables.

Books like YCT exam guides mark structure with drawings rather than with tagged PDF:
  * a light-grey filled bar behind a section heading ("सामान्य तथ्यात्मक विवरण")
  * a rectangle (one stroked rect, or four thin edges) around a note ("विशेष तथ्य") or a diagram
  * thin horizontal rules split at the same x positions = a table with columns
Reading drawings is fast (about 2 s for a 385-page book), unlike generic table finders.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import pymupdf as fitz

Rect = tuple[float, float, float, float]

RULE_MAX = 2.6  # thickness of a "line" drawn as a thin filled rectangle
POS_TOL = 3.0


@dataclass
class TableGrid:
    bbox: Rect
    col_x: list[float]  # column boundaries, including left and right edges
    row_y: list[float]  # y positions of the horizontal rules


@dataclass
class PageLayout:
    bands: list[Rect] = field(default_factory=list)  # shaded heading bars
    boxes: list[Rect] = field(default_factory=list)  # framed notes / diagrams
    tables: list[TableGrid] = field(default_factory=list)


def _is_grey(fill: tuple[float, ...] | None) -> bool:
    if not fill or len(fill) < 3:
        return False
    r, g, b = fill[:3]
    return 0.55 <= r <= 0.97 and abs(r - g) < 0.06 and abs(g - b) < 0.06


def _segments(drawings: list[dict]) -> tuple[list[Rect], list[Rect]]:
    """Horizontal and vertical rule segments, from thin filled rects and from stroked lines."""
    hs: list[Rect] = []
    vs: list[Rect] = []
    for d in drawings:
        r = d["rect"]
        dark = (d.get("fill") and max(d["fill"][:3]) < 0.4) or (d.get("color") and max(d["color"][:3]) < 0.4)
        if not dark:
            continue
        if r.height <= RULE_MAX and r.width >= 15:
            hs.append((r.x0, r.y0, r.x1, r.y1))
        elif r.width <= RULE_MAX and r.height >= 8:
            vs.append((r.x0, r.y0, r.x1, r.y1))
        elif d.get("fill") is None and d.get("color") is not None:
            for it in d["items"]:
                if it[0] == "l":
                    p1, p2 = it[1], it[2]
                    if abs(p1.y - p2.y) <= 0.5 and abs(p1.x - p2.x) >= 15:
                        hs.append((min(p1.x, p2.x), p1.y, max(p1.x, p2.x), p1.y))
                    elif abs(p1.x - p2.x) <= 0.5 and abs(p1.y - p2.y) >= 8:
                        vs.append((p1.x, min(p1.y, p2.y), p1.x, max(p1.y, p2.y)))
    return hs, vs


GAP = 1.5  # rule pieces further apart than this belong to different tables (e.g. side by side)


def _rows_of_rules(hs: list[Rect]) -> list[tuple[float, float, float, list[float]]]:
    """Group horizontal segments by y into runs of touching pieces:
    (y, x0, x1, internal break x positions). Two tables side by side give two runs."""
    by_y: dict[int, list[Rect]] = defaultdict(list)
    for s in hs:
        by_y[round((s[1] + s[3]) / 2 / POS_TOL)].append(s)
    rows = []
    for segs in by_y.values():
        segs.sort()
        y = sum((s[1] + s[3]) / 2 for s in segs) / len(segs)
        run = [segs[0]]
        runs = [run]
        for sg in segs[1:]:
            if sg[0] - max(r[2] for r in run) >= GAP:
                run = [sg]
                runs.append(run)
            else:
                run.append(sg)
        for run in runs:
            x0, x1 = run[0][0], max(r[2] for r in run)
            breaks = [r[2] for r in run[:-1] if r[2] < x1 - POS_TOL]
            rows.append((y, x0, x1, breaks))
    rows.sort()
    return rows


def _compatible(a: list[float], b: list[float]) -> bool:
    """Rules without column breaks fit any table; otherwise they must share a break position."""
    return not a or not b or any(_same(x, y) for x in a for y in b)


def _same(a: float, b: float, tol: float = 4.0) -> bool:
    return abs(a - b) <= tol


def analyze_page(page: fitz.Page) -> PageLayout:
    layout = PageLayout()
    try:
        drawings = page.get_drawings()
    except Exception:  # noqa: BLE001 - broken drawing streams must not break extraction
        return layout

    for d in drawings:
        r = d["rect"]
        if _is_grey(d.get("fill")) and r.width >= 60 and 8 <= r.height <= 40:
            layout.bands.append((r.x0, r.y0, r.x1, r.y1))
        elif d.get("fill") is None and d.get("color") is not None and r.width >= 60 and r.height >= 25:
            if any(it[0] == "re" for it in d["items"]):
                layout.boxes.append((r.x0, r.y0, r.x1, r.y1))

    hs, vs = _segments(drawings)
    rows = _rows_of_rules(hs)

    # Tables: >= 3 horizontal rules with the same left/right edges, split at shared column breaks.
    used: set[int] = set()
    for i in range(len(rows)):
        if i in used:
            continue
        group = [i]
        group_breaks: list[float] = list(rows[i][3])
        for j in range(i + 1, len(rows)):
            if j in used:
                continue
            y, x0, x1, brk = rows[j]
            if not (_same(x0, rows[i][1]) and _same(x1, rows[i][2])):
                continue  # a rule from another column / table
            if y - rows[group[-1]][0] < 8:
                continue
            if not _compatible(group_breaks, brk):
                break  # column positions change: a different table starts here
            group.append(j)
            group_breaks.extend(brk)
        if len(group) >= 3:
            x0, x1 = rows[i][1], rows[i][2]
            breaks: dict[int, list[float]] = defaultdict(list)
            for g in group:
                for b in rows[g][3]:
                    breaks[round(b / POS_TOL)].append(b)
            cols = sorted(sum(v) / len(v) for v in breaks.values() if len(v) >= 2)
            y0, y1 = rows[group[0]][0], rows[group[-1]][0]
            # vertical rules inside the table also mark columns
            for v in vs:
                vx = (v[0] + v[2]) / 2
                if x0 + POS_TOL < vx < x1 - POS_TOL and v[1] <= y0 + 4 and v[3] >= y1 - 4:
                    if not any(_same(vx, c) for c in cols):
                        cols.append(vx)
            cols.sort()
            if cols:  # at least two columns: a real table
                layout.tables.append(TableGrid((x0, y0, x1, y1), [x0, *cols, x1], [rows[g][0] for g in group]))
                used.update(group)

    # Boxes drawn as four separate edges: two unused horizontal rules joined by verticals at both ends.
    free = [r for k, r in enumerate(rows) if k not in used]
    for a in range(len(free)):
        for b in range(a + 1, len(free)):
            ya, xa0, xa1, _ = free[a]
            yb, xb0, xb1, _ = free[b]
            if yb - ya < 20 or not (_same(xa0, xb0) and _same(xa1, xb1)):
                continue
            left = any(_same((v[0] + v[2]) / 2, xa0) and v[1] <= ya + 3 and v[3] >= yb - 3 for v in vs)
            right = any(_same((v[0] + v[2]) / 2, xa1) and v[1] <= ya + 3 and v[3] >= yb - 3 for v in vs)
            if left and right:
                layout.boxes.append((xa0, ya, xa1, yb))
                break
    # Drop boxes that are really a detected table's outline.
    layout.boxes = [bx for bx in layout.boxes if not any(_contains(t.bbox, bx, 4) for t in layout.tables)]
    return layout


def _contains(outer: Rect, inner: Rect, tol: float = 0.0) -> bool:
    return (
        inner[0] >= outer[0] - tol and inner[1] >= outer[1] - tol
        and inner[2] <= outer[2] + tol and inner[3] <= outer[3] + tol
    )


def center_in(rect: Rect, bbox: Rect, tol: float = 1.0) -> bool:
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return rect[0] - tol <= cx <= rect[2] + tol and rect[1] - tol <= cy <= rect[3] + tol
