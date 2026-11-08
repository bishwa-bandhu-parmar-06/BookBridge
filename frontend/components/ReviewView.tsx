"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError, api, downloadPdf, pdfUrl, type PreviewTarget } from "@/lib/api";
import { langName } from "@/lib/labels";
import type { ChapterDetail, Job, SessionSummary } from "@/lib/types";
import AutoTranslateToggle from "./AutoTranslateToggle";
import GlossaryPanel from "./GlossaryPanel";
import ParagraphRow from "./ParagraphRow";
import PdfPreview from "./PdfPreview";
import { Bi, BiStack, Button, ButtonLink, ErrorBox, Notice, ProgressBar, Spinner, StatusBadge } from "./ui";

const POLL_MS = 2000;

function formatElapsed(sec: number) {
  const m = Math.floor(sec / 60);
  return `${m}:${String(sec % 60).padStart(2, "0")}`;
}

export default function ReviewView() {
  const { id: sid, chapterId: cid } = useParams<{ id: string; chapterId: string }>();
  const router = useRouter();

  const [chapter, setChapter] = useState<ChapterDetail | null>(null);
  const [session, setSession] = useState<SessionSummary | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [error, setError] = useState<unknown>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [show, setShow] = useState<"original" | "translation">("translation");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [glossaryKey, setGlossaryKey] = useState(0);
  const [previewOpen, setPreviewOpen] = useState(false);
  const previewTarget = useMemo<PreviewTarget>(() => ({ kind: "chapter", cid }), [cid]);
  const lastProgress = useRef(-1);
  const failedPolls = useRef(0);
  const [offline, setOffline] = useState(false);

  const fetchBoth = useCallback(() => Promise.all([api.getChapter(sid, cid), api.getSession(sid)]), [sid, cid]);

  const apply = useCallback(([c, s]: [ChapterDetail, SessionSummary]) => {
    setChapter(c);
    setSession(s);
    setLoadError(null);
    if (c.active_job_id) setJobId(c.active_job_id);
  }, []);

  /** Re-fetch chapter + session (used after actions). */
  const load = useCallback(async () => {
    try {
      apply(await fetchBoth());
    } catch (e) {
      setLoadError(e);
    }
  }, [fetchBoth, apply]);

  useEffect(() => {
    let ignore = false;
    fetchBoth().then(
      (r) => !ignore && apply(r),
      (e) => !ignore && setLoadError(e),
    );
    return () => {
      ignore = true;
    };
  }, [fetchBoth, apply]);

  // Poll the job every 2 s while it runs; refresh paragraphs as batches complete.
  useEffect(() => {
    if (!jobId) return;
    let stopped = false;
    const tick = async () => {
      try {
        const j = await api.getJob(jobId);
        if (stopped) return;
        failedPolls.current = 0;
        setOffline(false);
        setJob(j);
        if (j.progress !== lastProgress.current) {
          lastProgress.current = j.progress;
          api.getChapter(sid, cid).then((c) => !stopped && setChapter(c)).catch(() => {});
        }
        if (j.status === "done" || j.status === "failed") {
          stopped = true;
          setJobId(null);
          lastProgress.current = -1;
          if (j.status === "failed") {
            setError(new ApiError(500, "job_failed", j.error ?? "Translation failed.", j.error_hi ?? "अनुवाद विफल रहा।"));
          }
          await load();
          setGlossaryKey((x) => x + 1);
        }
      } catch (e) {
        if (e instanceof ApiError && e.code === "job_not_found") {
          stopped = true;
          setJobId(null);
          load();
          return;
        }
        // Server restarting or network down: say so instead of showing a stale status.
        failedPolls.current += 1;
        if (failedPolls.current >= 2) setOffline(true);
      }
    };
    tick();
    const t = setInterval(() => !stopped && tick(), POLL_MS);
    return () => {
      stopped = true;
      clearInterval(t);
    };
  }, [jobId, sid, cid, load]);

  // While background translation is on, refresh chapter statuses so "next chapter ready" updates.
  const autoOn = session?.auto_translate ?? false;
  useEffect(() => {
    if (!autoOn) return;
    const t = setInterval(() => {
      api.getSession(sid).then(setSession).catch(() => {});
    }, 5000);
    return () => clearInterval(t);
  }, [autoOn, sid]);

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

  if (loadError) {
    return (
      <div className="mx-auto max-w-xl space-y-4">
        <ErrorBox error={loadError} />
        <ButtonLink href={`/session/${sid}`} variant="primary">
          ← <Bi en="Back to chapters" hi="अध्यायों पर वापस" />
        </ButtonLink>
      </div>
    );
  }
  if (!chapter || !session) {
    return (
      <div className="flex items-center gap-2 text-slate-600">
        <Spinner /> <Bi en="Loading…" hi="लोड हो रहा है…" />
      </div>
    );
  }

  const translating = chapter.status === "translating" || jobId !== null;
  const editable = !translating && (chapter.status === "review" || chapter.status === "approved");
  const flaggedIds = chapter.paragraphs.filter((p) => p.flagged && p.type !== "formula").map((p) => p.id);
  const untranslated = chapter.paragraphs.filter((p) => !p.translated).length;
  const idx = session.chapters.findIndex((c) => c.id === chapter.id);
  const next = idx >= 0 ? session.chapters[idx + 1] : undefined;
  const otherJobRunning = session.chapters.some((c) => c.status === "translating" && c.id !== chapter.id);
  const src = langName[chapter.source_lang];
  const tgt = langName[chapter.target_lang];

  const patchParagraph = (pid: string, patch: { translated?: string; flagged?: boolean }) =>
    api.editParagraph(sid, cid, pid, patch).then((updated) =>
      setChapter((c) => (c ? { ...c, paragraphs: c.paragraphs.map((p) => (p.id === pid ? updated : p)) } : c)),
    );

  const toggleFlag = (pid: string, flagged: boolean) => {
    // optimistic
    setChapter((c) => (c ? { ...c, paragraphs: c.paragraphs.map((p) => (p.id === pid ? { ...p, flagged } : p)) } : c));
    patchParagraph(pid, { flagged }).catch((e) => {
      setError(e);
      load();
    });
  };

  const startTranslation = () =>
    run("translate", async () => {
      const { job_id } = await api.translate(sid, cid);
      setJob(null);
      setJobId(job_id);
      await load();
    });

  const retranslate = () =>
    run("retranslate", async () => {
      const { job_id } = await api.retranslate(sid, cid, flaggedIds, note);
      setJob(null);
      setJobId(job_id);
      setNote("");
      await load();
    });

  const approve = () =>
    run("approve", async () => {
      await api.approve(sid, cid);
      await load();
    });

  const goNext = () =>
    next &&
    run("next", async () => {
      if (next.status === "pending" || next.status === "failed") await api.translate(sid, next.id);
      router.push(`/session/${sid}/chapter/${next.id}`);
    });

  return (
    <div className="space-y-5 pb-28">
      {/* Header */}
      <div className="space-y-2">
        <Link href={`/session/${sid}`} className="text-sm text-indigo-700 hover:underline">
          ← <Bi en="All chapters" hi="सभी अध्याय" />
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-bold text-slate-900 sm:text-2xl">{chapter.translated_title ?? chapter.title}</h1>
          <StatusBadge status={translating ? "translating" : chapter.status} />
        </div>
        {chapter.translated_title && chapter.translated_title !== chapter.title && (
          <p className="text-sm text-slate-600">{chapter.title}</p>
        )}
        <p className="text-xs text-slate-500">
          <Bi en={`Pages ${chapter.start_page}–${chapter.end_page}`} hi={`पृष्ठ ${chapter.start_page}–${chapter.end_page}`} /> ·{" "}
          {src.en} → {tgt.en}
        </p>
      </div>

      <ErrorBox error={error} onDismiss={() => setError(null)} />

      {/* Not started yet */}
      {(chapter.status === "pending" || chapter.status === "failed") && !jobId && (
        <section className="space-y-3 rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
          <p>
            <Bi
              en={chapter.status === "failed" ? "Translation stopped. Already translated paragraphs are kept." : "This chapter has not been translated yet."}
              hi={chapter.status === "failed" ? "अनुवाद रुक गया। जो अनुच्छेद अनूदित हो चुके हैं, वे सुरक्षित हैं।" : "इस अध्याय का अभी अनुवाद नहीं हुआ है।"}
            />
          </p>
          <Button onClick={startTranslation} disabled={busy !== null || otherJobRunning}>
            {busy === "translate" && <Spinner />}
            <Bi en={chapter.status === "failed" ? "Continue translation" : "Translate this chapter"} hi={chapter.status === "failed" ? "अनुवाद जारी रखें" : "इस अध्याय का अनुवाद करें"} />
          </Button>
          {otherJobRunning && (
            <p className="text-sm text-slate-600">
              <Bi en="Another chapter is translating. Please wait." hi="दूसरे अध्याय का अनुवाद चल रहा है। कृपया प्रतीक्षा करें।" />
            </p>
          )}
        </section>
      )}

      {/* Progress */}
      {translating && (
        <section className="space-y-2 rounded-2xl bg-white p-5 shadow-sm ring-1 ring-sky-200">
          <ProgressBar
            value={job?.progress ?? 0}
            label={
              <span className="inline-flex items-center gap-2">
                <Spinner className="size-3.5 text-sky-700" />
                <Bi en={job?.kind === "retranslate" ? "Re-translating" : "Translating"} hi={job?.kind === "retranslate" ? "फिर से अनुवाद" : "अनुवाद हो रहा है"} />
              </span>
            }
          />
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-slate-700">
            <span>{job?.message ?? "Starting…"}</span>
            {job && <span className="font-mono text-xs tabular-nums text-slate-500">⏱ {formatElapsed(job.elapsed_seconds)}</span>}
          </div>
          {offline ? (
            <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-800">
              <Bi
                en="Can't reach the server right now. Reconnecting… (is the backend still running?)"
                hi="अभी सर्वर से संपर्क नहीं हो पा रहा। फिर से जुड़ रहे हैं… (क्या बैकएंड चल रहा है?)"
              />
            </p>
          ) : (
            job?.notice && (
              <p className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900">
                <Bi en={job.notice} hi="AI सेवा अभी व्यस्त है — दूसरा मॉडल आज़माया जा रहा है…" />
              </p>
            )
          )}
          <p className="text-xs text-slate-500">
            <Bi en="You can leave this page; translation continues." hi="आप यह पेज छोड़ सकते हैं; अनुवाद चलता रहेगा।" />
          </p>
        </section>
      )}

      {chapter.status === "approved" && !translating && (
        <Notice tone="success">
          ✓ <Bi en="Chapter approved. It will be included in the full book PDF." hi="अध्याय स्वीकृत। यह पूरी किताब की PDF में शामिल होगा।" />
        </Notice>
      )}
      {untranslated > 0 && editable && (
        <Notice tone="warn">
          <Bi
            en={`${untranslated} paragraph(s) are not translated. Re-translate or edit them before approving.`}
            hi={`${untranslated} अनुच्छेद का अनुवाद बाकी है। स्वीकृत करने से पहले फिर से अनुवाद या संपादन करें।`}
          />
        </Notice>
      )}

      <section className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
        <AutoTranslateToggle session={session} afterChapterId={cid} onChange={setSession} onError={setError} compact />
        {next && session.auto_translate && (
          <p className="mt-2 pl-14 text-xs text-slate-600">
            {next.status === "review" || next.status === "approved" ? (
              <Bi en={`Next chapter “${next.title}” is ready.`} hi={`अगला अध्याय “${next.title}” तैयार है।`} />
            ) : next.status === "translating" ? (
              <Bi en={`Next chapter “${next.title}” is being translated…`} hi={`अगले अध्याय “${next.title}” का अनुवाद हो रहा है…`} />
            ) : (
              <Bi en="The next chapter will start when this one finishes." hi="यह अध्याय पूरा होते ही अगला शुरू होगा।" />
            )}
          </p>
        )}
      </section>

      <GlossaryPanel sid={sid} refreshKey={glossaryKey} />

      {/* Side-by-side */}
      {chapter.paragraphs.length > 0 && (
        <section className="overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-slate-200">
          {/* mobile toggle */}
          <div className="flex border-b border-slate-200 md:hidden" role="tablist">
            {(["original", "translation"] as const).map((v) => (
              <button
                key={v}
                role="tab"
                aria-selected={show === v}
                onClick={() => setShow(v)}
                className={`flex-1 px-3 py-3 text-sm font-medium ${show === v ? "border-b-2 border-indigo-700 text-indigo-800" : "text-slate-500"}`}
              >
                {v === "original" ? (
                  <Bi en={`Original (${src.en})`} hi={`मूल (${src.hi})`} />
                ) : (
                  <Bi en={`Translation (${tgt.en})`} hi={`अनुवाद (${tgt.hi})`} />
                )}
              </button>
            ))}
          </div>
          {/* desktop headers */}
          <div className="hidden grid-cols-2 gap-6 border-b border-slate-200 bg-slate-50 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500 md:grid">
            <span>
              <Bi en={`Original · ${src.en}`} hi={`मूल · ${src.hi}`} />
            </span>
            <span>
              <Bi en={`Translation · ${tgt.en}`} hi={`अनुवाद · ${tgt.hi}`} />
            </span>
          </div>
          <ul>
            {chapter.paragraphs.map((p) => (
              <ParagraphRow
                key={p.id}
                p={p}
                sourceLang={chapter.source_lang}
                targetLang={chapter.target_lang}
                show={show}
                editable={editable}
                onToggleFlag={(f) => toggleFlag(p.id, f)}
                onSave={(text) =>
                  patchParagraph(p.id, { translated: text }).catch((e) => {
                    setError(e);
                    throw e;
                  })
                }
              />
            ))}
          </ul>
        </section>
      )}

      {previewOpen && (
        <PdfPreview
          sid={sid}
          target={previewTarget}
          title={chapter.translated_title ?? chapter.title}
          fileName={`chapter-${cid}.pdf`}
          onClose={() => setPreviewOpen(false)}
        />
      )}

      {/* Action bar */}
      <div className="fixed inset-x-0 bottom-0 z-10 border-t border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-col gap-2 px-3 py-2 sm:px-4 sm:py-3 lg:flex-row lg:items-center">
          {editable && (
            // On phones the re-translate controls only appear once something is flagged.
            <div className={`${flaggedIds.length ? "flex" : "hidden lg:flex"} flex-1 items-center gap-2`}>
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                maxLength={300}
                placeholder="Note (optional): use simpler words / नोट: सरल शब्द"
                className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
                aria-label="Note for re-translation"
              />
              <Button variant="secondary" onClick={retranslate} disabled={flaggedIds.length === 0 || busy !== null} className="shrink-0 px-3">
                {busy === "retranslate" ? <Spinner /> : "↻"}
                <BiStack en={`Re-translate (${flaggedIds.length})`} hi={`फिर अनुवाद (${flaggedIds.length})`} />
              </Button>
            </div>
          )}
          <div className="grid auto-cols-fr grid-flow-col gap-2 lg:flex">
            {editable && chapter.status !== "approved" && (
              <Button onClick={approve} disabled={busy !== null || untranslated > 0} className="px-2 sm:px-4">
                {busy === "approve" ? <Spinner /> : "✓"}
                <BiStack en="Approve" hi="स्वीकृत करें" />
              </Button>
            )}
            {editable && (
              <ButtonLink href={`/session/${sid}/read/${cid}`} variant="secondary" className="px-2 sm:px-4">
                📖
                <BiStack en="Read & study" hi="पढ़ें" />
              </ButtonLink>
            )}
            {editable && (
              <Button variant="secondary" onClick={() => setPreviewOpen(true)} disabled={busy !== null} className="px-2 sm:px-4">
                👁
                <BiStack en="Preview PDF" hi="PDF देखें" />
              </Button>
            )}
            {editable && (
              <Button
                variant="secondary"
                onClick={() => run("pdf", () => downloadPdf(pdfUrl.chapter(sid, cid), `chapter-${cid}.pdf`))}
                disabled={busy !== null}
                className="px-2 sm:px-4"
              >
                {busy === "pdf" ? <Spinner /> : "⬇"}
                <BiStack en="Chapter PDF" hi="अध्याय PDF" />
              </Button>
            )}
            {next && (
              <Button
                variant={chapter.status === "approved" ? "primary" : "secondary"}
                onClick={goNext}
                disabled={busy !== null || (translating && (next.status === "pending" || next.status === "failed"))}
                className="px-2 sm:px-4"
              >
                {busy === "next" && <Spinner />}
                <BiStack
                  en={next.status === "review" || next.status === "approved" ? "Next chapter ✓ →" : "Next chapter →"}
                  hi="अगला अध्याय"
                />
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
