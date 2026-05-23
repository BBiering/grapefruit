"""Perplexity-backed catalyst explanations for big stock moves.

For each hit we cache a single JSON blob covering:
- the overall trough->peak catalyst,
- the sharpest single-session jump inside the window (if any),
- whether that jump was foreseeable from public information beforehand,
- and the pre-existing signal, if any.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timezone

import time

import httpx

from grapefruit.config import CATALYST_CACHE_DIR, settings
from grapefruit.rate_limit import PERPLEXITY_BUCKET, redact


log = logging.getLogger(__name__)

_PPLX_URL = "https://api.perplexity.ai/chat/completions"
_MODEL = "sonar"
_MAX_RETRIES = 3
_MAX_RETRY_SLEEP = 60.0


def _cache_path(symbol: str, around: date):
    return CATALYST_CACHE_DIR / f"{symbol}_{around.isoformat()}.json"


def explain_move(
    symbol: str,
    name: str | None,
    around: date,
    trough_price: float | None = None,
    peak_price: float | None = None,
    start: date | None = None,
    spike: dict | None = None,
    refresh: bool = False,
) -> dict:
    """Return a structured catalyst report. Cached forever on disk per (symbol, around)."""
    cache = _cache_path(symbol, around)
    if cache.exists() and not refresh:
        try:
            return json.loads(cache.read_text())
        except json.JSONDecodeError:
            pass

    base = {
        "headline": "",
        "summary": "",
        "spike": spike,
        "spike_explanation": "",
        "was_foreseeable": None,
        "foreseeable_evidence": "",
        "raw": "",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "model": _MODEL,
    }

    if not settings.perplexity_api_key:
        return {**base, "error": "no_key"}

    label = f"{symbol} ({name})" if name else symbol
    period = f"around {around.isoformat()}"
    if start:
        period = f"from {start.isoformat()} to {around.isoformat()}"
    move = ""
    if trough_price and peak_price:
        move = (
            f" The stock rose from about ${trough_price:.2f} to about "
            f"${peak_price:.2f} ({peak_price / trough_price:.1f}x)."
        )
    spike_section = ""
    if spike:
        spike_section = (
            f" Within the window, the single sharpest move was on "
            f"{spike['date']}: ${spike['prior_close']:.2f} -> ${spike['close']:.2f} "
            f"({spike['single_day_multiplier']:.1f}x in one trading session)."
        )

    user_msg = (
        f"Stock: {label}.\n"
        f"Window: {period}.{move}{spike_section}\n\n"
        "Reply with a JSON object only (no surrounding prose). Schema:\n"
        "{\n"
        '  "headline": "1-3 word tag for the catalyst (e.g. \\"Earnings beat\\", '
        '\\"FDA approval\\", \\"Trial readout\\", \\"M&A rumor\\", \\"Short squeeze\\"); '
        'use \\"No clear catalyst\\" if the rise was gradual",\n'
        '  "summary": "1-2 sentences on the primary catalyst for the overall rise",\n'
        '  "spike_explanation": "1-2 sentences on what news/event/filing drove the '
        f"{spike['date'] if spike else 'sharpest'} single-session jump specifically; "
        'say so if the rise was gradual rather than event-driven",\n'
        '  "was_foreseeable": true or false (was there PUBLIC information '
        "BEFORE the spike date that a careful trader could have used to anticipate "
        "this move? e.g. scheduled FDA decision, trial readout date, earnings date, "
        'patent expiry, contract award timeline),\n'
        '  "foreseeable_evidence": "if was_foreseeable is true, describe the '
        'pre-existing public signal in one sentence with approximate date; otherwise '
        'empty string"\n'
        "}"
    )

    payload = {
        "model": _MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a financial research assistant. Identify real-world "
                    "catalysts for sharp US-equity moves. Return only the JSON object "
                    "matching the user's schema; do not wrap it in prose or fences."
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
        resp = _post_with_retry(headers, payload, symbol)
        if resp is None:
            return {**base, "error": "rate_limited"}
        data = resp.json()
        raw = data["choices"][0]["message"]["content"].strip()
        parsed = _parse_json_response(raw)
        result = {
            **base,
            "headline": (parsed.get("headline") or "").strip(),
            "summary": (parsed.get("summary") or "").strip(),
            "spike_explanation": (parsed.get("spike_explanation") or "").strip(),
            "was_foreseeable": parsed.get("was_foreseeable")
            if isinstance(parsed.get("was_foreseeable"), bool)
            else None,
            "foreseeable_evidence": (parsed.get("foreseeable_evidence") or "").strip(),
            "raw": raw,
        }
        if not result["summary"] and not parsed:
            # Couldn't parse JSON; fall back to the raw text as the summary so the
            # user still sees something useful.
            result["summary"] = raw
        cache.write_text(json.dumps(result))
        return result
    except httpx.HTTPStatusError as exc:
        body = ""
        try:
            body = redact(exc.response.text[:500])
        except Exception:  # noqa: BLE001
            pass
        log.warning("perplexity %s returned %s: %s", symbol, exc.response.status_code, body)
        return {**base, "error": f"http_{exc.response.status_code}"}
    except Exception as exc:  # noqa: BLE001
        log.warning("perplexity fetch failed for %s: %s", symbol, redact(str(exc)))
        return {**base, "error": f"fetch_failed: {type(exc).__name__}"}


def _post_with_retry(headers: dict, payload: dict, symbol: str) -> httpx.Response | None:
    """POST to Perplexity with rate-limiting and 429 retry. Returns the response or None."""
    for attempt in range(_MAX_RETRIES):
        PERPLEXITY_BUCKET.acquire()
        resp = httpx.post(_PPLX_URL, headers=headers, json=payload, timeout=45.0)
        if resp.status_code == 429:
            retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
            log.warning(
                "perplexity 429 for %s; sleeping %.1fs (attempt %d/%d)",
                symbol, retry_after, attempt + 1, _MAX_RETRIES,
            )
            time.sleep(retry_after)
            continue
        resp.raise_for_status()
        return resp
    log.warning("perplexity gave up on %s after %d 429s", symbol, _MAX_RETRIES)
    return None


def _parse_retry_after(header: str | None) -> float:
    if not header:
        return 5.0
    try:
        return min(float(header), _MAX_RETRY_SLEEP)
    except ValueError:
        return 5.0


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_json_response(text: str) -> dict:
    """Pull a JSON object out of Perplexity's reply, robust to fences and prose."""
    if not text:
        return {}
    # Try fenced ```json blocks first.
    m = _JSON_BLOCK_RE.search(text)
    candidate = m.group(1) if m else None
    if candidate is None:
        m2 = _BARE_JSON_RE.search(text)
        candidate = m2.group(0) if m2 else None
    if candidate is None:
        return {}
    try:
        obj = json.loads(candidate)
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        return {}
