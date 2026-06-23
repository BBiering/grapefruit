# 🍊 Grapefruit

Steep-rise stock detector. Scans the active US universe weekly for tickers that
**rose at least 5x in under a week and held the new level**, then asks Perplexity
why it happened and whether it was foreseeable from public information beforehand.
A second view tracks small-cap candidates with upcoming earnings as potential
future winners. **Not financial advice.**

## ⚠️ Survivorship bias

EODHD's US symbol list is dominated by **currently active, tradable** tickers.
Stocks that 10x-ed and then got delisted, acquired, or went bankrupt are largely
absent. Treat every "winner" as filtered through survivorship.

## Architecture

```
┌──────────────────┐                  ┌───────────────────────┐
│  Vercel (SPA)    │  Supabase JS     │  Supabase Postgres    │
│  one-pager       │  anon key + RLS  │  (single source of    │
│  Past / Future   │ ───────────────► │   truth)              │
└──────────────────┘                  └──────────▲────────────┘
                                                 │
                                                 │ psycopg
                                       ┌─────────┴─────────┐
                                       │ GCP Cloud Run Job │
                                       │ scheduled weekly  │
                                       │ + daily bars      │
                                       └───────────────────┘
                              EODHD · Perplexity APIs
```

- **Frontend** (`frontend/`) — React/Vite SPA hosted on Vercel. Reads Supabase
  directly via `@supabase/supabase-js` with the anon key + Row Level Security.
- **Backend** (`backend/grapefruit/`) — Python pipelines containerized and run as
  GCP Cloud Run Jobs. Each pipeline reads/writes Supabase. No always-on web
  server.
- **Database** — Supabase Postgres. Schema in `supabase/migrations/0001_redesign.sql`.

## Local dev

```bash
cp .env.example .env          # fill EODHD_API_KEY, PERPLEXITY_API_KEY, DATABASE_URL
pip install -e ".[dev]"

# Run a single pipeline locally against your Supabase project:
python -m grapefruit.pipelines refresh_universe
python -m grapefruit.pipelines refresh_fundamentals
python -m grapefruit.pipelines refresh_bars
python -m grapefruit.pipelines detect_winners
python -m grapefruit.pipelines enrich_catalysts
python -m grapefruit.pipelines refresh_watchlist
python -m grapefruit.pipelines refresh_upcoming_events

# Or run the full pipeline in order:
python -m grapefruit.pipelines weekly
```

```bash
cd frontend && npm install && npm run dev
# http://localhost:5173, reads Supabase directly via VITE_SUPABASE_URL +
# VITE_SUPABASE_PUBLISHABLE_KEY env vars (set them in frontend/.env.local)
```

## Tests

```bash
pytest backend/tests
```

The detector tests are pure-numpy and don't touch the database.

## Deploy

### Supabase (one-time)

1. Create a Supabase project.
2. SQL editor → paste and run `supabase/migrations/0001_redesign.sql`.
3. Copy the **Session pooler** URI for `DATABASE_URL` and the project URL +
   anon key for the frontend.

### Vercel (one-time)

1. Import the repo. `vercel.json` builds `frontend/` and serves the SPA.
2. Set env vars:
   - `VITE_SUPABASE_URL`
   - `VITE_SUPABASE_PUBLISHABLE_KEY` (the **publishable** key,
     `sb_publishable_…`; the secret key would be inlined into the public
     bundle and bypass RLS)
3. Push to `main` to redeploy.

### GCP infra (one-time)

Provisioned by Pulumi — see [`infra/README.md`](infra/README.md) for the
~10-minute bootstrap (state bucket, `pulumi stack init prod`, set six config
values, `pulumi up`).

After that, two GitHub Actions workflows do all the rolling on `main`:

- `.github/workflows/pulumi-up.yml` runs when `infra/**` changes (structure).
- `.github/workflows/deploy-jobs.yml` runs when `backend/**` changes (image
  build + `gcloud run jobs update --image=...`).

GitHub Actions secrets required:

- `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_SA_KEY`, `GCP_ARTIFACT_REPO` (used by
  both workflows)
- `PULUMI_STATE_BUCKET` (GCS bucket name, no `gs://` prefix)
- `PULUMI_CONFIG_PASSPHRASE` (any long random string; encrypts secrets in
  Pulumi state)
- `EODHD_API_KEY`, `PERPLEXITY_API_KEY`, `DATABASE_URL` — `pulumi-up.yml`
  reads these and runs `pulumi config set --secret` for each on every run.
  Pulumi then writes them to GCP Secret Manager and wires them into each
  Cloud Run Job's env.

No `pulumi config set` ever needs to run locally — every config value is
sourced from a GitHub secret on each workflow run.

### Schedule

- **Monday 09:00 UTC**: full pipeline via the `weekly` job (refresh universe →
  fundamentals → bars → detect winners → enrich catalysts → refresh watchlist
  → refresh upcoming events).
- **Daily 22:00 UTC**: `refresh_bars` (incremental) so the dashboard sees today's
  close by tomorrow morning.
