# Deploying BookBridge (free)

BookBridge has two parts:

| Part | Folder | Where it goes | Why |
| --- | --- | --- | --- |
| Website (Next.js) | `frontend/` | **Vercel** (free) | Made for Next.js |
| API (FastAPI) | `backend/` | **Hugging Face Spaces** (free), or Render (free) | Needs things Vercel functions don't have (see the end) |

You set up the API first (to get its address), then the website, then tell the API the
website's address.

---

## Part 1 – The API on Hugging Face Spaces (recommended)

Free "CPU basic" Space: 2 CPUs and 16 GB of memory. It goes to sleep only after
2 days without visitors.

1. Make a free account at <https://huggingface.co/join>.
2. Go to <https://huggingface.co/new-space>:
   - **Space name:** `bookbridge-api`
   - **Space SDK:** **Docker** → **Blank**
   - **Hardware:** CPU basic (free)
   - Click **Create Space**.
3. On the Space page, open **Files** → **+ Contribute** → **Upload files**. Upload these
   two files from this repo's `deploy/huggingface/` folder, and commit:
   - `Dockerfile`
   - `README.md` (replace the one the Space made)
4. Open **Settings** → **Variables and secrets**:
   - **New secret:** `GEMINI_API_KEY` = your Gemini key
   - **New variable:** `FRONTEND_ORIGIN` = `http://localhost:3000` (for now; you change it in Part 3)
   - **New variable:** `GEMINI_MODEL` = `gemini-3.1-flash-lite`
   - **New variable:** `GEMINI_FALLBACK_MODELS` = `gemini-3.5-flash-lite,gemini-flash-lite-latest,gemini-3-flash-preview,gemini-3.8-flash`
5. The Space builds by itself, which takes about 5–10 minutes. Watch the **Logs** tab. When it
   says **Running**, open:

   `https://<your-hf-username>-bookbridge-api.hf.space/api/health`

   If you see `{"status":"ok"}`, the API works. **Copy this address without
   `/api/health`.** That is your API address.

**Updating later:** after you push new code to GitHub, open the Space's **Settings** and
click **Factory rebuild**. The Space downloads the newest code from GitHub.

### Option B – The API on Render instead

Render is easier to connect to GitHub, but its free plan has only 512 MB of memory, and it
sleeps after 15 minutes without visitors. When it sleeps, open books are lost and the
next visit waits about a minute.

1. Make a free account at <https://render.com> (sign in with GitHub).
2. **New +** → **Blueprint** → pick the `BookBridge` repository. Render reads `render.yaml`.
3. It asks for:
   - `GEMINI_API_KEY`: your key
   - `FRONTEND_ORIGIN`: `http://localhost:3000` for now
4. Click **Apply**, then wait for the build (about 5–10 minutes).
5. Open `https://bookbridge-api.onrender.com/api/health` (Render shows the exact address).
   That address without `/api/health` is your API address.

Render redeploys by itself every time you push to GitHub.

---

## Part 2 – The website on Vercel

1. Make a free account at <https://vercel.com/signup> (sign in with GitHub).
2. **Add New…** → **Project** → **Import** the `BookBridge` repository.
3. On the setup screen:
   - **Root Directory:** click **Edit** and choose **`frontend`**. This step matters.
   - **Framework Preset:** Next.js (Vercel picks it automatically).
   - **Environment Variables:** add
     `NEXT_PUBLIC_API_URL` = your API address from Part 1, e.g.
     `https://yourname-bookbridge-api.hf.space` (no `/` at the end).
4. Click **Deploy**. After 1–2 minutes you get an address like
   `https://bookbridge-abc123.vercel.app`. **Copy it.**

If you forget `NEXT_PUBLIC_API_URL`, the build stops with a message telling you to add it.
If you add or change it later, redeploy: **Deployments** → ⋯ → **Redeploy**.

---

## Part 3 – Let the API accept the website

The API only answers the website addresses you allow (CORS).

- **Hugging Face:** Space → **Settings** → **Variables and secrets** → edit `FRONTEND_ORIGIN`
  to your Vercel address, e.g. `https://bookbridge-abc123.vercel.app`. The Space restarts.
- **Render:** service → **Environment** → edit `FRONTEND_ORIGIN` → **Save** (it redeploys).

Notes:
- Write the exact address, with `https://` and with no `/` at the end.
- To allow several addresses, separate them with commas:
  `https://bookbridge.vercel.app,http://localhost:3000`
- Optional, for Vercel preview links: add `FRONTEND_ORIGIN_REGEX` =
  `https://bookbridge-[a-z0-9-]+\.vercel\.app`

Then open your Vercel address and upload a book. 🎉

---

## If something goes wrong

| What you see | What to do |
| --- | --- |
| "Waking up the server…" for a minute | Normal on free plans after a quiet period. Wait. |
| "Cannot reach the BookBridge server" | Check `NEXT_PUBLIC_API_URL` on Vercel. Check that `FRONTEND_ORIGIN` on the API is exactly your Vercel address. Redeploy Vercel after any change. |
| The `/api/health` page doesn't open | Look at the build **Logs** on Hugging Face or Render. |
| "The translation service is not set up on the server" | `GEMINI_API_KEY` is missing or wrong on the API. |
| Big books fail on Render | Out of memory (512 MB). Use Hugging Face, or upload smaller parts. |

## Good to know

- **Your API key stays on the API server only** (Hugging Face or Render). It is never in Vercel
  or in GitHub. Everyone who uses your site shares your Gemini free quota.
- **Uploaded books live only on the API server** and are deleted after 2 hours, or when the
  server restarts or sleeps.
- **Keep one copy of the API running** (one worker, one instance). Translation progress is
  kept in that server's memory.

## Why not put the API on Vercel too?

Vercel's Python functions don't fit this API:
- they accept uploads of only about 4.5 MB, and books are bigger;
- they don't have the Pango libraries WeasyPrint needs to make PDFs;
- each request has a time limit, and translating a chapter runs for minutes in the background;
- they keep no files or memory between requests, but sessions and job progress need both.

The `backend/Dockerfile` also works on other free or cheap Docker hosts (Koyeb, Railway,
Google Cloud Run). Use port `$PORT` (default 7860) and set the same environment variables.
