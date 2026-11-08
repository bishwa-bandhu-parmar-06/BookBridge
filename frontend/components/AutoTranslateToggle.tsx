"use client";

import { useState } from "react";

import { api } from "@/lib/api";
import type { SessionSummary } from "@/lib/types";
import { Bi, Spinner } from "./ui";

/** "Keep translating the next chapters in the background" switch. */
export default function AutoTranslateToggle({
  session,
  afterChapterId,
  onChange,
  onError,
  compact = false,
}: {
  session: SessionSummary;
  afterChapterId?: string;
  onChange: (s: SessionSummary) => void;
  onError: (e: unknown) => void;
  compact?: boolean;
}) {
  const [saving, setSaving] = useState(false);
  const on = session.auto_translate;

  async function toggle() {
    setSaving(true);
    try {
      onChange(await api.setAutoTranslate(session.session_id, !on, afterChapterId));
    } catch (e) {
      onError(e);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={`flex items-start gap-3 rounded-xl ${compact ? "" : "bg-indigo-50/60 p-3 ring-1 ring-indigo-100"}`}>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        onClick={toggle}
        disabled={saving}
        className={`relative mt-0.5 inline-flex h-6 w-11 shrink-0 items-center rounded-full transition ${
          on ? "bg-indigo-700" : "bg-slate-300"
        } disabled:opacity-60`}
      >
        <span className={`inline-block size-5 rounded-full bg-white shadow transition ${on ? "translate-x-5" : "translate-x-0.5"}`} />
      </button>
      <div className="text-sm">
        <p className="font-medium text-slate-900">
          {saving && <Spinner className="mr-1 size-3" />}
          <Bi en="Keep translating the next chapters in the background" hi="अगले अध्यायों का अनुवाद पृष्ठभूमि में करते रहें" />
        </p>
        {!compact && (
          <p className="text-xs text-slate-600">
            <Bi
              en="Read one chapter while the next ones get ready. Uses your AI quota; turn it off anytime."
              hi="एक अध्याय पढ़ें, तब तक अगले तैयार होते रहेंगे। यह आपके AI कोटे का उपयोग करता है; कभी भी बंद करें।"
            />
          </p>
        )}
      </div>
    </div>
  );
}
