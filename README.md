# 🍊 Grapefruit

High-growth potential stock picker. A personal tool for studying historical US equity 10x moves and surfacing early-stage candidates that look similar today.

Two modes:

1. **Historical study** — scans the active US equity universe on EODHD for the last 5 years of daily bars, finds tickers that moved ≥ 10x inside a configurable rolling window (2–52 weeks), and surfaces raw news headlines around the peak so you can study the catalyst.
2. **Current candidate scan** — runs a tunable momentum + volume heuristic against the latest cached bars to flag tickers showing early-stage signals today. Heuristic only. **Not financial advice.**

## ⚠️ Survivorship bias

EODHD's US symbol list is dominated by **currently active, tradable** tickers. Stocks that 10x-ed and then got delisted, acquired, or went bankrupt are largely absent. Treat every "hit" as filtered through survivorship — the universe is biased toward winners.

## Stack

- Backend: Python 3.11+, FastAPI, DuckDB, `httpx`
- Frontend: React + Vite + TypeScript, TanStack Query, Recharts
- Data: EODHD (daily EOD bars, fundamentals, news)

## Setup

```bash
cp .env.example .env          # fill EODHD_API_KEY
pip install -e ".[dev]"
uvicorn grapefruit.main:app --reload --port 8000 --app-dir backend
```

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

The detector has synthetic-series unit tests covering the sliding-window invariants.
