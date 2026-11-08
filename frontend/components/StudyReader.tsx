"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, downloadPdf, preview, type PdfOptions, type PreviewTarget } from "@/lib/api";
import { HIGHLIGHT_CLASS, answerSpans, eraseRange, groupBoxes, parseTable, segments, tableView } from "@/lib/book";
import type { Annotation, ChapterDetail, HighlightColor, Paragraph } from "@/lib/types";
import PdfPreview from "./PdfPreview";
import { Bi, BiStack, Button, ErrorBox, Spinner } from "./ui";

const EMPTY: Annotation = { highlights: [], note: "", star: false };
const COLORS: HighlightColor[] = ["yellow", "green", "pink", "blue"];
const SCALE_KEY = "bookbridge-font-scale";
const MIN_SCALE = 0.8;
const MAX_SCALE = 1.6;

type Selection = { pid: string; start: number; end: number; x: number; y: number };

function readScale(): number {
  try {
    const v = Number(window.localStorage.getItem(SCALE_KEY));
    return v >= MIN_SCALE && v <= MAX_SCALE ? v : 1;
  } catch {
    return 1;
  }
}

/** Map a DOM selection boundary to (paragraph id, character offset in its text). */
function boundary(node: Node, offset: number): { pid: string; off: number } | null {
  const el = node.nodeType === Node.TEXT_NODE ? node.parentElement : (node as HTMLElement);
  const seg = el?.closest<HTMLElement>("[data-off]");
  const para = el?.closest<HTMLElement>("[data-pid]");
  if (!seg || !para) return null;
  const base = Number(seg.dataset.off);
  return { pid: para.dataset.pid!, off: base + (node.nodeType === Node.TEXT_NODE ? offset : 0) };
}

function readSelection(root: HTMLElement | null): Selection | null {
  const s = window.getSelection();
  if (!root || !s || s.isCollapsed || s.rangeCount === 0) return null;
  const r = s.getRangeAt(0);
  if (!root.contains(r.commonAncestorContainer)) return null;
  const a = boundary(r.startContainer, r.startOffset);
  const b = boundary(r.endContainer, r.endOffset);
  if (!a || !b || a.pid !== b.pid || a.off === b.off) return null;
  const rect = r.getBoundingClientRect();
  return { pid: a.pid, start: Math.min(a.off, b.off), end: Math.max(a.off, b.off), x: rect.left + rect.width / 2, y: rect.top };
}

