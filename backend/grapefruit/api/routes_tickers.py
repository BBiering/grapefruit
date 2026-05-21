from datetime import date

from fastapi import APIRouter, HTTPException

from grapefruit import storage
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
