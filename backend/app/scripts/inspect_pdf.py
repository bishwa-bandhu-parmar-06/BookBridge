"""Inspect a PDF the way the upload endpoint will see it.

Usage (from backend/):
    python -m app.scripts.inspect_pdf path/to/book.pdf
    python -m app.scripts.inspect_pdf book.pdf -n 40          # show 40 paragraphs
    python -m app.scripts.inspect_pdf book.pdf -o report.txt  # write UTF-8 report to a file

Prints the detected language, fonts (legacy ones flagged), legacy-text heuristics,
chapters, and the first N cleaned paragraphs. Even if the PDF would be rejected,
the diagnostics are still printed so you can see why.
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

from app.config import get_settings
from app.errors import AppError
from app.services import pdf_reader
from app.services.language import detect_language, legacy_text_stats, private_use_ratio
from app.services.text_cleaner import build_paragraphs


def _short(text: str, n: int = 300) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= n else text[: n - 1] + "…"


def inspect(path: Path, n_paragraphs: int, out: io.TextIOBase) -> int:
    s = get_settings()
    p = lambda *a: print(*a, file=out)  # noqa: E731

    data = path.read_bytes()
    p(f"File:        {path}  ({len(data) / 1_048_576:.1f} MB)")

    try:
        pdf_reader.check_pdf_bytes(data, s.max_upload_bytes, s.max_upload_mb)
        doc = pdf_reader.open_pdf(data)
    except AppError as e:
        p(f"REJECTED [{e.code}]: {e.message}")
        return 1

    rejected: AppError | None = None
    try:
        p(f"Pages:       {doc.page_count}" + ("  (over MAX_PAGES!)" if doc.page_count > s.max_pages else ""))
        p(f"Encrypted:   {bool(doc.is_encrypted)} (needs password: {bool(doc.needs_pass)})")
        p(f"TOC entries: {len(doc.get_toc())}")

        book = pdf_reader.extract_book(doc)
        sample = book.sample_text()
        guess = detect_language(sample)
        lt = legacy_text_stats(sample)

        p("")
        p("== Language ==")
        p(f"Detected:            {guess.lang}  (Devanagari share of letters: {guess.devanagari_ratio:.2%}, letters: {guess.letters})")
        p(f"Avg chars per page:  {book.total_chars / max(book.page_count, 1):.0f}  (scanned if < {s.min_chars_per_page})")
        p(f"Private-use chars:   {private_use_ratio(sample):.2%}")
        p(
            f"Legacy-text check:   legacy={lt.is_legacy}  latin_tokens={lt.latin_tokens}  "
            f"common_en_words={lt.common_word_ratio:.2%}  weird_tokens={lt.weird_token_ratio:.2%}  "
            f"vowels={lt.vowel_ratio:.2%}"
        )

        p("")
        p("== Fonts (by characters) ==")
        from app.services.language import is_legacy_font_name

        from app.services.legacy_font_converter import get_converter

        for key, chars in book.font_chars.most_common(20):
            conv = get_converter(book.font_display[key])
            if conv is not None:
                flag = f"  <-- legacy, converted ({conv.name})"
            elif is_legacy_font_name(key):
                flag = "  <-- LEGACY (not supported)"
            else:
                flag = ""
            p(f"  {chars:>8}  {book.font_display[key]}{flag}")

        try:
            analysis = pdf_reader.analyze_book(book, s.min_chars_per_page)
            for w in analysis.warnings:
                p(f"WARNING: {w}")
        except AppError as e:
            rejected = e

        paragraphs = build_paragraphs(book.pages)
        chapters = pdf_reader.detect_chapters(doc, paragraphs, s.default_pages_per_chunk, book.pages)

        p("")
        p(f"== Chapters (method: {chapters[0].method}) ==")
        for c in chapters:
            p(f"  [{c.id:>3}] pages {c.start_page:>4}–{c.end_page:<4} {_short(c.title, 100)}")

        p("")
        counts: dict[str, int] = {}
        for para in paragraphs:
            counts[para.type] = counts.get(para.type, 0) + 1
        p(f"== Paragraphs: {len(paragraphs)} total  {counts} ==")
        for para in paragraphs[:n_paragraphs]:
            lvl = f"h{para.level}" if para.level else ""
            p(f"  {para.id} [{para.type}{(' ' + lvl) if lvl else ''}] size={para.size:.1f}")
            p(f"      {_short(para.text)}")
    finally:
        doc.close()

    p("")
    if rejected:
        p(f"RESULT: REJECTED [{rejected.code}]: {rejected.message}")
        return 1
    p("RESULT: OK — this PDF would be accepted.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Inspect a PDF for BookBridge.")
    ap.add_argument("pdf", type=Path)
    ap.add_argument("-n", "--paragraphs", type=int, default=20, help="number of paragraphs to print (default 20)")
    ap.add_argument("-o", "--out", type=Path, help="write the report to this UTF-8 file instead of the console")
    args = ap.parse_args(argv)

    if not args.pdf.is_file():
        print(f"File not found: {args.pdf}", file=sys.stderr)
        return 2

    if args.out:
        with args.out.open("w", encoding="utf-8") as f:
            code = inspect(args.pdf, args.paragraphs, f)
        print(f"Report written to {args.out}")
        return code

    # Make Devanagari printable on Windows consoles.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return inspect(args.pdf, args.paragraphs, sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
