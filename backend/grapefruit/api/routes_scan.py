from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from grapefruit import bars as bars_mod
from grapefruit import metadata, storage
from grapefruit.config import settings
from grapefruit.detector import detect_hits
from grapefruit.jobs import JobState, list_jobs, new_job, run_async
from grapefruit.universe import fetch_active_universe, load_universe


ENRICH_TOP_N = 200
_AUTO_ENRICH_JOB_KIND = "assets_enrich_auto"

router = APIRouter()


class RefreshUniverseResponse(BaseModel):
    count: int
    refreshed_at: str


class BarsRefreshBody(BaseModel):
    symbols: list[str] | None = None
    years: int = 5


class ScanBody(BaseModel):
    window_weeks: int = Field(ge=2, le=52)
    threshold: float = 10.0
    symbols: list[str] | None = None
    max_price_usd: float | None = Field(default=None, gt=0)
    max_market_cap_usd: float | None = Field(default=None, gt=0)


@router.post("/api/universe/refresh", response_model=RefreshUniverseResponse)
def refresh_universe() -> RefreshUniverseResponse:
    payload = fetch_active_universe()
    return RefreshUniverseResponse(count=payload["count"], refreshed_at=payload["refreshed_at"])


@router.get("/api/universe")
def get_universe() -> dict:
    payload = load_universe()
    if not payload:
        return {"symbols": [], "count": 0, "refreshed_at": None}
    return payload


@router.post("/api/bars/refresh")
def refresh_bars(body: BarsRefreshBody) -> dict:
    storage.init_db()
    symbols = body.symbols
    if not symbols:
        uni = load_universe()
        if not uni:
            raise HTTPException(400, "Universe not loaded. Call /api/universe/refresh first.")
        symbols = uni["symbols"]
    years = body.years
    job = new_job("bars_refresh")
    job.total = len(symbols)

    def task(j: JobState):
        def progress(done: int, total: int, msg: str) -> None:
            j.processed = done
            j.total = total
            j.message = msg

        df = bars_mod.fetch_bars(symbols, years=years, progress=progress)
        n = storage.upsert_bars(df)
        return {"rows_upserted": n, "symbols": len(symbols)}

    run_async(job, task)
    return {"job_id": job.job_id}


@router.post("/api/scan/historical")
def scan_historical(body: ScanBody) -> dict:
    storage.init_db()
    window_days = body.window_weeks * 5
    threshold = body.threshold
    symbols = body.symbols or storage.symbols_with_bars()
    if not symbols:
        raise HTTPException(400, "No bars cached. Call /api/bars/refresh first.")
    # Optional small-cap filters: intersect with the requested set.
    if body.max_price_usd is not None:
        allowed = set(storage.symbols_with_last_close_below(body.max_price_usd))
        symbols = [s for s in symbols if s in allowed]
    if body.max_market_cap_usd is not None:
        allowed = set(storage.symbols_with_market_cap_below(body.max_market_cap_usd))
        symbols = [s for s in symbols if s in allowed]
    if not symbols:
        raise HTTPException(
            400,
            "No symbols match the requested filters. Loosen max_price_usd / max_market_cap_usd, "
            "or run /api/assets/refresh_market_caps to populate cap data.",
        )

    job = new_job("scan_historical")
    job.total = len(symbols)

    def task(j: JobState):
        all_hits: list[dict] = []
        for i, sym in enumerate(symbols, start=1):
            df = storage.load_symbol(sym)
            if len(df) < window_days:
                j.processed = i
                continue
            closes = df["close"].to_numpy(dtype=float)
            dates_arr = df["ts"].to_numpy()
            hits = detect_hits(sym, closes, dates_arr, window_days, threshold)
            for h in hits:
                all_hits.append(
                    {
                        "symbol": h.symbol,
                        "start_ts": h.start_ts,
                        "end_ts": h.end_ts,
                        "trough_price": h.trough_price,
                        "peak_price": h.peak_price,
                        "multiplier": h.multiplier,
                    }
                )
            j.processed = i
            j.message = f"scanned {sym} ({i}/{len(symbols)})"
        storage.save_hits(all_hits, window_days, threshold)
        # Lazily enrich metadata for the strongest hits so the UI table isn't empty.
        top = sorted(all_hits, key=lambda h: h["multiplier"], reverse=True)[:ENRICH_TOP_N]
        for idx, h in enumerate(top, start=1):
            try:
                metadata.get_or_fetch(h["symbol"])
            except Exception:  # noqa: BLE001
                pass
            j.message = f"enriching {h['symbol']} ({idx}/{len(top)})"
        return {"hits": len(all_hits), "window_days": window_days, "threshold": threshold}

    run_async(job, task)
    return {"job_id": job.job_id}