/** Read & study: the translated chapter as a book page with highlights, stars, notes, text size. */
export default function StudyReader() {
  const { id: sid, chapterId: cid } = useParams<{ id: string; chapterId: string }>();
  const [chapter, setChapter] = useState<ChapterDetail | null>(null);
  const [ann, setAnn] = useState<Record<string, Annotation>>({});
  const [loadError, setLoadError] = useState<unknown>(null);
  const [error, setError] = useState<unknown>(null);
  const [scale, setScale] = useState(() => (typeof window === "undefined" ? 1 : readScale()));
  const [onlyMarked, setOnlyMarked] = useState(false);
  const [showOriginal, setShowOriginal] = useState(false);
  const [includeAnn, setIncludeAnn] = useState(true);
  const [sel, setSel] = useState<Selection | null>(null);
  const [noteFor, setNoteFor] = useState<string | null>(null);
  const [noteDraft, setNoteDraft] = useState("");
  const [previewOpen, setPreviewOpen] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const articleRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let ignore = false;
    api.getChapter(sid, cid).then(
      (c) => {
        if (ignore) return;
        setChapter(c);
        setAnn(c.annotations ?? {});
      },
      (e) => !ignore && setLoadError(e),
    );
    return () => {
      ignore = true;
    };
  }, [sid, cid]);

  // Phones select text with handles (no mouseup), so also watch selection changes.
  useEffect(() => {
    let t: ReturnType<typeof setTimeout> | undefined;
    const onChange = () => {
      clearTimeout(t);
      t = setTimeout(() => setSel(readSelection(articleRef.current)), 250);
    };
    document.addEventListener("selectionchange", onChange);
    return () => {
      document.removeEventListener("selectionchange", onChange);
      clearTimeout(t);
    };
  }, []);

  const changeScale = (delta: number) => {
    setScale((cur) => {
      const next = Math.round(Math.min(MAX_SCALE, Math.max(MIN_SCALE, cur + delta)) * 10) / 10;
      try {
        window.localStorage.setItem(SCALE_KEY, String(next));
      } catch {
        /* private mode: size just isn't remembered */
      }
      return next;
    });
  };

  const save = useCallback(
    async (pid: string, next: Annotation) => {
      const prev = ann[pid];
      setAnn((m) => ({ ...m, [pid]: next }));
      try {
        const saved = await api.saveAnnotation(sid, cid, pid, next);
        setAnn((m) => {
          const copy = { ...m };
          if (!saved.highlights.length && !saved.note && !saved.star) delete copy[pid];
          else copy[pid] = saved;
          return copy;
        });
      } catch (e) {
        setAnn((m) => ({ ...m, [pid]: prev ?? EMPTY }));
        setError(e);
      }
    },
    [ann, sid, cid],
  );

  const clearSelection = () => {
    window.getSelection()?.removeAllRanges();
    setSel(null);
  };

  const highlight = (color: HighlightColor | null) => {
    if (!sel) return;
    const a = ann[sel.pid] ?? EMPTY;
    const rest = eraseRange(a.highlights, sel.start, sel.end);
    save(sel.pid, { ...a, highlights: color ? [...rest, { start: sel.start, end: sel.end, color }] : rest });
    clearSelection();
  };

  const toggleStar = (pid: string) => {
    const a = ann[pid] ?? EMPTY;
    save(pid, { ...a, star: !a.star });
  };

  const openNote = (pid: string) => {
    setNoteFor(pid);
    setNoteDraft(ann[pid]?.note ?? "");
    clearSelection();
  };

  const saveNote = () => {
    if (!noteFor) return;
    const a = ann[noteFor] ?? EMPTY;
    save(noteFor, { ...a, note: noteDraft.trim() });
    setNoteFor(null);
  };

  const pdfOptions = useMemo<PdfOptions>(() => ({ fontScale: scale, annotations: includeAnn }), [scale, includeAnn]);
  const target = useMemo<PreviewTarget>(() => ({ kind: "chapter", cid }), [cid]);

  const download = async () => {
    setDownloading(true);
    try {
      await downloadPdf(preview.downloadUrl(sid, target, pdfOptions), `chapter-${cid}.pdf`);
    } catch (e) {
      setError(e);
    } finally {
      setDownloading(false);
    }
  };

  if (loadError) {
    return (
      <div className="mx-auto max-w-xl space-y-4">
        <ErrorBox error={loadError} />
        <Link href={`/session/${sid}`} className="text-indigo-700 underline">
          ← <Bi en="Back to chapters" hi="अध्यायों पर वापस" />
        </Link>
      </div>
    );
  }
  if (!chapter) {
    return (
      <div className="flex items-center gap-2 text-slate-600">
        <Spinner /> <Bi en="Loading…" hi="लोड हो रहा है…" />
      </div>
    );
  }

  const title = chapter.translated_title ?? chapter.title;
  // Same rule as the PDF: headings a chapter opens with that repeat the chapter title are dropped;
  // a big heading before it (e.g. "Ancient History") is a part title shown once above the title.
  const norm = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
  const repeatsTitle = (p: Paragraph) => {
    const t = norm(p.translated ?? ""), o = norm(p.original), tt = norm(title), ot = norm(chapter.title);
    return (!!t && !!tt && (t.includes(tt) || tt.includes(t))) || (!!o && ot.includes(o));
  };
  let lead = 0;
  while (lead < chapter.paragraphs.length && chapter.paragraphs[lead].type === "heading" && !chapter.paragraphs[lead].group) lead++;
  const titleAt = chapter.paragraphs.slice(0, lead).findIndex(repeatsTitle);
  const parts: string[] = [];
  let paras: Paragraph[] = [];
  chapter.paragraphs.slice(0, lead).forEach((p, i) => {
    if (repeatsTitle(p)) return;
    if (titleAt >= 0 && i < titleAt && (p.level ?? 3) <= 1) parts.push(p.translated ?? p.original);
    else paras.push(p);
  });
  paras = [...paras, ...chapter.paragraphs.slice(lead)];
  const marked = (p: Paragraph) => {
    const a = ann[p.id];
    return !!a && (a.star || !!a.note || a.highlights.length > 0);
  };
  if (onlyMarked) paras = paras.filter((p) => marked(p) || (p.type === "heading" && (p.level ?? 3) <= 2));
  const markedCount = chapter.paragraphs.filter(marked).length;
  const canStudy = chapter.status === "review" || chapter.status === "approved";

  return (
    <div className="space-y-4 pb-16">
      {/* Toolbar */}
      <div className="sticky top-0 z-20 -mx-4 flex flex-wrap items-center gap-2 border-b border-slate-200 bg-white/95 px-4 py-2 backdrop-blur">
        <Link href={`/session/${sid}/chapter/${cid}`} className="text-sm text-indigo-700 hover:underline">
          ← <Bi en="Review" hi="समीक्षा" />
        </Link>
        <div className="flex items-center rounded-lg ring-1 ring-slate-300" role="group" aria-label="Text size">
          <button type="button" onClick={() => changeScale(-0.1)} disabled={scale <= MIN_SCALE} className="px-3 py-2 text-sm font-semibold disabled:opacity-40" aria-label="Smaller text">
            A−
          </button>
          <span className="min-w-12 text-center text-xs tabular-nums text-slate-600" suppressHydrationWarning>
            {Math.round(scale * 100)}%
          </span>
          <button type="button" onClick={() => changeScale(0.1)} disabled={scale >= MAX_SCALE} className="px-3 py-2 text-base font-semibold disabled:opacity-40" aria-label="Bigger text">
            A+
          </button>
        </div>
        <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg px-2 py-2 text-sm ring-1 ring-slate-300">
          <input type="checkbox" checked={onlyMarked} onChange={(e) => setOnlyMarked(e.target.checked)} className="accent-amber-500" />
          <Bi en={`Only my marks (${markedCount})`} hi="केवल मेरे चिह्न" />
        </label>
        <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg px-2 py-2 text-sm ring-1 ring-slate-300">
          <input type="checkbox" checked={showOriginal} onChange={(e) => setShowOriginal(e.target.checked)} className="accent-indigo-700" />
          <Bi en="Show Hindi" hi="हिंदी दिखाएँ" />
        </label>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <label className="inline-flex items-center gap-1.5 text-xs text-slate-600">
            <input type="checkbox" checked={includeAnn} onChange={(e) => setIncludeAnn(e.target.checked)} className="accent-indigo-700" />
            <Bi en="Marks in PDF" hi="PDF में चिह्न" />
          </label>
          <Button variant="secondary" onClick={() => setPreviewOpen(true)} className="min-h-10 px-3 py-1.5">
            👁 <BiStack en="Preview" hi="देखें" />
          </Button>
          <Button onClick={download} disabled={downloading} className="min-h-10 px-3 py-1.5">
            {downloading ? <Spinner /> : "⬇"} <BiStack en="PDF" hi="PDF" />
          </Button>
        </div>
      </div>

      <p className="text-xs text-slate-500">
        <Bi
          en="Select words to highlight them · ☆ marks a point important · ✎ adds your note. Your marks are saved and included in the PDF."
          hi="शब्द चुनकर हाइलाइट करें · ☆ महत्वपूर्ण · ✎ अपना नोट। आपके चिह्न सहेजे जाते हैं और PDF में आते हैं।"
        />
      </p>
      <ErrorBox error={error} onDismiss={() => setError(null)} />
      {!canStudy && (
        <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
          <Bi en="This chapter is not translated yet." hi="इस अध्याय का अनुवाद अभी नहीं हुआ है।" />
        </p>
      )}

      {/* Book page */}
      <article
        ref={articleRef}
        lang={chapter.target_lang}
        onMouseUp={() => setTimeout(() => setSel(readSelection(articleRef.current)), 0)}
        className="mx-auto max-w-3xl rounded-sm bg-white px-4 py-6 leading-relaxed text-slate-900 shadow-sm ring-1 ring-slate-200 sm:px-10"
        style={{ fontSize: `${16 * scale}px` }}
      >
        {parts.map((part) => (
          <p key={part} className="mb-3 text-center text-[1.8em] font-bold">{part}</p>
        ))}
        <h1 className="mb-5 border-y-2 border-slate-800 bg-slate-100 px-3 py-2 text-center text-[1.6em] font-bold leading-snug">{title}</h1>
        {groupBoxes(paras).map((g, gi) =>
          g.box ? (
            <div key={gi} className="my-4 border border-slate-700 px-4 py-3">
              {g.items.map((p) => (
                <Point key={p.id} p={p} a={ann[p.id]} inBox canStudy={canStudy} showOriginal={showOriginal}
                       onStar={toggleStar} onNote={openNote} noteFor={noteFor} noteDraft={noteDraft}
                       setNoteDraft={setNoteDraft} saveNote={saveNote} cancelNote={() => setNoteFor(null)} />
              ))}
            </div>
          ) : (
            <Point key={g.items[0].id} p={g.items[0]} a={ann[g.items[0].id]} canStudy={canStudy} showOriginal={showOriginal}
                   onStar={toggleStar} onNote={openNote} noteFor={noteFor} noteDraft={noteDraft}
                   setNoteDraft={setNoteDraft} saveNote={saveNote} cancelNote={() => setNoteFor(null)} />
          ),
        )}
        {onlyMarked && markedCount === 0 && (
          <p className="py-8 text-center text-sm text-slate-500">
            <Bi en="No highlights, stars or notes yet." hi="अभी कोई हाइलाइट, स्टार या नोट नहीं।" />
          </p>
        )}
      </article>

      {/* Floating highlight bar for the current text selection */}
      {sel && canStudy && (
        <div
          className="fixed z-30 flex items-center gap-1 rounded-full bg-slate-900 px-2 py-1.5 shadow-xl"
          style={{
            left: Math.max(8, Math.min(sel.x - 130, (typeof window !== "undefined" ? window.innerWidth : 400) - 268)),
            top: Math.max(8, sel.y - 52),
          }}
          onMouseDown={(e) => e.preventDefault()} // keep the selection while clicking
        >
          {COLORS.map((c) => (
            <button key={c} type="button" onClick={() => highlight(c)} aria-label={`Highlight ${c}`}
                    className={`size-8 rounded-full ring-2 ring-white/70 ${HIGHLIGHT_CLASS[c]}`} />
          ))}
          <button type="button" onClick={() => highlight(null)} className="rounded-full px-2 py-1 text-xs text-white hover:bg-white/10" aria-label="Remove highlight">
            ⌫ <span className="hidden sm:inline">Remove</span>
          </button>
          <button type="button" onClick={() => openNote(sel.pid)} className="rounded-full px-2 py-1 text-xs text-white hover:bg-white/10">
            ✎ Note
          </button>
        </div>
      )}

      {previewOpen && (
        <PdfPreview sid={sid} target={target} title={title} fileName={`chapter-${cid}.pdf`} options={pdfOptions} onClose={() => setPreviewOpen(false)} />
      )}
    </div>
  );
}

