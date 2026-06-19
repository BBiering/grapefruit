from datetime import date, timedelta

from grapefruit import eodhd_client, storage


def fetch_news(symbol: str, around: date, days: int = 14) -> list[dict]:
    cached = storage.load_news(symbol, around, days)
    if cached is not None:
        return cached

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
    storage.upsert_news(symbol, around, days, articles)
    return articles
