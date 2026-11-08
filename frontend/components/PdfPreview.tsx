"use client";

import { useEffect, useRef, useState } from "react";

import { DEFAULT_PDF_OPTIONS, downloadPdf, preview, type PdfOptions, type PreviewTarget } from "@/lib/api";
import type { PreviewInfo } from "@/lib/types";
import { Bi, BiStack, Button, ErrorBox, Spinner } from "./ui";

/**
 * Full-screen preview of the translated PDF before downloading. Pages are rendered as images
 * on the server, so it looks exactly like the PDF and works on phones too (mobile browsers
 * cannot show a PDF inside a web page).
 */
export default function PdfPreview({
  sid,
  target,
  title,
  fileName,
  options = DEFAULT_PDF_OPTIONS,
  onClose,
}: {
  sid: string;
  target: PreviewTarget;
  title: string;
  fileName: string;
  /** text size and whether to include the student's highlights / notes */
  options?: PdfOptions;
  onClose: () => void;
}) {
  const [info, setInfo] = useState<PreviewInfo | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [downloading, setDownloading] = useState(false);
  const [current, setCurrent] = useState(1);
  const scroller = useRef<HTMLDivElement>(null);
  // Sharp on high-density screens without huge images.
  const [imgWidth] = useState(() => {
    if (typeof window === "undefined") return 1000;
    const css = Math.min(window.innerWidth || 900, 900);
    const px = Math.round(css * (window.devicePixelRatio || 1));
    return Math.max(600, Math.min(1600, px)); // the server accepts 300–1800
  });

  useEffect(() => {
    let ignore = false;
    preview.prepare(sid, target, options).then(
      (i) => !ignore && setInfo(i),
      (e) => !ignore && setError(e),
    );
    return () => {
      ignore = true;
    };
  }, [sid, target, options]);

  // Esc closes; the page behind does not scroll while the preview is open.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  // Track which page is in view for the "page X of N" counter.
  useEffect(() => {
    const root = scroller.current;
    if (!root || !info) return;
    const obs = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio);
        if (visible[0]) setCurrent(Number((visible[0].target as HTMLElement).dataset.page));
      },
      { root, threshold: [0.3, 0.6] },
    );
    root.querySelectorAll("[data-page]").forEach((el) => obs.observe(el));
    return () => obs.disconnect();
  }, [info]);

  async function download() {
    setDownloading(true);
    try {
      await downloadPdf(preview.downloadUrl(sid, target, options), fileName);
    } catch (e) {
      setError(e);
    } finally {
      setDownloading(false);
    }
  }

  const ratio = info ? info.height_pt / info.width_pt : 1.414;

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-slate-900/90" role="dialog" aria-modal="true" aria-label="PDF preview">
      <div className="flex items-center gap-2 bg-white px-3 py-2 shadow sm:px-4">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-slate-900">
            <Bi en="Preview" hi="पूर्वावलोकन" />: {title}
          </p>
          {info && (
            <p className="text-xs text-slate-500">
              <Bi en={`Page ${current} of ${info.pages}`} hi={`पृष्ठ ${current} / ${info.pages}`} />
            </p>
          )}
        </div>
        <Button onClick={download} disabled={downloading || !info} className="px-3">
          {downloading ? <Spinner /> : "⬇"}
          <BiStack en="Download PDF" hi="PDF डाउनलोड" />
        </Button>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close preview"
          className="grid size-10 place-items-center rounded-lg text-xl text-slate-600 hover:bg-slate-100"
        >
          ✕
        </button>
      </div>

      <div ref={scroller} className="flex-1 overflow-y-auto px-2 py-4 sm:px-6">
        {error ? (
          <div className="mx-auto max-w-xl">
            <ErrorBox error={error} />
          </div>
        ) : !info ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-white">
            <Spinner className="size-8" />
            <p className="text-sm">
              <Bi en="Preparing the PDF preview…" hi="PDF पूर्वावलोकन तैयार हो रहा है…" />
            </p>
          </div>
        ) : (
          <div className="mx-auto flex max-w-[900px] flex-col gap-4">
            {Array.from({ length: info.pages }, (_, i) => i + 1).map((page) => (
              <div
                key={page}
                data-page={page}
                className="relative w-full overflow-hidden rounded-sm bg-white shadow-lg"
                style={{ aspectRatio: `1 / ${ratio}` }}
              >
                {/* eslint-disable-next-line @next/next/no-img-element -- server-rendered page images */}
                <img
                  src={preview.pageUrl(sid, target, page, imgWidth, info.version)}
                  alt={`Page ${page}`}
                  loading={page <= 2 ? "eager" : "lazy"}
                  className="absolute inset-0 size-full"
                />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
