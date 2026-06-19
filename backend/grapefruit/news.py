import json
from datetime import date, timedelta

from grapefruit import eodhd_client
from grapefruit.config import NEWS_CACHE_DIR


def _cache_path(symbol: str, around: date, days: int):
    return NEWS_CACHE_DIR / f"{symbol}_{around.isoformat()}_{days}.json"


def fetch_news(symbol: str, around: date, days: int = 14) -> list[dict]:
    cache = _cache_path(symbol, around, days)
    if cache.exists():
        return json.loads(cache.read_text())

    start = around - timedelta(days=days)
    end = around + timedelta(days=days)
    items = eodhd_client.fetch_news(symbol, start, end, limit=50)
    articles = [
        {
            "ts": n.get("date"),
            "headline": n.get("title"),
            "summary": n.get("content"),
            "url": n.get("link"),
            "source": "EODHD",
        }
        for n in items
    ]
    cache.write_text(json.dumps(articles))
    return articles