@router.post("/api/assets/enrich")
def enrich_assets(limit: int = 500) -> dict:
    """Backfill name/industry/exchange for hit symbols that don't have them yet."""
    pending = storage.hit_symbols_missing_metadata()[:limit]
    if not pending:
        return {"pending": 0, "enriched": 0}
    job = new_job("assets_enrich")
    job.total = len(pending)

    def task(j: JobState):
        enriched = 0
        for idx, sym in enumerate(pending, start=1):
            row = metadata.get_or_fetch(sym, refresh=True)
            if row.get("name"):
                enriched += 1
            j.processed = idx
            j.message = f"{sym} ({idx}/{len(pending)})"
        return {"pending": len(pending), "enriched": enriched}

    run_async(job, task)
    return {"job_id": job.job_id, "pending": len(pending)}


@router.post("/api/assets/refresh_market_caps")
def refresh_market_caps(limit: int | None = None) -> dict:
    """Bulk-fetch Finnhub metadata (including market cap) for the entire universe.

    Slow: free-tier Finnhub is 60 req/min, so 12k symbols takes ~3.5h. Runs as a
    background job. Pass `limit` to cap the work for a smaller experiment.
    """
    if not settings.finnhub_api_key:
        raise HTTPException(400, "FINNHUB_API_KEY not set. Add it to .env and restart.")
    uni = load_universe()
    if not uni:
        raise HTTPException(400, "Universe not loaded. Call /api/universe/refresh first.")
    symbols = uni["symbols"][:limit] if limit else uni["symbols"]
    job = new_job("market_caps_refresh")
    job.total = len(symbols)

    def task(j: JobState):
        filled = 0
        for idx, sym in enumerate(symbols, start=1):
            row = metadata.get_or_fetch(sym, refresh=True)
            if row.get("market_cap_usd"):
                filled += 1
            j.processed = idx
            j.message = f"{sym} ({idx}/{len(symbols)}, {filled} with cap)"
        return {"symbols": len(symbols), "with_market_cap": filled}

    run_async(job, task)
    return {"job_id": job.job_id, "symbols": len(symbols)}


def _trigger_auto_enrich() -> None:
    """If hits have missing metadata and no auto-enrich job is already running, kick one off."""
    if not settings.finnhub_api_key:
        return
    running = [
        j for j in list_jobs()
        if j["kind"] == _AUTO_ENRICH_JOB_KIND and j["status"] in ("pending", "running")
    ]
    if running:
        return
    pending = storage.hit_symbols_missing_metadata()
    if not pending:
        return
    job = new_job(_AUTO_ENRICH_JOB_KIND)
    job.total = len(pending)

    def task(j: JobState):
        enriched = 0
        for idx, sym in enumerate(pending, start=1):
            row = metadata.get_or_fetch(sym, refresh=True)
            if row.get("name"):
                enriched += 1
            j.processed = idx
            j.message = f"{sym} ({idx}/{len(pending)})"
        return {"pending": len(pending), "enriched": enriched}

    run_async(job, task)


