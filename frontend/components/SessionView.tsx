"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ApiError, api, downloadPdf, pdfUrl, type PreviewTarget } from "@/lib/api";
import { langName } from "@/lib/labels";
import type { ChapterSummary, Lang, SessionSummary } from "@/lib/types";
import AutoTranslateToggle from "./AutoTranslateToggle";
import ChapterEditor from "./ChapterEditor";
import Countdown from "./Countdown";
import PdfPreview from "./PdfPreview";
import { Bi, Button, ButtonLink, ErrorBox, Notice, Spinner, StatusBadge } from "./ui";

export default function SessionView() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [session, setSession] = useState<SessionSummary | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [error, setError] = useState<unknown>(null);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null); // which action is running
  const [expired, setExpired] = useState(false);
  const [previewing, setPreviewing] = useState<{ target: PreviewTarget; title: string; fileName: string } | null>(null);

  const load = useCallback(async () => {
    try {
      setSession(await api.getSession(id));
      setLoadError(null);
    } catch (e) {
      setLoadError(e);
    }
  }, [id]);

  useEffect(() => {
    let ignore = false;
    api.getSession(id).then(
      (s) => !ignore && setSession(s),
      (e) => !ignore && setLoadError(e),
    );
    return () => {
      ignore = true;
    };
  }, [id]);

  // Keep statuses fresh while a chapter is translating.
  const anyTranslating = session?.chapters.some((c) => c.status === "translating") ?? false;
  useEffect(() => {
    if (!anyTranslating) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [anyTranslating, load]);

  async function run(key: string, fn: () => Promise<void>) {
    setBusy(key);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  }

  const translate = (ch: ChapterSummary) =>
    run(`translate-${ch.id}`, async () => {
      await api.translate(id, ch.id);
      router.push(`/session/${id}/chapter/${ch.id}`);
    });

  const changeDirection = (source: Lang) =>
    run("direction", async () => {
      setSession(await api.setDirection(id, source));
    });

  const finish = () => {
    const ok = window.confirm(
      "Delete all files for this book now? This cannot be undone.\nइस किताब की सभी फ़ाइलें अभी हटाएँ? यह वापस नहीं होगा।",
    );
    if (!ok) return;
    run("delete", async () => {
      await api.deleteSession(id);
      router.push("/?deleted=1");
    });
  };

  if (loadError) {
    const notFound = loadError instanceof ApiError && loadError.status === 404;
    return (
      <div className="mx-auto max-w-xl space-y-4">
        <ErrorBox error={loadError} />
        <ButtonLink href="/" variant="primary">
          <Bi en={notFound ? "Upload a book" : "Back to start"} hi={notFound ? "किताब अपलोड करें" : "शुरुआत पर जाएँ"} />
        </ButtonLink>
      </div>
    );
  }
  if (!session) {
    return (
      <div className="flex items-center gap-2 text-slate-600">
        <Spinner /> <Bi en="Loading…" hi="लोड हो रहा है…" />
      </div>
    );
  }

  const approvedCount = session.chapters.filter((c) => c.status === "approved").length;
  const src = langName[session.source_lang];
  const tgt = langName[session.target_lang];

  return (
    <div className="space-y-6">
      {/* Header */}
      <section className="space-y-3 rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="truncate text-xl font-bold text-slate-900">{session.book_title}</h1>
            <p className="text-sm text-slate-600">
              <Bi en={`${session.page_count} pages · ${session.chapters.length} chapters`} hi={`${session.page_count} पृष्ठ · ${session.chapters.length} अध्याय`} />
            </p>
          </div>
          <Countdown secondsRemaining={session.seconds_remaining} onExpire={() => setExpired(true)} />
        </div>

        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="font-medium">
            <Bi en="Direction" hi="दिशा" />:
          </span>
          {session.boundaries_editable ? (
            <select
              value={session.source_lang}
              onChange={(e) => changeDirection(e.target.value as Lang)}
              disabled={busy === "direction"}
              className="rounded-md border border-slate-300 bg-white px-2 py-1.5"
              aria-label="Translation direction"
            >
              <option value="hi">Hindi → English / हिंदी → अंग्रेज़ी</option>
              <option value="en">English → Hindi / अंग्रेज़ी → हिंदी</option>
            </select>
          ) : (
            <span>
              {src.en} → {tgt.en} / <span lang="hi">{src.hi} → {tgt.hi}</span>
            </span>
          )}
          {session.source_lang !== session.detected_lang && (
            <span className="text-amber-700">
              <Bi
                en={`(the book looks like ${langName[session.detected_lang].en})`}
                hi={`(किताब ${langName[session.detected_lang].hi} में लगती है)`}
              />
            </span>
          )}
        </div>
        {session.warnings.length > 0 && (
          <Notice tone="warn">
            <ul className="list-inside list-disc">
              {session.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          </Notice>
        )}
      </section>

      {expired && (
        <Notice tone="warn">
          <Bi en="This session has expired and its files were deleted." hi="यह सत्र समाप्त हो गया और फ़ाइलें हटा दी गईं।" />
        </Notice>
      )}
      <ErrorBox error={error} onDismiss={() => setError(null)} />

      {/* Chapters */}
      <section className="space-y-3 rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold">
            <Bi en="Chapters" hi="अध्याय" />
          </h2>
          {session.boundaries_editable && !editing && (
            <Button variant="secondary" onClick={() => setEditing(true)}>
              ✎ <Bi en="Edit chapters" hi="अध्याय बदलें" />
            </Button>
          )}
        </div>

        {editing ? (
          <ChapterEditor
            session={session}
            onSaved={(s) => {
              setSession(s);
              setEditing(false);
            }}
            onCancel={() => setEditing(false)}
          />
        ) : (
          <>
            {session.chapter_detection === "fixed" && session.boundaries_editable && (
              <Notice>
                <Bi
                  en="No chapters were found, so the book was split every few pages. You can edit the chapters."
                  hi="अध्याय नहीं मिले, इसलिए किताब को कुछ-कुछ पृष्ठों में बाँटा गया। आप अध्याय बदल सकते हैं।"
                />
              </Notice>
            )}
            <AutoTranslateToggle session={session} onChange={setSession} onError={setError} />
            {anyTranslating && (
              <Notice>
                <Bi en="One chapter is translating. Others can start when it finishes." hi="एक अध्याय का अनुवाद चल रहा है। उसके बाद दूसरा शुरू हो सकता है।" />
              </Notice>
            )}
            <ul className="divide-y divide-slate-100">
              {session.chapters.map((ch) => (
                <ChapterRow
                  key={ch.id}
                  sid={id}
                  ch={ch}
                  busy={busy}
                  translateDisabled={anyTranslating || busy !== null || expired}
                  onTranslate={() => translate(ch)}
                  onPreview={() =>
                    setPreviewing({
                      target: { kind: "chapter", cid: ch.id },
                      title: ch.translated_title ?? ch.title,
                      fileName: `chapter-${ch.id}.pdf`,
                    })
                  }
                  onError={setError}
                />
              ))}
            </ul>
          </>
        )}
      </section>

      {/* Book actions */}
      <section className="flex flex-col gap-3 rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap gap-2">
        <Button
          variant="secondary"
          disabled={approvedCount === 0 || busy !== null}
          onClick={() => setPreviewing({ target: { kind: "book" }, title: session.book_title, fileName: "book.pdf" })}
        >
          👁 <Bi en="Preview full book" hi="पूरी किताब देखें" />
        </Button>
        <Button
          disabled={approvedCount === 0 || busy !== null}
          onClick={() => run("book", () => downloadPdf(pdfUrl.book(id), "book.pdf"))}
        >
          {busy === "book" ? <Spinner /> : "⬇"}
          <Bi en={`Download full book (${approvedCount} approved)`} hi={`पूरी किताब डाउनलोड करें (${approvedCount} स्वीकृत)`} />
        </Button>
        </div>
        <Button variant="danger" onClick={finish} disabled={busy !== null}>
          🗑 <Bi en="Finish & delete my files" hi="समाप्त करें और फ़ाइलें हटाएँ" />
        </Button>
      </section>

      {previewing && (
        <PdfPreview
          sid={id}
          target={previewing.target}
          title={previewing.title}
          fileName={previewing.fileName}
          onClose={() => setPreviewing(null)}
        />
      )}
    </div>
  );
}

function ChapterRow({
  sid,
  ch,
  busy,
  translateDisabled,
  onTranslate,
  onPreview,
  onError,
}: {
  sid: string;
  ch: ChapterSummary;
  busy: string | null;
  translateDisabled: boolean;
  onTranslate: () => void;
  onPreview: () => void;
  onError: (e: unknown) => void;
}) {
  const [downloading, setDownloading] = useState(false);
  const canTranslate = ch.status === "pending" || ch.status === "failed";
  const canReview = ch.status !== "pending";
  const canDownload = ch.status === "review" || ch.status === "approved";

  async function download() {
    setDownloading(true);
    try {
      await downloadPdf(pdfUrl.chapter(sid, ch.id), `chapter-${ch.id}.pdf`);
    } catch (e) {
      onError(e);
    } finally {
      setDownloading(false);
    }
  }

  return (
    <li className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center">
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-slate-900">{ch.title}</span>
          <StatusBadge status={ch.status} />
        </div>
        {ch.translated_title && ch.translated_title !== ch.title && (
          <p className="text-sm text-slate-600">{ch.translated_title}</p>
        )}
        <p className="text-xs text-slate-500">
          <Bi
            en={ch.start_page === ch.end_page ? `Page ${ch.start_page}` : `Pages ${ch.start_page}–${ch.end_page}`}
            hi={ch.start_page === ch.end_page ? `पृष्ठ ${ch.start_page}` : `पृष्ठ ${ch.start_page}–${ch.end_page}`}
          />
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        {canTranslate && (
          <Button onClick={onTranslate} disabled={translateDisabled}>
            {busy === `translate-${ch.id}` && <Spinner />}
            <Bi en={ch.status === "failed" ? "Try again" : "Translate"} hi={ch.status === "failed" ? "फिर कोशिश करें" : "अनुवाद करें"} />
          </Button>
        )}
        {canReview && (
          <ButtonLink href={`/session/${sid}/chapter/${ch.id}`} variant={ch.status === "review" ? "primary" : "secondary"}>
            <Bi en={ch.status === "translating" ? "View progress" : "Review"} hi={ch.status === "translating" ? "प्रगति देखें" : "समीक्षा"} />
          </ButtonLink>
        )}
        {canDownload && (
          <ButtonLink href={`/session/${sid}/read/${ch.id}`} variant="secondary">
            📖 <Bi en="Read" hi="पढ़ें" />
          </ButtonLink>
        )}
        {canDownload && (
          <Button variant="secondary" onClick={onPreview}>
            👁 <Bi en="Preview" hi="देखें" />
          </Button>
        )}
        {canDownload && (
          <Button variant="secondary" onClick={download} disabled={downloading}>
            {downloading ? <Spinner /> : "⬇"} PDF
          </Button>
        )}
      </div>
    </li>
  );
}
