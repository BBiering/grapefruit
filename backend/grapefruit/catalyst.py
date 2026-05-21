"""Perplexity-backed one-sentence catalyst explanations for big stock moves."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone

import httpx

from grapefruit.config import CATALYST_CACHE_DIR, settings


log = logging.getLogger(__name__)

_PPLX_URL = "https://api.perplexity.ai/chat/completions"
_MODEL = "sonar"


def _cache_path(symbol: str, around: date):
    return CATALYST_CACHE_DIR / f"{symbol}_{around.isoformat()}.json"


def explain_move(
    symbol: str,
    name: str | None,
    around: date,
    trough_price: float | None = None,
    peak_price: float | None = None,
    refresh: bool = False,
) -> dict:
    """Return {summary, fetched_at, model, error?}. Cached forever on disk."""
    cache = _cache_path(symbol, around)
    if cache.exists() and not refresh:
        try:
            return json.loads(cache.read_text())
        except json.JSONDecodeError:
            pass

    if not settings.perplexity_api_key:
        return {
            "summary": "",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "model": _MODEL,
            "error": "no_key",
        }

    label = f"{symbol} ({name})" if name else symbol
    move = ""
    if trough_price and peak_price:
        move = f" — the stock moved from about ${trough_price:.2f} to ${peak_price:.2f}"
    user_msg = (
        f"What was the primary catalyst behind the sharp price increase of {label} "
        f"around {around.isoformat()}{move}? Answer in one or two sentences. "
        "Be specific (product launch, earnings beat, deal, FDA approval, etc.) "
        "and cite the approximate date if relevant."
    )

    payload = {
        "model": _MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a financial research assistant. Identify the most likely "
                    "real-world catalyst for a sharp move in a US-listed stock. Be "
                    "concrete; if no clear catalyst exists, say so."
                ),
            },
            {"role": "user", "content": user_msg},
        ],
    }
    headers = {
        "Authorization": f"Bearer {settings.perplexity_api_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = httpx.post(_PPLX_URL, headers=headers, json=payload, timeout=30.0)
        resp.raise_for_status()
        data = resp.json()
        summary = data["choices"][0]["message"]["content"].strip()
        result = {
            "summary": summary,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "model": _MODEL,
        }
        cache.write_text(json.dumps(result))
        return result
    except httpx.HTTPStatusError as exc:
        log.warning("perplexity %s returned %s", symbol, exc.response.status_code)
        return {
            "summary": "",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "model": _MODEL,
            "error": f"http_{exc.response.status_code}",
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("perplexity fetch failed for %s: %s", symbol, exc)
        return {
            "summary": "",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "model": _MODEL,
            "error": "fetch_failed",
        }
