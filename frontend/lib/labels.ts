// Bilingual labels (English + Hindi) used across the UI.

import type { ChapterStatus, Lang } from "./types";

export type BiText = { en: string; hi: string };

export const langName: Record<Lang, BiText> = {
  hi: { en: "Hindi", hi: "हिंदी" },
  en: { en: "English", hi: "अंग्रेज़ी" },
};

export const statusLabel: Record<ChapterStatus, BiText> = {
  pending: { en: "Not started", hi: "शुरू नहीं" },
  translating: { en: "Translating", hi: "अनुवाद जारी" },
  review: { en: "Ready to review", hi: "समीक्षा के लिए तैयार" },
  approved: { en: "Approved", hi: "स्वीकृत" },
  failed: { en: "Failed", hi: "विफल" },
};

export const statusColor: Record<ChapterStatus, string> = {
  pending: "bg-slate-100 text-slate-700 ring-slate-200",
  translating: "bg-sky-50 text-sky-800 ring-sky-200",
  review: "bg-amber-50 text-amber-800 ring-amber-200",
  approved: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  failed: "bg-rose-50 text-rose-800 ring-rose-200",
};

export const paragraphTypeLabel: Record<string, BiText> = {
  heading: { en: "Heading", hi: "शीर्षक" },
  paragraph: { en: "Paragraph", hi: "अनुच्छेद" },
  list_item: { en: "List", hi: "सूची" },
  formula: { en: "Formula (kept as is)", hi: "सूत्र (अपरिवर्तित)" },
  table_text: { en: "Table text", hi: "तालिका पाठ" },
  table: { en: "Table", hi: "तालिका" },
};
