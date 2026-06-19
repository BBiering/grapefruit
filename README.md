# 🍊 Grapefruit

High-growth potential stock picker. A personal tool for studying historical US equity 10x moves and surfacing early-stage candidates that look similar today.

Two modes:

1. **Historical study** — scans the active US equity universe on EODHD for the last 5 years of daily bars, finds tickers that moved ≥ 10x inside a configurable rolling window (2–52 weeks), and surfaces raw news headlines around the peak so you can study the catalyst.
2. **Current candidate scan** — runs a tunable momentum + volume heuristic against the latest cached bars to flag tickers showing early-stage signals today. Heuristic only. **Not financial advice.**

## ⚠️ Survivorship bias

EODHD's US symbol list is dominated by **currently active, tradable** tickers. Stocks that 10x-ed and then got delisted, acquired, or went bankrupt are largely absent. Treat every "hit" as filtered through survivorship — the universe is biased toward winners.

## Stack

- Backend: Python 3.11+, FastAPI, Postgres (Supabase), `httpx`, `psycopg`
- Frontend: React + Vite + TypeScript, TanStack Query, Recharts
- Data: EODHD (daily EOD bars, fundamentals, news), Perplexity `sonar` (catalyst summaries)
- Deploy: Vercel (frontend) + Render (FastAPI) + Supabase (Postgres)

## Setup

```bash
cp .env.example .env          # fill EODHD_API_KEY, PERPLEXITY_API_KEY, DATABASE_URL
pip install -e ".[dev]"
uvicorn grapefruit.main:app --reload --port 8000 --app-dir backend
```

`DATABASE_URL` is a Supabase Postgres connection string. Use the **Session pooler** URI from Supabase → Settings → Database → Connection string → Session pooler (port `5432`). Do **not** use "Direct connection" — it's IPv6-only and Render's free tier can't reach it. The backend creates all required tables idempotently at startup.

```bash
# Frontend (separate terminal)
cd frontend
npm install
npm run dev                   # http://localhost:5173, proxies /api -> :8000
```

Get an EODHD API key at https://eodhd.com/.

## Usage flow

1. Open http://localhost:5173.
2. **Refresh universe** — pulls the current active US equity asset list (~10k symbols).
3. **Refresh bars** — pulls the last 5 years of daily bars into `data/bars.duckdb`. EODHD allows ~1000 req/min, so the full universe completes in minutes.
4. **Run scan** — pick a window (weeks) and threshold (default 10x), then run. Watch progress.
5. **Hits** table — click a row to see the price chart and news headlines around the peak.
6. **Candidates** — tune momentum / volume thresholds against the current cache and review top-scoring tickers.

## Tests

```bash
pytest backend/tests
```

The detector has synthetic-series unit tests that don't touch the database. `test_storage.py` is skipped unless `DATABASE_URL` is set; point it at a throwaway Supabase project to run those (note: each test truncates every table).

## Deploy

Three pieces, all auto-deploying on `git push origin main`:

1. **Supabase** — create a free Postgres project. Copy the **Session pooler** URI (Settings → Database → Connection string → Session pooler, port `5432`) for `DATABASE_URL`. **Do not use "Direct connection"** — it's IPv6-only and Render free tier can't reach it. No schema setup needed; the backend creates tables on startup.
2. **Render** — import the included `render.yaml` Blueprint (Dashboard → Blueprints → New). Fill in the four `sync: false` env vars (`DATABASE_URL`, `EODHD_API_KEY`, `PERPLEXITY_API_KEY`, `FRONTEND_ORIGIN`). Render auto-deploys on every push to `main`.
3. **Vercel** — import the repo. `vercel.json` configures the build (`frontend/`) and SPA rewrites. Set one env var: `VITE_API_BASE_URL` = your Render service URL (e.g. `https://grapefruit-api.onrender.com`).

Then put the Vercel URL into Render's `FRONTEND_ORIGIN` so CORS allows the deployed frontend.

### Render free-tier caveat

Free Web Services sleep after 15 minutes of HTTP idleness; the first request after a sleep costs ~30s cold start. The ProgressBar polls `/api/jobs/{id}` every 1s while a job is in flight, which keeps the service warm for the duration. For long jobs (hours-long full-universe scans), keep the browser tab open.
