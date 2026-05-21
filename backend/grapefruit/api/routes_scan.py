from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from grapefruit import bars as bars_mod
from grapefruit import metadata, storage
from grapefruit.detector import detect_hits
from grapefruit.jobs import JobState, new_job, run_async
from grapefruit.universe import fetch_active_universe, load_universe


ENRICH_TOP_N = 200

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


@router.get("/api/hits")
def get_hits(
    window_weeks: int | None = None,
    min_multiplier: float | None = None,
    max_days_since_peak: int | None = None,
    min_peak_retention: float | None = None,
) -> list[dict]:
    rows = storage.query_hits(
        window_weeks=window_weeks,
        min_multiplier=min_multiplier,
        max_days_since_peak=max_days_since_peak,
        min_peak_retention=min_peak_retention,
    )
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


def _iso(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, date):
        return v.isoformat()
    return str(v)
