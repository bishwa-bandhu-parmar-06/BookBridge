// Typed client for the BookBridge API. Every error becomes an ApiError with a
// friendly English + Hindi message.

import type {
  Annotation,
  ChapterBoundary,
  ChapterDetail,
  ChapterSummary,
  Glossary,
  Job,
  Lang,
  Paragraph,
  PreviewInfo,
  PublicConfig,
  SessionSummary,
} from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public messageHi: string = "",
  ) {
    super(message);
  }
}

const NETWORK_ERROR = () =>
  new ApiError(
    0,
    "network_error",
    "Cannot reach the BookBridge server. Check your internet connection and try again.",
    "BookBridge सर्वर से संपर्क नहीं हो पा रहा। इंटरनेट कनेक्शन जाँचें और फिर कोशिश करें।",
  );

function errorFromBody(status: number, body: unknown): ApiError {
  if (body && typeof body === "object" && "message" in body) {
    const b = body as { error?: string; message: string; message_hi?: string };
    return new ApiError(status, b.error ?? "error", b.message, b.message_hi ?? "");
  }
  return new ApiError(status, "error", `Something went wrong (HTTP ${status}).`, "कुछ गड़बड़ हो गई।");
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: init.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json", ...init.headers } : init.headers,
      cache: "no-store",
    });
  } catch {
    throw NETWORK_ERROR();
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) throw errorFromBody(res.status, body);
  return body as T;
}

const json = (data: unknown) => JSON.stringify(data);
const sess = (sid: string) => `/api/sessions/${encodeURIComponent(sid)}`;
const chap = (sid: string, cid: string) => `${sess(sid)}/chapters/${encodeURIComponent(cid)}`;

/** Upload with progress (fetch cannot report upload progress, so XHR is used here). */
export function uploadBook(
  files: File[],
  sourceLang: "auto" | Lang,
  onProgress: (fraction: number) => void,
): Promise<SessionSummary> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    for (const f of files) form.append("file", f);
    form.append("source_lang", sourceLang);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_URL}/api/sessions`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.upload.onload = () => onProgress(1);
    xhr.onerror = () => reject(NETWORK_ERROR());
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* non-JSON body */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as SessionSummary);
      else reject(errorFromBody(xhr.status, body));
    };
    xhr.send(form);
  });
}

export const api = {
  config: () => request<PublicConfig>("/api/config"),

  getSession: (sid: string) => request<SessionSummary>(sess(sid)),
  setDirection: (sid: string, source_lang: Lang) =>
    request<SessionSummary>(sess(sid), { method: "PATCH", body: json({ source_lang }) }),
  deleteSession: (sid: string) => request<{ deleted: boolean }>(sess(sid), { method: "DELETE" }),
  setAutoTranslate: (sid: string, enabled: boolean, afterChapterId?: string) =>
    request<SessionSummary>(`${sess(sid)}/auto-translate`, {
      method: "POST",
      body: json({ enabled, after_chapter_id: afterChapterId ?? null }),
    }),
  updateChapters: (sid: string, chapters: ChapterBoundary[]) =>
    request<SessionSummary>(`${sess(sid)}/chapters`, { method: "PUT", body: json({ chapters }) }),

  getChapter: (sid: string, cid: string) => request<ChapterDetail>(chap(sid, cid)),
  translate: (sid: string, cid: string) => request<{ job_id: string }>(`${chap(sid, cid)}/translate`, { method: "POST" }),
  retranslate: (sid: string, cid: string, paragraph_ids: string[], note?: string) =>
    request<{ job_id: string }>(`${chap(sid, cid)}/retranslate`, {
      method: "POST",
      body: json({ paragraph_ids, note: note?.trim() || null }),
    }),
  editParagraph: (sid: string, cid: string, pid: string, patch: { translated?: string; flagged?: boolean }) =>
    request<Paragraph>(`${chap(sid, cid)}/paragraphs/${encodeURIComponent(pid)}`, { method: "PATCH", body: json(patch) }),
  approve: (sid: string, cid: string) => request<ChapterSummary>(`${chap(sid, cid)}/approve`, { method: "POST" }),
  saveAnnotation: (sid: string, cid: string, pid: string, a: Annotation) =>
    request<Annotation>(`${chap(sid, cid)}/annotations/${encodeURIComponent(pid)}`, { method: "PUT", body: json(a) }),

  getJob: (jobId: string) => request<Job>(`/api/jobs/${encodeURIComponent(jobId)}`),

  getGlossary: (sid: string) => request<Glossary>(`${sess(sid)}/glossary`),
  putGlossary: (sid: string, terms: { source: string; target: string }[]) =>
    request<Glossary>(`${sess(sid)}/glossary`, { method: "PUT", body: json({ terms }) }),
};

export const pdfUrl = {
  chapter: (sid: string, cid: string) => `${API_URL}${chap(sid, cid)}/pdf`,
  book: (sid: string) => `${API_URL}${sess(sid)}/book.pdf`,
};

/** What to preview: one chapter, or the whole book (approved chapters). */
export type PreviewTarget = { kind: "chapter"; cid: string } | { kind: "book" };

const previewBase = (sid: string, t: PreviewTarget) =>
  t.kind === "chapter" ? `${chap(sid, t.cid)}/preview` : `${sess(sid)}/book/preview`;

/** Student options for the PDF: text size and whether to print highlights / notes / stars. */
export interface PdfOptions {
  fontScale: number;
  annotations: boolean;
}

export const DEFAULT_PDF_OPTIONS: PdfOptions = { fontScale: 1, annotations: true };

const optionQuery = (o: PdfOptions) => `font_scale=${o.fontScale.toFixed(2)}&annotations=${o.annotations}`;

/** The uploaded book's page as an image (to compare a scanned page with what was read). */
export const originalPageUrl = (sid: string, page: number, width: number) =>
  `${API_URL}/api/sessions/${sid}/pages/${page}.jpg?width=${width}`;

export const preview = {
  /** Builds the PDF on the server with the latest translations and returns its page count. */
  prepare: (sid: string, t: PreviewTarget, o: PdfOptions = DEFAULT_PDF_OPTIONS) =>
    request<PreviewInfo>(`${previewBase(sid, t)}?${optionQuery(o)}`),
  pageUrl: (sid: string, t: PreviewTarget, page: number, width: number, version: number) =>
    `${API_URL}${previewBase(sid, t)}/${page}.png?width=${width}&v=${version}`,
  downloadUrl: (sid: string, t: PreviewTarget, o: PdfOptions = DEFAULT_PDF_OPTIONS) =>
    `${t.kind === "chapter" ? pdfUrl.chapter(sid, t.cid) : pdfUrl.book(sid)}?${optionQuery(o)}`,
};

/**
 * Download a PDF. Fetches first so a JSON error (e.g. "no approved chapters") is shown
 * to the user instead of opening an error page.
 */
export async function downloadPdf(url: string, fallbackName: string): Promise<void> {
  let res: Response;
  try {
    res = await fetch(url, { cache: "no-store" });
  } catch {
    throw NETWORK_ERROR();
  }
  if (!res.ok) throw errorFromBody(res.status, await res.json().catch(() => null));
  const blob = await res.blob();
  const cd = res.headers.get("content-disposition") ?? "";
  const m = /filename\*=UTF-8''([^;]+)/i.exec(cd) ?? /filename="?([^";]+)"?/i.exec(cd);
  const name = m ? decodeURIComponent(m[1]) : fallbackName;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 10_000);
}
