import json
from datetime import date, datetime, timedelta, timezone

from alpaca.data.requests import NewsRequest

from grapefruit.alpaca_client import get_news_client
from grapefruit.config import NEWS_CACHE_DIR


def _cache_path(symbol: str, around: date, days: int):
    return NEWS_CACHE_DIR / f"{symbol}_{around.isoformat()}_{days}.json"


def fetch_news(symbol: str, around: date, days: int = 14) -> list[dict]:
    cache = _cache_path(symbol, around, days)
    if cache.exists():
        return json.loads(cache.read_text())

    client = get_news_client()
    start = datetime.combine(
        around - timedelta(days=days), datetime.min.time(), tzinfo=timezone.utc
    )
    end = datetime.combine(
        around + timedelta(days=days), datetime.min.time(), tzinfo=timezone.utc
    )
    req = NewsRequest(symbols=symbol, start=start, end=end, limit=50)
    resp = client.get_news(req)
    articles = []
    for n in resp.data.get("news", []) if isinstance(resp.data, dict) else resp.data:
        articles.append(
            {
                "ts": (n.created_at.isoformat() if n.created_at else None),
                "headline": n.headline,
                "summary": n.summary,
                "url": n.url,
                "source": n.source,
            }
        )
    cache.write_text(json.dumps(articles))
    return articles
