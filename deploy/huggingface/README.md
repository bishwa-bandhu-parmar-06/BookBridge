---
title: BookBridge API
emoji: 📚
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
short_description: API for BookBridge, a Hindi ⇄ English textbook translator
---

# BookBridge API

The backend for BookBridge. The website runs on Vercel and calls this Space.

Set these in **Settings → Variables and secrets**:

| Name | Type | Value |
| --- | --- | --- |
| `GEMINI_API_KEY` | Secret | your Gemini API key |
| `FRONTEND_ORIGIN` | Variable | your Vercel address, e.g. `https://bookbridge.vercel.app` |
| `GEMINI_MODEL` | Variable | e.g. `gemini-3.1-flash-lite` |
| `GEMINI_FALLBACK_MODELS` | Variable | e.g. `gemini-3.5-flash-lite,gemini-flash-lite-latest` |

Check it works: open `https://<your-space>.hf.space/api/health`.
