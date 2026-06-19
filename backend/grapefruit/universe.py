from datetime import datetime, timezone

from grapefruit import eodhd_client, storage


_KEY = "universe"


def fetch_active_universe() -> dict:
    """Fetch all common US stocks from EODHD and cache in `app_state`."""
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
    storage.set_app_state(_KEY, payload)
    return payload


def load_universe() -> dict | None:
    return storage.get_app_state(_KEY)
