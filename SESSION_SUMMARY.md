# Grapefruit — Session Summary

> Generated from the Aug–Sep 2026 working session. Covers the biotech refocus,
> infrastructure consolidation, data-quality plumbing, and product features.

## 1. Strategic refocus: biotech-only universe, 6 EU markets + US

- **Universe** = Euronext PA (France), ST (Sweden), LSE (UK), SW (Switzerland), CO
  (Denmark), XETRA (Germany), plus **US**.
- **Price ceiling**: ~$200-equivalent per market in native currency
  (`MAX_NATIVE_PRICE` map in `refresh_universe.py`):
  US 200 / EUR 170 (PA, XETRA) / GBP 160 (LSE) / CHF 160 (SW) / SEK 1900 / DKK 1280.
- **Market-cap floor**: `MIN_MARKET_CAP_USD = 300e6` — excludes nano (<$50M) and
  micro ($50M–$300M) caps.
- **Strict biotech-only filter**: only `industry == "Biotechnology"` exactly is kept.
  Classified non-biotech is deleted deterministically at fetch time in
  `refresh_sectors`; unresolved (NULL-industry) names get a grace window via
  `sector_attempted_at` so legit-but-late-classified names (e.g. IVA.PA) survive.

## 2. Pipeline architecture

- **8 Cloud Run jobs** (all share one image, `job_name` as arg):
  `refresh_universe, refresh_bars, refresh_sectors, detect_step_changes,
  enrich_catalysts, scan_catalysts, evaluate_predictions, weekly`.
- **Weekly order**: universe → sectors (classify + prune) → bars (biotech-only) →
  step changes → enrich → scan → evaluate.
- **Timeouts**: weekly 6h, scan_catalysts 3h, refresh_sectors 1.5h (6000/run).
- `refresh_sectors`: `_MAX_PER_RUN = 6000`; stamps `sector_attempted_at` per fetch;
  `symbols_needing_sector` keys on industry, oldest-attempt first.
- Consumers (`scan_catalysts`, `refresh_bars`, `detect_step_changes`) gate on
  `symbols_biotech()` so no credits/API calls are wasted on unclassified rows.

## 3. Perplexity integration (Search API + Agent API)

- `catalyst.py` migrated from legacy Sonar chat-completions to the **new two-step
  flow**: `web_search()` (Search API, per-request) + Agent API extraction
  (`_agent_json`, preset `fast`/`low`).
- `explain_move` uses Agent API `low` + `finance_search`/`web_search`/`fetch_url`.
- **Catalyst horizon widened 3 → 6 months** so scheduled readouts a few quarters
  out (e.g. IVA.PA NATiV3 Phase 3, Q4 2026) are detected.
- Cost model: ~$13–15 per full scan of ~450 biotech names (Search + extract per co).

## 4. Data completeness fixes

- `upsert_assets`/`upsert_asset` use `COALESCE(...)` so refresh_universe never wipes
  known sector/industry.
- `cleanup_non_biotech` replaced by per-symbol deterministic prune in
  `refresh_sectors`; no time-based sweep remains.
- FK cascades (`step_change_history`, `forward_catalysts` → `assets`) mean deleting
  an asset cleans its derived rows automatically; `bars` needs manual pruning
  (no FK).

## 5. Frontend (Vercel SPA)

- **Company cards**: full-width, one per row, always-expanded timeline
  (collapsible per event), past (yellow) + predicted (blue) markers on the 3y
  chart, hover cursor + tooltip, Perplexity chat per company (serverless
  `/api/chat` proxy, markdown renderer, **persistent per-symbol history**).
- **Filters**: search by name/ticker, country (with flags), catalyst type
  (all/predicted/past/both), **watchlist-only** toggle; sort by predicted impact
  (desc) or past multiplier.
- **Watchlist**: `watchlist` table + star toggle per card.
- **Dates**: `displayCatalystDate()` humanizes quarters (`Q4 2026`), half-years
  (`H1 2027`), ISO dates; only empty → "Date unknown".
- Mobile: fluid chart (`ResponsiveContainer`), info-before-chart stacking, cards
  grow to content (max 70vh), no fixed-height clipping.

## 6. New tables (supabase/migrations/0014_watchlist_chat.sql)

- `watchlist` (symbol PK FK→assets, added_at) — anon RLS read/insert/delete.
- `chat_messages` (id, symbol, role, content, created_at) — anon RLS
  read/insert/delete; indexed on (symbol, created_at).

## 7. Ops notes

- GCP project: `grapefruit-500208` @ `europe-west4`; jobs owned by
  `grapefruit-deployer@grapefruit-500208.iam.gserviceaccount.com` (created via
  Pulumi + GitHub Actions). Schedulers: `grapefruit-weekly` (Mon 09:00 UTC),
  `grapefruit-bars-daily` (22:00 UTC).
- Auth gotcha for local `gcloud`: must be `benjamin.biering@gmail.com` +
  `grapefruit-500208`, not the personal `interhuman-ai-prod` default.
- `.DS_Store` gitignored.

## 8. Known caveats

- Anon-writable watchlist/chat (no auth on the tool) — shared across users.
- `scan_catalysts` only stores rows when `detected=true`; "no catalyst this
  window" companies simply have no row.
- Source URLs from Perplexity can occasionally be null (extraction validation
  rejects non-matching URLs).