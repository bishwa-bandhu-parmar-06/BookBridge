"use client";

import { useState } from "react";

import { api } from "@/lib/api";
import type { ChapterBoundary, SessionSummary } from "@/lib/types";
import { Bi, Button, ErrorBox } from "./ui";

type Row = ChapterBoundary & { key: number };

let nextKey = 1;
const toRows = (s: SessionSummary): Row[] =>
  s.chapters.map((c) => ({ key: nextKey++, title: c.title, start_page: c.start_page, end_page: c.end_page }));

/** Edit chapter boundaries before the first translation: rename, change pages, merge, split, remove. */
export default function ChapterEditor({
  session,
  onSaved,
  onCancel,
}: {
  session: SessionSummary;
  onSaved: (s: SessionSummary) => void;
  onCancel: () => void;
}) {
  const [rows, setRows] = useState<Row[]>(() => toRows(session));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const update = (key: number, patch: Partial<ChapterBoundary>) =>
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));

  const mergeWithNext = (i: number) =>
    setRows((rs) => {
      if (i + 1 >= rs.length) return rs;
      const merged = { ...rs[i], end_page: rs[i + 1].end_page };
      return [...rs.slice(0, i), merged, ...rs.slice(i + 2)];
    });

  const split = (i: number) =>
    setRows((rs) => {
      const r = rs[i];
      if (r.end_page <= r.start_page) return rs;
      const mid = Math.floor((r.start_page + r.end_page + 1) / 2);
      const a = { ...r, end_page: mid - 1 };
      const b = { key: nextKey++, title: `${r.title} (2)`, start_page: mid, end_page: r.end_page };
      return [...rs.slice(0, i), a, b, ...rs.slice(i + 1)];
    });

  const remove = (i: number) => setRows((rs) => (rs.length > 1 ? rs.filter((_, j) => j !== i) : rs));

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const updated = await api.updateChapters(
        session.session_id,
        rows.map(({ title, start_page, end_page }) => ({ title, start_page, end_page })),
      );
      onSaved(updated);
    } catch (e) {
      setError(e);
    } finally {
      setSaving(false);
    }
  }

  const num = "w-20 rounded-md border border-slate-300 px-2 py-1.5 text-sm tabular-nums";

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">
        <Bi
          en={`Adjust chapters (the book has ${session.page_count} pages). Chapters must be in order and must not share pages. Pages not in any chapter are skipped.`}
          hi={`अध्याय ठीक करें (किताब में ${session.page_count} पृष्ठ हैं)। अध्याय क्रम में हों और पृष्ठ साझा न करें। जो पृष्ठ किसी अध्याय में नहीं, वे छोड़ दिए जाएँगे।`}
        />
      </p>
      <ol className="space-y-3">
        {rows.map((r, i) => (
          <li key={r.key} className="space-y-2 rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200">
            <div className="flex items-center gap-2">
              <span className="w-6 text-sm font-medium text-slate-500">{i + 1}.</span>
              <input
                aria-label="Chapter title"
                value={r.title}
                onChange={(e) => update(r.key, { title: e.target.value })}
                className="flex-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
              />
            </div>
            <div className="flex flex-wrap items-center gap-2 pl-8 text-sm">
              <label className="flex items-center gap-1">
                <Bi en="From" hi="से" />
                <input
                  type="number"
                  min={1}
                  max={session.page_count}
                  value={r.start_page}
                  onChange={(e) => update(r.key, { start_page: Number(e.target.value) })}
                  className={num}
                />
              </label>
              <label className="flex items-center gap-1">
                <Bi en="To" hi="तक" />
                <input
                  type="number"
                  min={1}
                  max={session.page_count}
                  value={r.end_page}
                  onChange={(e) => update(r.key, { end_page: Number(e.target.value) })}
                  className={num}
                />
              </label>
              <span className="ml-auto flex flex-wrap gap-1">
                <Button variant="ghost" className="min-h-9 px-2 py-1" onClick={() => split(i)} disabled={r.end_page <= r.start_page}>
                  <Bi en="Split" hi="बाँटें" />
                </Button>
                <Button variant="ghost" className="min-h-9 px-2 py-1" onClick={() => mergeWithNext(i)} disabled={i === rows.length - 1}>
                  <Bi en="Merge with next" hi="अगले से जोड़ें" />
                </Button>
                <Button variant="ghost" className="min-h-9 px-2 py-1 text-rose-700" onClick={() => remove(i)} disabled={rows.length === 1}>
                  <Bi en="Remove" hi="हटाएँ" />
                </Button>
              </span>
            </div>
          </li>
        ))}
      </ol>
      <ErrorBox error={error} onDismiss={() => setError(null)} />
      <div className="flex flex-wrap gap-2">
        <Button onClick={save} disabled={saving}>
          <Bi en="Save chapters" hi="अध्याय सहेजें" />
        </Button>
        <Button variant="secondary" onClick={() => setRows(toRows(session))} disabled={saving}>
          <Bi en="Undo changes" hi="बदलाव वापस लें" />
        </Button>
        <Button variant="ghost" onClick={onCancel} disabled={saving}>
          <Bi en="Cancel" hi="रद्द करें" />
        </Button>
      </div>
    </div>
  );
}
