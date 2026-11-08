// Book layout helpers shared by the Read & study view. They mirror the PDF rules in
// backend/app/services/pdf_writer.py and annotations.py so the screen matches the download.

import type { Highlight, HighlightColor, Paragraph } from "./types";

const ANSWER_SEP = /\s[–—]\s*|\s-(?:\s+|(?=\S))/g;

/** [questionEnd, answerStart, answerEnd] for "question – answer", else null. */
export function answerSpans(text: string): [number, number, number] | null {
  let last: RegExpExecArray | null = null;
  for (const m of text.matchAll(ANSWER_SEP)) last = m as RegExpExecArray;
  if (!last || last.index === undefined) return null;
  const qEnd = text.slice(0, last.index).trimEnd().length;
  const after = last.index + last[0].length;
  const aStart = after + (text.slice(after).length - text.slice(after).trimStart().length);
  const aEnd = text.trimEnd().length;
  if (qEnd === 0 || aEnd <= aStart || aEnd - aStart > 160) return null;
  return [qEnd, aStart, aEnd];
}

export interface Segment {
  text: string;
  color: HighlightColor | null;
  /** offset of this piece in the paragraph text (used to map a text selection back) */
  start: number;
}

/** Split text[start:end] into highlighted / plain runs. Later highlights win on overlap. */
export function segments(text: string, highlights: Highlight[], start = 0, end = text.length): Segment[] {
  if (start >= end) return [];
  const colors: (HighlightColor | null)[] = new Array(end - start).fill(null);
  for (const h of highlights) {
    for (let i = Math.max(h.start, start); i < Math.min(h.end, end); i++) colors[i - start] = h.color;
  }
  const out: Segment[] = [];
  let runStart = start;
  for (let i = start + 1; i <= end; i++) {
    if (i === end || colors[i - start] !== colors[runStart - start]) {
      out.push({ text: text.slice(runStart, i), color: colors[runStart - start], start: runStart });
      runStart = i;
    }
  }
  return out;
}

/** Remove highlighting from [start, end): overlapping highlights are trimmed or split. */
export function eraseRange(highlights: Highlight[], start: number, end: number): Highlight[] {
  const out: Highlight[] = [];
  for (const h of highlights) {
    if (h.end <= start || h.start >= end) out.push(h);
    else {
      if (h.start < start) out.push({ ...h, end: start });
      if (h.end > end) out.push({ ...h, start: end });
    }
  }
  return out;
}

export function parseTable(text: string): string[][] {
  const rows = text.split("\n").filter((r) => r.trim()).map((r) => r.split("|").map((c) => c.trim()));
  const width = Math.max(0, ...rows.map((r) => r.length));
  return rows.map((r) => [...r, ...new Array(width - r.length).fill("")]);
}

export type TableRow = { kind: "title" | "head" | "body"; cells: string[]; span?: number };

export function tableView(rows: string[][]): TableRow[] {
  const out: TableRow[] = [];
  let headerDone = false;
  const width = rows[0]?.length ?? 0;
  for (const r of rows) {
    const filled = r.filter(Boolean);
    if (width > 1 && filled.length === 1 && !headerDone) out.push({ kind: "title", cells: filled, span: width });
    else if (!headerDone) {
      out.push({ kind: "head", cells: r });
      headerDone = true;
    } else out.push({ kind: "body", cells: r });
  }
  return out;
}

/** Consecutive paragraphs from the same framed box become one group. */
export type BlockGroup = { box: string | null; items: Paragraph[] };

export function groupBoxes(paras: Paragraph[]): BlockGroup[] {
  const out: BlockGroup[] = [];
  for (const p of paras) {
    const g = p.group ?? null;
    const last = out[out.length - 1];
    if (last && g && last.box === g) last.items.push(p);
    else if (g) out.push({ box: g, items: [p] });
    else out.push({ box: null, items: [p] });
  }
  return out;
}

export const HIGHLIGHT_CLASS: Record<HighlightColor, string> = {
  yellow: "bg-yellow-200",
  green: "bg-green-200",
  pink: "bg-pink-200",
  blue: "bg-sky-200",
};