@router.get("/api/hits")
def get_hits(
    window_weeks: int | None = None,
    min_multiplier: float | None = None,
    max_days_since_peak: int | None = None,
    min_peak_retention: float | None = None,
    min_breakout_ratio: float | None = None,
    industry: str | None = None,
) -> list[dict]:
    rows = storage.query_hits(
        window_weeks=window_weeks,
        min_multiplier=min_multiplier,
        max_days_since_peak=max_days_since_peak,
        min_peak_retention=min_peak_retention,
        min_breakout_ratio=min_breakout_ratio,
        industry=industry,
    )
    _trigger_auto_enrich()
    return [
        {
            **r,
            "start_ts": _iso(r["start_ts"]),
            "end_ts": _iso(r["end_ts"]),
            "scanned_at": _iso(r["scanned_at"]),
            "last_ts": _iso(r.get("last_ts")),
        }
        for r in rows
    ]


@router.get("/api/status")
def get_status() -> dict:
    storage.init_db()
    c = storage.counts()
    uni = load_universe()
    pending_enrich = len(storage.hit_symbols_missing_metadata())
    return {
        "keys": {
            "alpaca": bool(settings.apca_api_key_id and settings.apca_api_secret_key),
            "finnhub": bool(settings.finnhub_api_key),
            "perplexity": bool(settings.perplexity_api_key),
        },
        "universe_symbols": uni["count"] if uni else 0,
        "universe_refreshed_at": uni["refreshed_at"] if uni else None,
        "bar_symbols": c["bar_symbols"],
        "hits": c["hits"],
        "assets": c["assets"],
        "assets_with_name": c["assets_with_name"],
        "assets_with_market_cap": c["assets_with_market_cap"],
        "hit_symbols_missing_metadata": pending_enrich,
        "catalysts": c["catalysts"],
    }


@router.get("/api/industries")
def get_industries() -> list[str]:
    return storage.list_hit_industries()


@router.post("/api/catalyst/batch")
def batch_catalysts(limit: int = 50) -> dict:
    """Fetch catalysts (Perplexity) for hits that don't have one yet, top-N by multiplier."""
    if not settings.perplexity_api_key:
        raise HTTPException(400, "PERPLEXITY_API_KEY not set. Add it to .env and restart.")
    pending = storage.hits_without_catalyst(limit=limit)
    if not pending:
        return {"pending": 0, "fetched": 0}
    job = new_job("catalyst_batch")
    job.total = len(pending)

    from datetime import datetime, timezone

    from grapefruit.catalyst import explain_move
    from grapefruit.detector import find_spike

    def task(j: JobState):
        fetched = 0
        for idx, h in enumerate(pending, start=1):
            sym = h["symbol"]
            start_ts = h["start_ts"]
            end_ts = h["end_ts"]
            meta = storage.load_asset(sym) or {}
            spike = None
            df = storage.load_symbol(sym, start=start_ts, end=end_ts)
            if not df.empty:
                spike = find_spike(
                    df["close"].to_numpy(dtype=float),
                    df["ts"].to_numpy(),
                    start_ts,
                    end_ts,
                )
            result = explain_move(
                sym,
                meta.get("name"),
                end_ts,
                trough_price=h.get("trough_price"),
                peak_price=h.get("peak_price"),
                start=start_ts,
                spike=spike,
            )
            if not result.get("error"):
                storage.upsert_catalyst(
                    {
                        "symbol": sym,
                        "end_ts": end_ts,
                        "headline": result.get("headline") or None,
                        "summary": result.get("summary") or None,
                        "spike_explanation": result.get("spike_explanation") or None,
                        "was_foreseeable": result.get("was_foreseeable"),
                        "foreseeable_evidence": result.get("foreseeable_evidence") or None,
                        "fetched_at": datetime.now(timezone.utc),
                    }
                )
                fetched += 1
            j.processed = idx
            j.message = f"{sym} {end_ts} ({idx}/{len(pending)})"
        return {"pending": len(pending), "fetched": fetched}

    run_async(job, task)
    return {"job_id": job.job_id, "pending": len(pending)}


def _iso(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, date):
        return v.isoformat()
    return str(v)