function Segs({ text, a, start = 0, end }: { text: string; a?: Annotation; start?: number; end?: number }) {
  return (
    <>
      {segments(text, a?.highlights ?? [], start, end ?? text.length).map((s) => (
        <span key={s.start} data-off={s.start} className={s.color ? `${HIGHLIGHT_CLASS[s.color]} rounded-sm` : undefined}>
          {s.text}
        </span>
      ))}
    </>
  );
}

function Point({
  p, a, inBox = false, canStudy, showOriginal, onStar, onNote, noteFor, noteDraft, setNoteDraft, saveNote, cancelNote,
}: {
  p: Paragraph;
  a?: Annotation;
  inBox?: boolean;
  canStudy: boolean;
  showOriginal: boolean;
  onStar: (pid: string) => void;
  onNote: (pid: string) => void;
  noteFor: string | null;
  noteDraft: string;
  setNoteDraft: (v: string) => void;
  saveNote: () => void;
  cancelNote: () => void;
}) {
  const text = p.translated ?? p.original;
  const star = a?.star ? <span className="mr-1 text-amber-600">★</span> : null;
  let body: React.ReactNode;

  if (p.type === "heading") {
    const lvl = p.level ?? 3;
    const cls = inBox
      ? "text-center font-bold"
      : lvl === 1
        ? "mt-6 mb-3 text-center text-[1.35em] font-bold"
        : lvl === 2
          ? "mt-5 mb-2 bg-slate-200 px-3 py-1 text-center text-[1.1em] font-bold"
          : "mt-4 mb-1.5 font-bold before:mr-1.5 before:content-['❑']";
    body = <div className={cls}>{star}<Segs text={text} a={a} /></div>;
  } else if (p.type === "table") {
    const rows = tableView(parseTable(text));
    body = (
      <div className="my-2 overflow-x-auto">
        {star}
        <table className="border-collapse text-[0.92em]">
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className={r.kind !== "body" ? "bg-slate-100 font-semibold" : ""}>
                {r.kind === "title" ? (
                  <td colSpan={r.span} className="border border-slate-500 px-2 py-1 text-center">{r.cells[0]}</td>
                ) : (
                  r.cells.map((c, j) => <td key={j} className="border border-slate-500 px-2 py-1 align-top">{c}</td>)
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  } else if (p.type === "formula") {
    body = <div className="my-2 bg-slate-50 py-1.5 text-center font-mono">{star}<Segs text={text} a={a} /></div>;
  } else {
    const spans = p.type === "list_item" || p.type === "paragraph" ? answerSpans(text) : null;
    body = spans ? (
      <div className="flex flex-wrap items-baseline gap-x-3">
        <span className="pl-4 -indent-4">{star}<Segs text={text} a={a} start={0} end={spans[0]} /></span>
        <span className="ml-auto text-right font-bold">– <Segs text={text} a={a} start={spans[1]} end={spans[2]} /></span>
      </div>
    ) : (
      <p className={`${p.type === "list_item" ? "pl-4 -indent-4" : ""} ${inBox ? "" : ""}`}>{star}<Segs text={text} a={a} /></p>
    );
  }

  return (
    <div data-pid={p.id} className="group relative my-1.5 pr-14">
      {body}
      {showOriginal && p.type !== "table" && (
        <p lang="hi" className="mt-0.5 text-[0.8em] text-slate-500">{p.original}</p>
      )}
      {a?.note && noteFor !== p.id && (
        <div className="mt-1 ml-4 border-l-4 border-amber-400 bg-amber-50 px-2 py-1 text-[0.85em] text-amber-900">
          <b>✎</b> {a.note}
        </div>
      )}
      {noteFor === p.id && (
        <div className="mt-1 ml-4 space-y-1.5">
          <textarea value={noteDraft} onChange={(e) => setNoteDraft(e.target.value)} rows={3} maxLength={2000} autoFocus
                    placeholder="Your note / आपका नोट" className="w-full rounded-md border border-amber-300 p-2 text-[0.9em]" />
          <div className="flex gap-2 text-sm">
            <button type="button" onClick={saveNote} className="rounded-md bg-amber-500 px-3 py-1 font-medium text-white">Save / सहेजें</button>
            <button type="button" onClick={cancelNote} className="rounded-md px-3 py-1 text-slate-600">Cancel / रद्द करें</button>
          </div>
        </div>
      )}
      {canStudy && (
        <div className="absolute top-0 right-0 flex gap-0.5 opacity-50 transition group-hover:opacity-100 focus-within:opacity-100">
          <button type="button" onClick={() => onStar(p.id)} aria-label={a?.star ? "Remove star" : "Mark important"}
                  className={`grid size-7 place-items-center rounded text-base ${a?.star ? "text-amber-600" : "text-slate-500"} hover:bg-amber-50`}>
            {a?.star ? "★" : "☆"}
          </button>
          <button type="button" onClick={() => onNote(p.id)} aria-label="Add note"
                  className="grid size-7 place-items-center rounded text-sm text-slate-500 hover:bg-amber-50">
            ✎
          </button>
        </div>
      )}
    </div>
  );
}
