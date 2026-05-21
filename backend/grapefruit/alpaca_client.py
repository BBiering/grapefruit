from functools import lru_cache

from alpaca.data.historical.news import NewsClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.trading.client import TradingClient

from grapefruit.config import settings


def _require_keys() -> tuple[str, str]:
    if not settings.apca_api_key_id or not settings.apca_api_secret_key:
        raise RuntimeError(
            "Alpaca API keys not set. Copy .env.example to .env and fill "
            "APCA_API_KEY_ID and APCA_API_SECRET_KEY."
        )
    return settings.apca_api_key_id, settings.apca_api_secret_key


@lru_cache(maxsize=1)
def get_data_client() -> StockHistoricalDataClient:
    key, secret = _require_keys()
    return StockHistoricalDataClient(api_key=key, secret_key=secret)


@lru_cache(maxsize=1)
def get_trading_client() -> TradingClient:
    key, secret = _require_keys()
    return TradingClient(api_key=key, secret_key=secret, paper=True)


@lru_cache(maxsize=1)
def get_news_client() -> NewsClient:
    key, secret = _require_keys()
    return NewsClient(api_key=key, secret_key=secret)
