# BookBridge frontend

Next.js (App Router) + TypeScript + Tailwind CSS. See the [main README](../README.md) for full setup.

```bash
cp .env.example .env.local   # NEXT_PUBLIC_API_URL=http://localhost:8000
npm install
npm run dev                  # http://localhost:3000
```

- `app/` — routes: `/` (upload), `/session/[id]` (chapters), `/session/[id]/chapter/[chapterId]` (review)
- `components/` — screens and UI pieces (all client components)
- `lib/api.ts` — typed API client; `lib/types.ts` mirrors `backend/app/schemas.py`
