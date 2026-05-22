from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException

from grapefruit import metadata, storage
from grapefruit.catalyst import explain_move
from grapefruit.detector import find_spike
from grapefruit.news import fetch_news

router = APIRouter()


@router.get("/api/tickers/{symbol}/bars")
def get_bars(symbol: str, start: date | None = None, end: date | None = None) -> list[dict]:
    df = storage.load_symbol(symbol.upper(), start=start, end=end)
    if df.empty:
        return []
    return [
        {
            "ts": row.ts.isoformat() if hasattr(row.ts, "isoformat") else str(row.ts),
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "volume": int(row.volume),
        }
        for row in df.itertuples(index=False)
    ]


@router.get("/api/tickers/{symbol}/news")
def get_news(symbol: str, around: date, days: int = 14) -> list[dict]:
    try:
        return fetch_news(symbol.upper(), around, days=days)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"news fetch failed: {exc}") from exc


@router.get("/api/tickers/{symbol}/meta")
def get_meta(symbol: str, refresh: bool = False) -> dict:
    row = metadata.get_or_fetch(symbol.upper(), refresh=refresh)
    refreshed = row.get("refreshed_at")
    return {
        "symbol": row["symbol"],
        "name": row.get("name"),
        "exchange": row.get("exchange"),
        "sector": row.get("sector"),
        "industry": row.get("industry"),
        "refreshed_at": refreshed.isoformat() if hasattr(refreshed, "isoformat") else refreshed,
    }


@router.get("/api/tickers/{symbol}/catalyst")
def get_catalyst(
    symbol: str,
    around: date,
    start: date | None = None,
    trough_price: float | None = None,
    peak_price: float | None = None,
    refresh: bool = False,
) -> dict:
    sym = symbol.upper()
    meta = storage.load_asset(sym) or {}
    spike = None
    if start:
        df = storage.load_symbol(sym, start=start, end=around)
        if not df.empty:
            spike = find_spike(
                df["close"].to_numpy(dtype=float),
                df["ts"].to_numpy(),
                start,
                around,
            )
    result = explain_move(
        sym,
        meta.get("name"),
        around,
        trough_price=trough_price,
        peak_price=peak_price,
        start=start,
        spike=spike,
        refresh=refresh,
    )
    if not result.get("error"):
        storage.upsert_catalyst(
            {
                "symbol": sym,
                "end_ts": around,
                "headline": result.get("headline") or None,
                "summary": result.get("summary") or None,
                "spike_explanation": result.get("spike_explanation") or None,
                "was_foreseeable": result.get("was_foreseeable"),
                "foreseeable_evidence": result.get("foreseeable_evidence") or None,
                "fetched_at": datetime.now(timezone.utc),
            }
        )
    return result


@router.get("/api/tickers/{symbol}/spike")
def get_spike(symbol: str, start: date, end: date) -> dict:
    sym = symbol.upper()
    df = storage.load_symbol(sym, start=start, end=end)
    if df.empty:
        raise HTTPException(404, f"No cached bars for {sym} in [{start}, {end}]")
    spike = find_spike(
        df["close"].to_numpy(dtype=float),
        df["ts"].to_numpy(),
        start,
        end,
    )
    if spike is None:
        raise HTTPException(404, "Window too short to compute a spike")
    return spike
