"use client";

import { useState } from "react";

import { originalPageUrl } from "@/lib/api";
import { Bi } from "./ui";

/**
 * Shown above the text of a page that was read with AI (a scan or photo): lets the student
 * open the original page image and check what was read.
 */
export default function ScannedPageRow({ sid, page }: { sid: string; page: number }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="border-b border-slate-100 bg-amber-50/60 px-4 py-2 text-sm">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-3 text-left text-amber-900"
      >
        <span>
          📷 <Bi en={`Scanned page ${page} — read with AI`} hi={`स्कैन पृष्ठ ${page} — AI से पढ़ा गया`} />
        </span>
        <span className="shrink-0 font-medium underline">
          {open ? <Bi en="Hide page" hi="पृष्ठ छिपाएँ" /> : <Bi en="Compare with original" hi="मूल से मिलाएँ" />}
        </span>
      </button>
      {open && (
        // eslint-disable-next-line @next/next/no-img-element -- a private, per-session page image
        <img
          src={originalPageUrl(sid, page, 1000)}
          alt={`Original page ${page}`}
          className="mx-auto mt-2 w-full max-w-2xl rounded-md bg-white shadow ring-1 ring-slate-200"
        />
      )}
    </li>
  );
}
