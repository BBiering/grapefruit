"""Perplexity-backed catalyst explanations for big stock moves.

For each hit we cache:
- the overall trough->peak catalyst,
- the sharpest single-session jump inside the window (recomputed per call),
- whether that jump was foreseeable from public information beforehand,
- and the pre-existing signal, if any.

Persistence is in the `catalysts` Postgres table via grapefruit.storage. No
disk caches.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import date, datetime, timezone

import httpx

from grapefruit.config import settings
from grapefruit.rate_limit import PERPLEXITY_BUCKET, redact


log = logging.getLogger(__name__)

_PPLX_URL = "https://api.perplexity.ai/chat/completions"
_MODEL = "sonar"
_FORWARD_MODEL = "sonar-pro"  # stronger web reasoning for the look-ahead scan
_MAX_RETRIES = 3
_MAX_RETRY_SLEEP = 60.0


def forward_catalyst(symbol: str, name: str | None, price: float | None) -> dict:
    """Scan the live web for an IMMINENT (next 1–90 days) forward-looking catalyst
    for `symbol`, using sonar-pro with native JSON mode.

    Returns {detected, event_name, impact_type, expected_window, strategic_summary,
    source_url, model, error?}. Never raises — errors are returned in `error`.
    """
    base = {
        "symbol": symbol,
        "detected": False,
        "event_name": None,
        "impact_type": None,
        "expected_window": None,
        "strategic_summary": None,
        "source_url": None,
        "model": _FORWARD_MODEL,
    }
    if not settings.perplexity_api_key:
        return {**base, "error": "no_key"}

    label = f"{symbol} ({name})" if name else symbol
    price_str = f"${price:.2f}" if isinstance(price, (int, float)) else "unknown"
    user_msg = (
        "You are an institutional research analyst hunting for forward-looking, "
        "high-impact stock catalysts. Analyze the live web, SEC EDGAR filings "
        "(especially recent 8-Ks), corporate calendars, and bio/tech registries "
        f"for the ticker '{label}' (currently around {price_str}).\n\n"
        "Identify a SCHEDULED or highly anticipated FUTURE event in the next 1 to "
        "90 days that could cause a large structural re-pricing (e.g. Phase 2/3 "
        "trial data readouts, FDA PDUFA decision dates, scheduled spin-offs, "
        "earnings dates with expected guidance changes, pending regulatory "
        "approvals, or major contract decisions). Ignore old news unless it sets "
        "up an imminent future event.\n\n"
        "Return a JSON object with exactly these keys:\n"
        "{\n"
        '  "imminent_future_catalyst_detected": true or false,\n'
        '  "catalyst_event_name": "name of the specific future event, or empty",\n'
        '  "expected_date_window": "YYYY-MM-DD or a short timeframe, or empty",\n'
        '  "catalyst_impact_type": "Binary FDA | Earnings | Spin-off | Contract | Regulatory | Other",\n'
        '  "strategic_summary": "1-2 sentences on exactly what is dropping and why it could reprice the stock",\n'
        '  "verified_source_url": "the exact live URL referencing this upcoming event, or empty"\n'
        "}"
    )
    payload = {
        "model": _FORWARD_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a precise financial data extraction engine. You speak "
                    "exclusively in structured JSON objects."
                ),
            },
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.2,
    }
    headers = {
        "Authorization": f"Bearer {settings.perplexity_api_key}",
        "Content-Type": "application/json",
    }
    try:
        resp = _post_with_retry(headers, payload, symbol)
        if resp is None:
            return {**base, "error": "rate_limited"}
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        parsed = _parse_json_response(raw)
        if not parsed:
            return {**base, "error": "unparseable"}
        return {
            **base,
            "detected": bool(parsed.get("imminent_future_catalyst_detected")),
            "event_name": (parsed.get("catalyst_event_name") or "").strip() or None,
            "impact_type": (parsed.get("catalyst_impact_type") or "").strip() or None,
            "expected_window": (parsed.get("expected_date_window") or "").strip() or None,
            "strategic_summary": (parsed.get("strategic_summary") or "").strip() or None,
            "source_url": (parsed.get("verified_source_url") or "").strip() or None,
        }
    except httpx.HTTPStatusError as exc:
        log.warning("perplexity forward %s returned %s", symbol, exc.response.status_code)
        return {**base, "error": f"http_{exc.response.status_code}"}
    except Exception as exc:  # noqa: BLE001
        log.warning("perplexity forward fetch failed for %s: %s", symbol, redact(str(exc)))
        return {**base, "error": f"fetch_failed: {type(exc).__name__}"}


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
    """Return a structured catalyst report. Pure function — caller is responsible
    for caching/persistence (e.g. into `winner_catalysts`). The `refresh` arg is
    retained for API compatibility but ignored."""
    del refresh  # caching is handled by callers now

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
            result["summary"] = raw
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
    if not text:
        return {}
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
