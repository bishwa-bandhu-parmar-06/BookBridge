"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { langName } from "@/lib/labels";
import type { Glossary } from "@/lib/types";
import { Bi, Button, ErrorBox, Spinner } from "./ui";

type Row = { key: number; source: string; target: string; origin: "model" | "user" };
let k = 1;

/** View and edit the session glossary. Saved terms are used for every later translation. */
export default function GlossaryPanel({ sid, refreshKey }: { sid: string; refreshKey: number }) {
  const [open, setOpen] = useState(false);
  const [glossary, setGlossary] = useState<Glossary | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [filter, setFilter] = useState("");
  const [savedMsg, setSavedMsg] = useState(false);

  useEffect(() => {
    if (dirty) return; // don't clobber unsaved edits
    api
      .getGlossary(sid)
      .then((g) => {
        setGlossary(g);
        setRows(g.terms.map((t) => ({ ...t, key: k++ })));
      })
      .catch(setError);
  }, [sid, refreshKey, dirty]);

  const edit = (key: number, patch: Partial<Row>) => {
    setDirty(true);
    setSavedMsg(false);
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch, origin: "user" } : r)));
  };

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const g = await api.putGlossary(
        sid,
        rows.filter((r) => r.source.trim() && r.target.trim()).map(({ source, target }) => ({ source, target })),
      );
      setGlossary(g);
      setRows(g.terms.map((t) => ({ ...t, key: k++ })));
      setDirty(false);
      setSavedMsg(true);
    } catch (e) {
      setError(e);
    } finally {
      setSaving(false);
    }
  }

  const visible = rows.filter(
    (r) => !filter || r.source.toLowerCase().includes(filter.toLowerCase()) || r.target.includes(filter),
  );
  const input = "w-full min-w-0 rounded-md border border-slate-300 px-2 py-1.5 text-sm";

  return (
    <section className="rounded-2xl bg-white shadow-sm ring-1 ring-slate-200">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-2 px-5 py-4 text-left"
      >
        <span className="font-semibold">
          📖 <Bi en="Glossary" hi="शब्दावली" />{" "}
          <span className="text-sm font-normal text-slate-500">({glossary?.terms.length ?? 0})</span>
        </span>
        <span aria-hidden className="text-slate-500">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="space-y-3 border-t border-slate-100 px-5 py-4">
          <p className="text-xs text-slate-600">
            <Bi
              en="Technical terms are kept consistent across chapters. Your edits always win over the translator's choices."
              hi="तकनीकी शब्द सभी अध्यायों में एक जैसे रखे जाते हैं। आपके बदलाव हमेशा मान्य होंगे।"
            />
          </p>
          {rows.length > 8 && (
            <input
              placeholder="Search / खोजें"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className={input}
            />
          )}
          {glossary && (
            <div className="grid grid-cols-[1fr_1fr_auto] gap-2 text-xs font-medium text-slate-500">
              <span>{langName[glossary.source_lang].en} / {langName[glossary.source_lang].hi}</span>
              <span>{langName[glossary.target_lang].en} / {langName[glossary.target_lang].hi}</span>
              <span />
            </div>
          )}
          <ul className="max-h-80 space-y-2 overflow-y-auto">
            {visible.map((r) => (
              <li key={r.key} className="grid grid-cols-[1fr_1fr_auto] items-center gap-2">
                <input aria-label="Term" value={r.source} onChange={(e) => edit(r.key, { source: e.target.value })} className={input} />
                <input aria-label="Translation" value={r.target} onChange={(e) => edit(r.key, { target: e.target.value })} className={input} />
                <button
                  type="button"
                  aria-label="Remove term"
                  onClick={() => {
                    setDirty(true);
                    setRows((rs) => rs.filter((x) => x.key !== r.key));
                  }}
                  className="grid size-9 place-items-center rounded-md text-slate-500 hover:bg-rose-50 hover:text-rose-700"
                >
                  ✕
                </button>
              </li>
            ))}
            {rows.length === 0 && (
              <li className="text-sm text-slate-500">
                <Bi en="No terms yet. They appear after the first translation." hi="अभी कोई शब्द नहीं। पहले अनुवाद के बाद दिखेंगे।" />
              </li>
            )}
          </ul>
          <ErrorBox error={error} onDismiss={() => setError(null)} />
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              onClick={() => {
                setDirty(true);
                setFilter("");
                setRows((rs) => [...rs, { key: k++, source: "", target: "", origin: "user" }]);
              }}
            >
              + <Bi en="Add term" hi="शब्द जोड़ें" />
            </Button>
            <Button onClick={save} disabled={!dirty || saving}>
              {saving && <Spinner />}
              <Bi en="Save glossary" hi="शब्दावली सहेजें" />
            </Button>
            {savedMsg && (
              <span className="text-sm text-emerald-700">
                ✓ <Bi en="Saved" hi="सहेजा गया" />
              </span>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
