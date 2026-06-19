import json
from datetime import datetime, timezone

from grapefruit import eodhd_client
from grapefruit.config import UNIVERSE_PATH


def fetch_active_universe() -> dict:
    """Fetch all common US stocks from EODHD and cache to disk."""
    assets = eodhd_client.list_symbols()

    symbols = sorted(
        a["Code"]
        for a in assets
        if a.get("Code")
        and a.get("Type") == "Common Stock"
        and "/" not in a["Code"]
        and "." not in a["Code"]
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
