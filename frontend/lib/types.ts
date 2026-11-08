// Shapes returned by the BookBridge backend (see backend/app/schemas.py).

export type Lang = "hi" | "en";
export type ChapterStatus = "pending" | "translating" | "review" | "approved" | "failed";
export type ParagraphType = "heading" | "paragraph" | "list_item" | "formula" | "table_text" | "table";

export interface ChapterSummary {
  id: string;
  title: string;
  translated_title: string | null;
  start_page: number;
  end_page: number;
  status: ChapterStatus;
}

export interface SessionSummary {
  session_id: string;
  book_title: string;
  source_lang: Lang;
  target_lang: Lang;
  detected_lang: Lang;
  page_count: number;
  chapter_detection: "toc" | "contents" | "headings" | "fixed" | "manual";
  chapters: ChapterSummary[];
  warnings: string[];
  created_at: string;
  expires_at: string;
  seconds_remaining: number;
  boundaries_editable: boolean;
  /** keep translating the following chapters in the background */
  auto_translate: boolean;
}

export interface Paragraph {
  id: string;
  page: number;
  type: ParagraphType;
  level: number | null;
  /** paragraphs in the same framed box of the book share a group id */
  group?: string | null;
  original: string;
  translated: string | null;
  flagged: boolean;
  edited: boolean;
  error: boolean;
}

export interface ChapterDetail extends ChapterSummary {
  source_lang: Lang;
  target_lang: Lang;
  paragraphs: Paragraph[];
  active_job_id: string | null;
  /** the student's highlights / notes / stars, by paragraph id */
  annotations: Record<string, Annotation>;
  /** pages of this chapter read with AI (scans / photos); their image can be viewed */
  scanned_pages?: number[];
}

export type HighlightColor = "yellow" | "green" | "pink" | "blue";

/** A highlighted range in a point's translated text (character offsets). */
export interface Highlight {
  start: number;
  end: number;
  color: HighlightColor;
}

export interface Annotation {
  highlights: Highlight[];
  note: string;
  star: boolean;
}

export interface Job {
  job_id: string;
  session_id: string;
  chapter_id: string;
  kind: "translate" | "retranslate";
  status: "queued" | "running" | "done" | "failed";
  progress: number;
  message: string;
  /** temporary warning, e.g. "AI service busy"; cleared when the next part succeeds */
  notice: string | null;
  elapsed_seconds: number;
  error: string | null;
  error_hi: string | null;
}

export interface GlossaryTerm {
  source: string;
  target: string;
  origin: "model" | "user";
}

export interface Glossary {
  source_lang: Lang;
  target_lang: Lang;
  terms: GlossaryTerm[];
}

export interface PublicConfig {
  max_upload_mb: number;
  max_pages: number;
  session_ttl_minutes: number;
}

export interface PreviewInfo {
  pages: number;
  width_pt: number;
  height_pt: number;
  version: number;
}

export interface ChapterBoundary {
  title: string;
  start_page: number;
  end_page: number;
}
