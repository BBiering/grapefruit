import json
from datetime import datetime, timezone

from alpaca.trading.enums import AssetClass, AssetStatus
from alpaca.trading.requests import GetAssetsRequest

from grapefruit.alpaca_client import get_trading_client
from grapefruit.config import UNIVERSE_PATH


def fetch_active_universe() -> dict:
    """Fetch all active, tradable US equities and cache to disk."""
    client = get_trading_client()
    req = GetAssetsRequest(status=AssetStatus.ACTIVE, asset_class=AssetClass.US_EQUITY)
    assets = client.get_all_assets(req)

    symbols = sorted(
        a.symbol
        for a in assets
        if a.tradable and a.symbol and "/" not in a.symbol and "." not in a.symbol
    )
    payload = {
        "symbols": symbols,
        "count": len(symbols),
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
    }
    UNIVERSE_PATH.write_text(json.dumps(payload))
    return payload


def load_universe() -> dict | None:
    if not UNIVERSE_PATH.exists():
        return None
    return json.loads(UNIVERSE_PATH.read_text())
