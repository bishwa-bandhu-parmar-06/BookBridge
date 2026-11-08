"use client";

import { useState } from "react";

import { paragraphTypeLabel } from "@/lib/labels";
import type { Lang, Paragraph } from "@/lib/types";
import { Bi, Button, Spinner } from "./ui";

function Text({ p, text, lang }: { p: Paragraph; text: string; lang: Lang }) {
  if (p.type === "formula") {
    return <div className="rounded-md bg-slate-100 px-3 py-2 text-center font-mono text-sm">{text}</div>;
  }
  if (p.type === "table") {
    // "cell | cell" lines → a real table (first line is the header row)
    const rows = text.split("\n").filter((r) => r.trim()).map((r) => r.split("|").map((c) => c.trim()));
    return (
      <div className="overflow-x-auto">
        <table lang={lang} className="w-full border-collapse text-sm">
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className={i === 0 ? "bg-slate-100 font-semibold" : ""}>
                {row.map((c, j) => (
                  <td key={j} className="border border-slate-300 px-2 py-1 align-top">
                    {c}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  if (p.type === "heading") {
    const size = p.level === 1 ? "text-xl" : p.level === 2 ? "text-lg" : "text-base";
    return (
      <p lang={lang} className={`${size} font-semibold text-slate-900`}>
        {text}
      </p>
    );
  }
  return (
    <p lang={lang} className={`whitespace-pre-wrap ${p.type === "list_item" ? "pl-3" : ""} ${p.type === "table_text" ? "text-sm" : ""}`}>
      {text}
    </p>
  );
}

/** One aligned row: original (left) and translation (right). On mobile only one side is shown. */
export default function ParagraphRow({
  p,
  sourceLang,
  targetLang,
  show,
  editable,
  onToggleFlag,
  onSave,
}: {
  p: Paragraph;
  sourceLang: Lang;
  targetLang: Lang;
  show: "original" | "translation";
  editable: boolean;
  onToggleFlag: (flagged: boolean) => void;
  onSave: (text: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const isFormula = p.type === "formula";

  async function save() {
    if (!draft.trim()) return;
    setSaving(true);
    try {
      await onSave(draft);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  const rowTone = p.error ? "bg-amber-50/70" : p.flagged ? "bg-rose-50/60" : "";

  return (
    <li id={p.id} className={`grid gap-x-6 gap-y-2 border-b border-slate-100 px-4 py-4 md:grid-cols-2 ${rowTone}`}>
      {/* Original */}
      <div className={`${show === "original" ? "block" : "hidden"} md:block`}>
        <Text p={p} text={p.original} lang={sourceLang} />
        {p.type !== "paragraph" && (
          <span className="mt-1 inline-block text-[11px] uppercase tracking-wide text-slate-400">
            {paragraphTypeLabel[p.type].en} · <span lang="hi">{paragraphTypeLabel[p.type].hi}</span>
          </span>
        )}
      </div>

      {/* Translation */}
      <div className={`${show === "translation" ? "block" : "hidden"} space-y-2 md:block`}>
        {editing ? (
          <div className="space-y-2">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={Math.min(12, Math.max(3, Math.ceil(draft.length / 60)))}
              lang={targetLang}
              className="w-full rounded-md border border-indigo-300 p-2 text-[15px] focus:outline-2 focus:outline-indigo-500"
              autoFocus
            />
            <div className="flex gap-2">
              <Button onClick={save} disabled={saving || !draft.trim()} className="min-h-9 py-1.5">
                {saving && <Spinner />}
                <Bi en="Save" hi="सहेजें" />
              </Button>
              <Button variant="ghost" onClick={() => setEditing(false)} disabled={saving} className="min-h-9 py-1.5">
                <Bi en="Cancel" hi="रद्द करें" />
              </Button>
            </div>
          </div>
        ) : p.translated ? (
          <Text p={p} text={p.translated} lang={targetLang} />
        ) : (
          <p className="text-sm italic text-amber-800">
            {p.error ? (
              <Bi en="Could not be translated. Re-translate or edit it." hi="अनुवाद नहीं हो सका। फिर से अनुवाद करें या संपादित करें।" />
            ) : (
              <Bi en="Waiting for translation…" hi="अनुवाद की प्रतीक्षा…" />
            )}
          </p>
        )}

        {editable && !editing && (
          <div className="flex flex-wrap items-center gap-3 text-sm">
            {!isFormula && (
              <label className="inline-flex cursor-pointer items-center gap-1.5 text-slate-700">
                <input
                  type="checkbox"
                  checked={p.flagged}
                  onChange={(e) => onToggleFlag(e.target.checked)}
                  className="size-4 accent-rose-600"
                />
                <Bi en="Flag" hi="चिह्नित करें" />
              </label>
            )}
            <button
              type="button"
              onClick={() => {
                setDraft(p.translated ?? p.original);
                setEditing(true);
              }}
              className="inline-flex items-center gap-1 rounded px-1 text-indigo-700 hover:bg-indigo-50"
            >
              ✎ <Bi en="Edit" hi="संपादित करें" />
            </button>
            {p.edited && (
              <span className="text-xs text-emerald-700">
                <Bi en="edited by you" hi="आपने बदला" />
              </span>
            )}
          </div>
        )}
      </div>
    </li>
  );
}
