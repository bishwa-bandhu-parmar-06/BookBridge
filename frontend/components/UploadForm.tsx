"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type DragEvent } from "react";

import { ApiError, api, uploadBook } from "@/lib/api";
import type { Lang } from "@/lib/types";
import { Bi, Button, ErrorBox, Notice, ProgressBar, Spinner } from "./ui";

type Direction = "auto" | Lang; // value = source language

const DIRECTIONS: { value: Direction; en: string; hi: string }[] = [
  { value: "auto", en: "Detect automatically", hi: "अपने आप पहचानें" },
  { value: "hi", en: "Hindi → English", hi: "हिंदी → अंग्रेज़ी" },
  { value: "en", en: "English → Hindi", hi: "अंग्रेज़ी → हिंदी" },
];

type Phase = { kind: "idle" } | { kind: "uploading"; progress: number } | { kind: "processing" };

function formatMB(bytes: number) {
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function UploadForm() {
  const router = useRouter();
  const justDeleted = useSearchParams().get("deleted") === "1";
  const inputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [direction, setDirection] = useState<Direction>("auto");
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [error, setError] = useState<unknown>(null);
  const [dragging, setDragging] = useState(false);
  const [limits, setLimits] = useState({ max_upload_mb: 50, max_pages: 500, session_ttl_minutes: 120 });

  useEffect(() => {
    api.config().then(setLimits).catch(() => {});
  }, []);

  const busy = phase.kind !== "idle";
  const ttlHours = limits.session_ttl_minutes / 60;
  const ttlText = Number.isInteger(ttlHours) ? `${ttlHours} hour${ttlHours === 1 ? "" : "s"}` : `${limits.session_ttl_minutes} minutes`;
  const ttlTextHi = Number.isInteger(ttlHours) ? `${ttlHours} घंटे` : `${limits.session_ttl_minutes} मिनट`;

  /** One PDF, or one or more photos of pages (JPG / PNG / WebP). */
  function pick(list: FileList | null | undefined) {
    setError(null);
    const chosen = Array.from(list ?? []);
    if (!chosen.length) return;
    const isPdf = (f: File) => f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf");
    const isImage = (f: File) => /^image\/(jpeg|png|webp)$/.test(f.type) || /\.(jpe?g|png|webp)$/i.test(f.name);
    const ok = (chosen.length === 1 && isPdf(chosen[0])) || chosen.every(isImage);
    if (!ok) {
      setError(
        new ApiError(
          400,
          "unsupported_file",
          "Choose one PDF, or photos of the pages (JPG, PNG or WebP).",
          "एक PDF, या पृष्ठों की फ़ोटो (JPG, PNG या WebP) चुनें।",
        ),
      );
      return;
    }
    const size = chosen.reduce((n, f) => n + f.size, 0);
    if (size > limits.max_upload_mb * 1024 * 1024) {
      setError(
        new ApiError(
          413,
          "file_too_large",
          `These files are ${formatMB(size)}. The maximum is ${limits.max_upload_mb} MB.`,
          `ये फ़ाइलें ${formatMB(size)} की हैं। अधिकतम ${limits.max_upload_mb} MB है।`,
        ),
      );
      return;
    }
    setFiles(chosen);
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    if (!busy) pick(e.dataTransfer.files);
  }

  async function submit() {
    if (!files.length) return;
    setError(null);
    setPhase({ kind: "uploading", progress: 0 });
    try {
      const session = await uploadBook(files, direction, (p) => {
        setPhase(p >= 1 ? { kind: "processing" } : { kind: "uploading", progress: p * 100 });
      });
      router.push(`/session/${session.session_id}`);
    } catch (e) {
      setError(e);
      setPhase({ kind: "idle" });
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-8">
      <div className="space-y-2 text-center">
        <h1 className="text-2xl font-bold text-slate-900 sm:text-3xl">
          Translate your textbook
          <span lang="hi" className="font-hindi mt-1 block text-xl font-semibold text-indigo-800 sm:text-2xl">
            अपनी किताब का अनुवाद करें
          </span>
        </h1>
        <p className="text-sm text-slate-600">
          Hindi ⇄ English, chapter by chapter, as a clean PDF.{" "}
          <span lang="hi">हिंदी ⇄ अंग्रेज़ी, अध्याय दर अध्याय, साफ़ PDF में।</span>
        </p>
      </div>

      {justDeleted && (
        <Notice tone="success">
          ✓ <Bi en="Your files were deleted." hi="आपकी फ़ाइलें हटा दी गईं।" />
        </Notice>
      )}

      <section className="space-y-5 rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200 sm:p-7">
        {/* Drop zone */}
        <div
          role="button"
          tabIndex={0}
          aria-disabled={busy}
          onClick={() => !busy && inputRef.current?.click()}
          onKeyDown={(e) => {
            if (!busy && (e.key === "Enter" || e.key === " ")) {
              e.preventDefault();
              inputRef.current?.click();
            }
          }}
          onDragOver={(e) => {
            e.preventDefault();
            if (!busy) setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-10 text-center transition ${
            dragging ? "border-indigo-500 bg-indigo-50" : "border-slate-300 hover:border-indigo-400 hover:bg-slate-50"
          } ${busy ? "pointer-events-none opacity-60" : ""}`}
        >
          <span aria-hidden className="text-3xl">📄</span>
          {files.length ? (
            <>
              <span className="max-w-full truncate font-medium text-slate-900">
                {files.length === 1 ? files[0].name : <Bi en={`${files.length} photos selected`} hi={`${files.length} फ़ोटो चुनी गईं`} />}
              </span>
              <span className="text-xs text-slate-500">
                {formatMB(files.reduce((n, f) => n + f.size, 0))} · <Bi en="Tap to choose again" hi="फिर से चुनने के लिए टैप करें" />
              </span>
            </>
          ) : (
            <>
              <span className="font-medium text-slate-900">
                <Bi en="Upload Book" hi="किताब अपलोड करें" />
              </span>
              <span className="text-sm text-slate-600">
                <Bi en="Drag a PDF or photos of pages here, or tap to choose" hi="PDF या पृष्ठों की फ़ोटो यहाँ खींचें, या चुनने के लिए टैप करें" />
              </span>
              <span className="text-xs text-slate-500">
                <Bi
                  en={`PDF, scanned PDF or photos (JPG/PNG) · up to ${limits.max_upload_mb} MB · ${limits.max_pages} pages`}
                  hi={`PDF, स्कैन PDF या फ़ोटो (JPG/PNG) · अधिकतम ${limits.max_upload_mb} MB · ${limits.max_pages} पृष्ठ`}
                />
              </span>
            </>
          )}
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf,.pdf,image/jpeg,image/png,image/webp"
            multiple
            className="sr-only"
            onChange={(e) => {
              pick(e.target.files);
              e.target.value = "";
            }}
          />
        </div>

        {/* Direction */}
        <fieldset className="space-y-2" disabled={busy}>
          <legend className="mb-2 text-sm font-medium text-slate-800">
            <Bi en="Translation direction" hi="अनुवाद की दिशा" />
          </legend>
          <div className="grid gap-2 sm:grid-cols-3">
            {DIRECTIONS.map((d) => (
              <label
                key={d.value}
                className={`flex cursor-pointer items-start gap-2 rounded-lg p-3 text-sm ring-1 transition ${
                  direction === d.value ? "bg-indigo-50 ring-indigo-500" : "ring-slate-200 hover:bg-slate-50"
                }`}
              >
                <input
                  type="radio"
                  name="direction"
                  value={d.value}
                  checked={direction === d.value}
                  onChange={() => setDirection(d.value)}
                  className="mt-1 accent-indigo-700"
                />
                <span>
                  <span className="block font-medium">{d.en}</span>
                  <span lang="hi" className="block text-slate-600">
                    {d.hi}
                  </span>
                </span>
              </label>
            ))}
          </div>
          {direction === "auto" && (
            <p className="text-xs text-slate-500">
              <Bi
                en="We detect the book's language. You can change the direction on the next screen."
                hi="हम किताब की भाषा पहचानेंगे। अगली स्क्रीन पर दिशा बदल सकते हैं।"
              />
            </p>
          )}
        </fieldset>

        <ErrorBox error={error} onDismiss={() => setError(null)} />

        {phase.kind === "uploading" && <ProgressBar value={phase.progress} label={<Bi en="Uploading" hi="अपलोड हो रहा है" />} />}
        {phase.kind === "processing" && (
          <div className="flex items-center gap-3 rounded-lg bg-indigo-50 p-3 text-sm text-indigo-900">
            <Spinner />
            <span>
              <Bi en="Reading the book and finding chapters…" hi="किताब पढ़ी जा रही है और अध्याय खोजे जा रहे हैं…" />
              <span className="block text-xs text-indigo-700">
                <Bi en="Large books can take up to a minute." hi="बड़ी किताबों में एक मिनट तक लग सकता है।" />
              </span>
            </span>
          </div>
        )}

        <Button className="w-full" disabled={!files.length || busy} onClick={submit}>
          {busy && <Spinner />}
          <Bi en="Upload & find chapters" hi="अपलोड करें और अध्याय खोजें" />
        </Button>
      </section>

      <Notice tone="warn">
        <p>
          Upload only books you own, for personal study. Files are deleted automatically after {ttlText}.
        </p>
        <p lang="hi" className="mt-1">
          केवल अपनी किताबें, व्यक्तिगत अध्ययन के लिए अपलोड करें। फ़ाइलें {ttlTextHi} बाद अपने आप हटा दी जाती हैं।
        </p>
      </Notice>

      <Notice>
        <Bi
          en="Works with digital PDFs, scanned PDFs and photos of pages. Scans and photos are read with AI page by page, which takes a little longer."
          hi="डिजिटल PDF, स्कैन PDF और पृष्ठों की फ़ोटो — सब चलते हैं। स्कैन और फ़ोटो AI से पृष्ठ-दर-पृष्ठ पढ़े जाते हैं, इसमें थोड़ा अधिक समय लगता है।"
        />
      </Notice>
    </div>
  );
}
