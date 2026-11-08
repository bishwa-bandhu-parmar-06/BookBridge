# BookBridge

Translate textbook PDFs between **Hindi and English**, chapter by chapter, and download the
translated book as a clean PDF.
*किताबों का हिंदी ⇄ अंग्रेज़ी अनुवाद, अध्याय दर अध्याय।*

1. Upload an original digital PDF and choose (or auto-detect) the direction.
2. BookBridge extracts the text, removes headers/footers, and splits it into chapters (editable).
3. Translate one chapter at a time. Progress is shown live.
4. Review side by side: flag paragraphs, re-translate only those (optionally with a note like
   "use simpler words"), or edit by hand. Keep technical terms consistent with the glossary.
5. Approve, download the chapter PDF, and move on. Download the full book (approved chapters) any time.
   Turn on **Keep translating the next chapters in the background** to have the following chapters
   translated one after another while you read — "Next chapter →" then opens instantly.
6. **Read & study** a translated chapter: A−/A+ text size, select words to highlight them (4 colours),
   ☆ mark points important, ✎ add your own notes, "Only my marks" for quick revision, show the Hindi
   original. **Preview / download the PDF with your highlights, notes and text size** included.
7. Files are deleted automatically after 2 hours, or right away with **Finish & delete my files**.

**Supported:** digital PDFs, **scanned PDFs and photos of pages** (JPG/PNG/WebP — read with Gemini OCR
page by page when a chapter is translated; one AI request per page), Hindi ⇄ English — including Hindi books
typeset in the legacy **APS-DV** fonts (APS-DV-Priyanka, -PriyankaRoman, -SURESH, -Yogita), common in
exam-prep books from Prayagraj publishers such as YCT. Their text is converted to Unicode automatically.
Question-bank layouts ("• question – answer") are kept together as one item.
**Not supported (yet):** other legacy Hindi fonts (Kruti Dev, Chanakya, DevLys…), text inside pictures or
diagrams, reproducing the original layout. There are no accounts and nothing is stored permanently.

---

## Contents

- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [1. Backend setup](#1-backend-setup)
- [2. WeasyPrint system libraries](#2-weasyprint-system-libraries-required-for-pdf-output)
- [3. Get a Gemini API key](#3-get-a-gemini-api-key)
- [4. Frontend setup](#4-frontend-setup)
- [Running without an API key (mock mode)](#running-without-an-api-key-mock-mode)
- [Testing](#testing)
- [Configuration reference](#configuration-reference)
- [API](#api)
- [How it works](#how-it-works)
- [Privacy and storage](#privacy-and-storage)
- [Adding another translation provider](#adding-another-translation-provider)
- [Troubleshooting](#troubleshooting)
- [Project structure](#project-structure)

---

## Architecture

```
Browser (Next.js, :3000) ──JSON/HTTP──▶ FastAPI (:8000)
                                         ├─ PyMuPDF: validate, extract, detect language/chapters
                                         ├─ Translator interface ─▶ Gemini API  (or Mock)
                                         ├─ BackgroundTasks + in-memory job registry
                                         ├─ Jinja2 HTML ─▶ WeasyPrint ─▶ PDF (bundled Noto fonts)
                                         └─ ./tmp_sessions/{uuid}/  (state.json, original.pdf, images, outputs)
```

No database, no Redis, no auth. Everything for a session lives in its own temporary folder.

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.11+ | backend |
| Node.js | 20.9+ | frontend (Next.js 16) |
| Pango (system library) | any recent | needed by WeasyPrint to create PDFs, see [step 2](#2-weasyprint-system-libraries-required-for-pdf-output) |
| Gemini API key | — | optional for local testing (use mock mode) |

---

## 1. Backend setup

```bash
cd backend
python -m venv .venv
```

Activate it: **Windows** `.venv\Scripts\activate` · **macOS/Linux** `source .venv/bin/activate`

```bash
pip install -r requirements.txt
cp .env.example .env        # Windows (cmd): copy .env.example .env
```

Edit `backend/.env` (at least `TRANSLATOR`, and the Gemini settings if you use Gemini), then run:

```bash
uvicorn app.main:app --reload --port 8000
```

API docs: <http://localhost:8000/docs> · health check: <http://localhost:8000/api/health>

### Try a PDF before anything else

The inspect tool shows exactly what the backend sees in a PDF — language, fonts (legacy ones flagged),
chapters and the first cleaned paragraphs — and why a PDF would be rejected:

```bash
python -m app.scripts.inspect_pdf path/to/book.pdf
python -m app.scripts.inspect_pdf book.pdf -n 40 -o report.txt   # more paragraphs, UTF-8 file output
```

---

## 2. WeasyPrint system libraries (required for PDF output)

WeasyPrint uses **Pango/HarfBuzz** to shape Devanagari correctly (conjuncts like क्ष, श्र, द्व and
matras). These are system libraries, not pip packages. Everything else works without them, but the
PDF download endpoints return `pdf_unavailable` (HTTP 503) until they are installed.

**Windows**

1. Install MSYS2: `winget install MSYS2.MSYS2` (or the installer from <https://www.msys2.org>), keeping the default folder `C:\msys64`.
2. Open the **MSYS2** shell and install Pango:
   ```bash
   pacman -S mingw-w64-ucrt-x86_64-pango
   ```
   (`mingw-w64-x86_64-pango` also works.) WeasyPrint automatically looks in `C:\msys64\ucrt64\bin` and
   `C:\msys64\mingw64\bin`. If you installed elsewhere, set `WEASYPRINT_DLL_DIRECTORIES` to the folder
   containing `libpango-1.0-0.dll`.

**macOS**

```bash
brew install pango
```

**Debian / Ubuntu**

```bash
sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0
```

**Fedora**: `sudo dnf install pango`

**Check it worked** (inside the backend virtualenv):

```bash
python -c "import weasyprint; print('WeasyPrint', weasyprint.__version__, 'OK')"
python -m pytest tests/test_pdf_writer.py -q     # includes the Devanagari conjunct test
```

Fonts (Noto Sans, Noto Sans Devanagari, Noto Sans Mono, Noto Sans Math) are bundled in
`backend/app/fonts/` under the SIL Open Font License — nothing to install.

---

## 3. Get a Gemini API key

1. Go to **Google AI Studio**: <https://aistudio.google.com/> and sign in with a Google account.
2. Click **Get API key** → **Create API key** (create or pick a Google Cloud project when asked).
3. Copy the key into `backend/.env`:
   ```
   TRANSLATOR=gemini
   GEMINI_API_KEY=your-key-here
   ```
4. Choose a model. List the models your key can use, then put one in `GEMINI_MODEL`:
   ```bash
   python -m app.scripts.check_gemini --list
   ```
   ```
   GEMINI_MODEL=<a model name from the list>
   ```
5. Check that everything works (sends two built-in sample sentences, not your book):
   ```bash
   python -m app.scripts.check_gemini
   ```

**Notes**

- Never commit `.env`. The key is only read on the server; the browser never sees it.
- Free-tier keys have low rate limits. BookBridge retries automatically (HTTP 429), and the review
  screen shows "Translation service is busy, retrying…". Large chapters simply take longer.
- Check Google's current terms for your tier regarding how API inputs may be used.

---

## 4. Frontend setup

```bash
cd frontend
cp .env.example .env.local     # NEXT_PUBLIC_API_URL=http://localhost:8000
npm install
npm run dev
```

Open <http://localhost:3000>. The backend must be running, and its `FRONTEND_ORIGIN` must match the
frontend's URL (default `http://localhost:3000`) for CORS.

Production build: `npm run build && npm start`.

---

## Running without an API key (mock mode)

Set in `backend/.env`:

```
TRANSLATOR=mock
MOCK_DELAY_SECONDS=1        # optional: slow it down to watch the progress bar
```

The mock translator returns `"[HI] " + text` (or `"[EN] "`), so the whole flow — upload, chapters,
translation jobs, review, glossary, approve, PDF download — works offline.

---

## Testing

```bash
cd backend && python -m pytest -q
```

Covers language detection, legacy-font detection (with real Kruti Dev gibberish samples), chapter
regexes (English, Hindi, Devanagari digits), the chunker, translation JSON validation and
retry/backoff/fallback (mocked translators), the glossary, session store and cleanup, rate limiting,
every API endpoint, and PDF generation with Devanagari conjunct shaping (skipped with a clear reason if
Pango is missing).

```bash
cd frontend && npx tsc --noEmit && npm run lint && npm run build
```

---

## Configuration reference

Backend (`backend/.env`):

| Variable | Default | Meaning |
|---|---|---|
| `TRANSLATOR` | `gemini` | `gemini` or `mock` |
| `GEMINI_API_KEY` | — | Google AI Studio key |
| `GEMINI_MODEL` | — | model name (no default; see `check_gemini --list`) |
| `MOCK_DELAY_SECONDS` | `0` | artificial delay per batch in mock mode |
| `TRANSLATION_BATCH_CHARS` | `4000` | target characters per translation batch |
| `TRANSLATION_MAX_ATTEMPTS` | `3` | attempts per batch before splitting it in half |
| `TRANSLATION_CONCURRENCY` | `3` | batches translated at the same time |
| `GEMINI_FALLBACK_MODELS` | — | comma-separated models tried when `GEMINI_MODEL` is busy (503) or rate-limited (429) |
| `GEMINI_THINKING_LEVEL` | `minimal` | model "thinking"; `minimal` is ~3× faster and enough for translation |
| `GEMINI_TIMEOUT_SECONDS` | `25` | give up on a hanging (overloaded) model after this long and try the next one |
| `SESSION_TTL_MINUTES` | `120` | auto-delete sessions after this long |
| `CLEANUP_INTERVAL_MINUTES` | `10` | how often the cleanup loop runs |
| `MAX_UPLOAD_MB` | `50` | max upload size |
| `MAX_PAGES` | `500` | max pages per PDF |
| `DEFAULT_PAGES_PER_CHUNK` | `10` | page ranges used when no chapters are detected |
| `SESSIONS_DIR` | `./tmp_sessions` | where session folders live |
| `UPLOAD_RATE_LIMIT_PER_HOUR` | `10` | uploads per IP per hour (`0` = off) |
| `TRUST_PROXY_HEADERS` | `false` | use `X-Forwarded-For` for the client IP — only behind your own reverse proxy |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | allowed CORS origin |
| `WEASYPRINT_DLL_DIRECTORIES` | — | Windows only, if Pango is not in `C:\msys64` |

Frontend (`frontend/.env.local`): `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`).

---

## API

All errors are JSON: `{"error": "<code>", "message": "<English>", "message_hi": "<Hindi>"}`.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/sessions` | upload (`file`, `source_lang`=`auto`\|`hi`\|`en`) → session summary + chapters |
| `GET` | `/api/sessions/{sid}` | summary, chapter statuses, time remaining |
| `PATCH` | `/api/sessions/{sid}` | change direction (before any translation) |
| `PUT` | `/api/sessions/{sid}/chapters` | replace chapter boundaries (before any translation) |
| `POST` | `/api/sessions/{sid}/chapters/{cid}/translate` | start a job → `{job_id}` |
| `GET` | `/api/jobs/{job_id}` | `{status, progress, message, error}` |
| `GET` | `/api/sessions/{sid}/chapters/{cid}` | paragraphs (original + translation) |
| `POST` | `/api/sessions/{sid}/chapters/{cid}/retranslate` | `{paragraph_ids[], note?}` → `{job_id}` |
| `PATCH` | `/api/sessions/{sid}/chapters/{cid}/paragraphs/{pid}` | `{translated?, flagged?}` |
| `POST` | `/api/sessions/{sid}/chapters/{cid}/approve` | approve (all paragraphs must be translated) |
| `GET`/`PUT` | `/api/sessions/{sid}/glossary` | view / replace term pairs |
| `GET` | `/api/sessions/{sid}/chapters/{cid}/pdf` | chapter PDF (review or approved) |
| `GET` | `/api/sessions/{sid}/book.pdf` | all approved chapters, with contents page |
| `DELETE` | `/api/sessions/{sid}` | delete everything now |
| `GET` | `/api/config` | public limits shown in the UI |

Rules: one translation job per session at a time (409 `job_running`); uploads are rate-limited per IP
(429 `rate_limited` with `Retry-After`).

---

## How it works

- **Validation** — magic bytes (not the extension), size, page count, password protection, and
  text-layer density (< 50 characters/page on average ⇒ "scanned PDF").
- **Language** — share of Devanagari characters among letters. **Legacy fonts** — known font names
  (Kruti Dev, Chanakya, DevLys, Walkman…) plus a gibberish heuristic (few common English words,
  odd in-word punctuation and capitals, few vowels).
- **Legacy → Unicode** — `services/legacy_font_converter.py` converts APS-DV text per font run: it tokenises
  glyph pieces (half-letters + stem, pre-base ि, reph, subscript ्र, nukta) into syllables and reorders them into
  Unicode order. Fonts without a converter (Kruti Dev, Chanakya…) are still rejected with a clear message;
  add a converter class there to support them.
- **Cleaning** — NFC normalisation, ि (i-matra) order fix, danda fix; running headers/footers and
  page numbers removed; English hyphenation joined; paragraphs merged across page breaks; types:
  heading, paragraph, list item, table text, formula (never translated).
- **Chapters** — PDF outline (TOC) → printed contents page ("title ........ 5-10", with the printed→PDF page
  offset read from page-number footers) → "Chapter 1 / Unit 2 / अध्याय ३ / पाठ 1" headings → fixed page ranges.
- **Book layout** — `services/layout.py` reads the PDF's vector drawings (≈2 s for 385 pages): grey bars →
  section headings, framed rectangles → boxed notes/diagrams, ruled lines → tables (rows rebuilt from text
  positions, side-by-side and stacked tables kept apart). Heading levels come from commonly used font sizes;
  "❑" bold lines are sub-headings; running headers/footers (e.g. "समग्र इतिहास 11 YCT") are dropped. The PDF
  keeps this structure: chapter banner, grey section bars, ❑ sub-headings, right-aligned bold answers,
  ruled tables and framed boxes.
- **Question banks** — "– answer" / "-answer" lines and their right-aligned wrapped lines are joined to the
  preceding "• question"; answers are printed in bold in the output PDF.
- **Translation** — paragraphs batched (~2,000 chars, never split) and sent as JSON with ids; the
  response must have the same ids, count and no empty texts. Invalid ⇒ retry with backoff (1 s, 2 s),
  then paragraph-by-paragraph; rate limits ⇒ longer waits using the provider's `retryDelay`.
  Each batch gets the chapter title, the previous 2 translated paragraphs, and the matching glossary terms.
  The prompt lives in `services/translator/prompts.py`.
- **Glossary** — the model returns key term pairs with each batch; the first translation of a term is
  kept for consistency, and your edits always win.
- **PDF** — Jinja2 HTML templates → WeasyPrint with bundled Noto fonts; images placed after their
  page's text; formulas in a centred monospace block; page numbers in the footer; book PDF has a cover
  and contents page.

## Privacy and storage

- Each upload gets a random UUID; its files live only in `tmp_sessions/{uuid}/`. IDs are validated
  strictly (no path traversal) and nothing lists sessions.
- Sessions expire after `SESSION_TTL_MINUTES` (default 2 h): expired sessions return 404 immediately and
  are deleted by a cleanup loop every 10 minutes. **Finish & delete my files** removes them at once.
- Logs record ids, counts and timings — never book text.
- When using Gemini, chapter text is sent to Google's API for translation.

## Adding another translation provider

1. Create `backend/app/services/translator/<provider>.py` with a class implementing
   `Translator.translate_batch(paragraphs, source_lang, target_lang, glossary, context) -> BatchResult`.
   Raise `RateLimitError`, `InvalidResponseError`, `TranslatorError` or `TranslatorConfigError` as appropriate;
   use `parse_batch_response()` if your provider returns the same JSON shape.
2. Add a branch for it in `backend/app/services/translator/__init__.py` (and its settings).

Retries, batching, glossary, context and jobs are provider-agnostic — nothing else changes.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "This looks like a scanned PDF" | The PDF has no text layer. OCR isn't supported yet. |
| "old non-Unicode font (Kruti Dev…)" | Run `inspect_pdf` to see the fonts (APS-DV fonts are converted automatically). For other legacy fonts, try a Unicode edition of the book. |
| PDF download says "not available on the server" / `OSError: cannot load library 'libpango…'` | Install Pango ([step 2](#2-weasyprint-system-libraries-required-for-pdf-output)); on Windows check `WEASYPRINT_DLL_DIRECTORIES`. |
| "translation service is not set up" (503) | Set `GEMINI_API_KEY` and `GEMINI_MODEL`, or `TRANSLATOR=mock`. Run `check_gemini`. |
| Translation keeps saying "busy, retrying" | Free-tier rate limit; it will continue. Smaller `TRANSLATION_BATCH_CHARS` doesn't reduce the request count — a paid tier does. |
| Browser shows "Cannot reach the BookBridge server" | Backend not running, wrong `NEXT_PUBLIC_API_URL`, or `FRONTEND_ORIGIN` doesn't match (CORS). |
| "Too many uploads from your network" | Per-IP limit; wait or raise `UPLOAD_RATE_LIMIT_PER_HOUR`. |
| A chapter shows "Failed" after a server restart | Jobs are in memory; open it and click **Continue translation** — finished paragraphs are kept. |

## Project structure

```
backend/
  app/
    main.py               FastAPI app, CORS, upload guard (rate limit/size), cleanup loop
    config.py             settings from .env
    routers/              sessions, chapters, jobs, glossary, export (PDF)
    services/
      pdf_reader.py       validation, extraction, legacy/scanned checks, images, chapters
      text_cleaner.py     normalisation, headers/footers, paragraphs, types, formulas
      language.py         language + legacy-font detection
      chunker.py          translation batches
      translator/         base interface, prompts, gemini, mock
      translation.py      retry/fallback + background job
      glossary.py, jobs.py, session_store.py, rate_limit.py, pdf_writer.py
    templates/            chapter.html, book.html (Jinja2)
    fonts/                Noto fonts (OFL)
    scripts/              inspect_pdf, check_gemini
  tests/
frontend/
  app/                    / (upload), /session/[id], /session/[id]/chapter/[chapterId]
  components/             UploadForm, SessionView, ChapterEditor, ReviewView, ParagraphRow, GlossaryPanel…
  lib/                    api.ts, types.ts, labels.ts
```

**Use responsibly:** upload only books you own, for personal study.
