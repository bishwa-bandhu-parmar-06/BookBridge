import type { Metadata, Viewport } from "next";
import { Noto_Sans, Noto_Sans_Devanagari } from "next/font/google";
import Link from "next/link";

import "./globals.css";

const notoSans = Noto_Sans({ variable: "--font-noto-sans", subsets: ["latin"], display: "swap" });
const notoDevanagari = Noto_Sans_Devanagari({
  variable: "--font-noto-devanagari",
  subsets: ["devanagari"],
  weight: ["400", "500", "700"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "BookBridge — Hindi ⇄ English textbook translation",
  description: "Translate textbook PDFs between Hindi and English, chapter by chapter. किताबों का हिंदी ⇄ अंग्रेज़ी अनुवाद।",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#3730a3" };

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${notoSans.variable} ${notoDevanagari.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col font-sans">
        <header className="border-b border-slate-200 bg-white">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
            <Link href="/" className="flex items-center gap-2 font-semibold text-indigo-800">
              <span aria-hidden className="grid size-8 place-items-center rounded-lg bg-indigo-700 text-sm text-white">
                अ
              </span>
              BookBridge
            </Link>
            <span className="text-xs text-slate-500">
              Hindi ⇄ English · <span lang="hi">हिंदी ⇄ अंग्रेज़ी</span>
            </span>
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:py-10">{children}</main>
        <footer className="border-t border-slate-200 py-4 text-center text-xs text-slate-500">
          For personal study only · <span lang="hi">केवल व्यक्तिगत अध्ययन के लिए</span>
        </footer>
      </body>
    </html>
  );
}
