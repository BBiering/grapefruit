"""Perplexity-backed catalyst analysis.

Two-step flow (Perplexity Search API + Sonar chat):
1. `/search` returns ranked web results as structured JSON (title, url,
   snippet, date) — cheap, per-request pricing, no token charges.
2. A Sonar chat completion extracts a structured catalyst report from those
   results, so `source_url` is grounded in real results, not hallucinated.

Also provides `explain_move` for past step changes (kept on chat completions
since it reasons about known price data rather than needing fresh retrieval).
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

_SONAR_URL = "https://api.perplexity.ai/chat/completions"
_SEARCH_URL = "https://api.perplexity.ai/search"
_MODEL = "sonar"
_FORWARD_MODEL = "sonar-pro"  # stronger web reasoning for catalyst extraction
_MAX_RETRIES = 3
_MAX_RETRY_SLEEP = 60.0


def web_search(
    query: str,
    max_results: int = 8,
    country: str | None = None,
) -> list[dict]:
    """Step 1: Perplexity Search API — ranked web results as structured JSON.

    Returns a list of {title, url, snippet, date, last_updated}. Empty list on
    any failure. Billed per request (no token charges).
    """
    if not settings.perplexity_api_key:
        return []
    payload: dict = {"query": query, "max_results": max_results}
    if country:
        payload["country"] = country
    headers = {
        "Authorization": f"Bearer {settings.perplexity_api_key}",
        "Content-Type": "application/json",
    }
    try:
        resp = _post_search(headers, payload)
        if resp is None:
            return []
        data = resp.json()
        return data.get("results", []) if isinstance(data, dict) else []
    except Exception as exc:  # noqa: BLE001
        log.warning("perplexity search failed: %s", redact(str(exc)))
        return []


def scan_catalyst(
    symbol: str,
    name: str | None = None,
    price: float | None = None,
    sector: str | None = None,
) -> dict:
    """Two-step future-catalyst scan for a single symbol.

    1. Search the web for upcoming scheduled events (next ~3 months).
    2. Ask sonar-pro to extract a structured report from the search results.

    Returns {detected, event_name, event_date, impact_type, expected_impact_pct,
    confidence, strategic_summary, source_url, error?}. Never raises.
    """
    base = {
        "detected": False,
        "event_name": None,
        "event_date": None,
        "impact_type": None,
        "expected_impact_pct": None,
        "confidence": None,
        "strategic_summary": None,
        "source_url": None,
    }
    if not settings.perplexity_api_key:
        return {**base, "error": "no_key"}

    label = f"{symbol} ({name})" if name else symbol
    price_str = f"${price:.2f}" if isinstance(price, (int, float)) else "unknown"
    sector_str = sector or "Unknown"

    # --- Step 1: retrieve evidence -------------------------------------------------
    query = (
        f"{label} upcoming catalyst events scheduled next 3 months: "
        f"FDA/EMA decisions, clinical trial readouts, earnings dates, spin-offs. "
        f"Sector: {sector_str}, price ~{price_str}."
    )
    results = web_search(query, max_results=8, country="FR")
    if not results:
        return {**base, "error": "no_search_results"}

    # --- Step 2: extract structured report from results ---------------------------
    context = "\n".join(
        f"[{i + 1}] {r.get('title', '')} ({r.get('date', 'unknown date')})\n"
        f"    URL: {r.get('url', '')}\n"
        f"    {r.get('snippet', '')[:400]}"
        for i, r in enumerate(results)
    )

    user_msg = (
        "You are an institutional research analyst. Based ONLY on the web search "
        "results below, identify SPECIFIC upcoming catalyst events in the next "
        "3 months for the European stock "
        f"'{label}' (sector: {sector_str}, price ~{price_str}).\n\n"
        "Focus on scheduled events with a date or narrow window: FDA/EMA decisions, "
        "clinical trial readouts, earnings dates, spin-offs, major contract decisions. "
        "Ignore historical news.\n\n"
        "Search results:\n"
        f"{context}\n\n"
        "Return a JSON object with exactly these keys:\n"
        "{\n"
        '  "catalyst_detected": true or false,\n'
        '  "event_name": "specific event name or empty string",\n'
        '  "event_date": "YYYY-MM-DD or empty if not known",\n'
        '  "impact_type": "Earnings | Regulatory | Clinical Trial | Spin-off | Contract | Other",\n'
        '  "expected_impact_pct": number (estimated price change %, e.g. 15.0 for +15%),\n'
        '  "confidence": "high" | "medium" | "low",\n'
        '  "strategic_summary": "1-2 sentences on the catalyst and potential impact",\n'
        '  "source_url": "the URL from the search results that supports this -- must be one of the URLs above"\n'
        "}"
    )

    parsed = _query_json(user_msg)
    if not parsed:
        return {**base, "error": "unparseable"}

    detected = bool(parsed.get("catalyst_detected"))
    source_url = (parsed.get("source_url") or "").strip() or None
    # Only accept a source URL that actually came from search results.
    known_urls = {r.get("url") for r in results}
    if source_url and source_url not in known_urls:
        source_url = None

    return {
        "detected": detected,
        "event_name": (parsed.get("event_name") or "").strip() or None,
        "event_date": (parsed.get("event_date") or "").strip() or None,
        "impact_type": (parsed.get("impact_type") or "").strip() or None,
        "expected_impact_pct": parsed.get("expected_impact_pct"),
        "confidence": (parsed.get("confidence") or "").strip().lower() or None,
        "strategic_summary": (parsed.get("strategic_summary") or "").strip() or None,
        "source_url": source_url,
    }


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
    """Explain a past 5x+ step change with a structured catalyst report.

    Reasons about known price data (no retrieval needed), so it stays on the
    regular chat-completions endpoint. Pure function — the caller persists.
    """
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
                    "catalysts for sharp European equity moves. Return only the JSON object "
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
        resp = _post_with_retry(_SONAR_URL, headers, payload, symbol)
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


# ---------------------------------------------------------------------------
# low-level HTTP helpers
# ---------------------------------------------------------------------------

def _query_json(user_msg: str, model: str = _FORWARD_MODEL) -> dict:
    """Single sonar chat call that returns the parsed JSON from the answer."""
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a precise financial data extraction engine. Return ONLY "
                    "the JSON object matching the user's schema; no prose or fences."
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
        resp = _post_with_retry(_SONAR_URL, headers, payload, "extract")
        if resp is None:
            return {}
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        return _parse_json_response(raw)
    except Exception as exc:  # noqa: BLE001
        log.warning("perplexity extraction failed: %s", redact(str(exc)))
        return {}


def _post_search(headers: dict, payload: dict) -> httpx.Response | None:
    """POST /search with 429/5xx retry honoring Retry-After."""
    for attempt in range(_MAX_RETRIES):
        PERPLEXITY_BUCKET.acquire()
        try:
            resp = httpx.post(_SEARCH_URL, headers=headers, json=payload, timeout=45.0)
        except Exception as exc:  # noqa: BLE001
            if attempt + 1 >= _MAX_RETRIES:
                log.warning("perplexity search request failed: %s", redact(str(exc)))
                return None
            time.sleep(2 ** attempt)
            continue
        if resp.status_code == 429:
            retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
            log.warning(
                "perplexity search 429; sleeping %.1fs (attempt %d/%d)",
                retry_after, attempt + 1, _MAX_RETRIES,
            )
            time.sleep(retry_after)
            continue
        if resp.status_code >= 500:
            retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
            if attempt + 1 < _MAX_RETRIES:
                log.warning(
                    "perplexity search %d; sleeping %.1fs (attempt %d/%d)",
                    resp.status_code, retry_after, attempt + 1, _MAX_RETRIES,
                )
                time.sleep(retry_after)
                continue
        if resp.status_code >= 400:
            log.warning(
                "perplexity search %d: %s",
                resp.status_code, redact(resp.text[:300]),
            )
            return None
        return resp
    return None


def _post_with_retry(url: str, headers: dict, payload: dict, symbol: str) -> httpx.Response | None:
    """POST chat completions with 429/5xx retry honoring Retry-After."""
    for attempt in range(_MAX_RETRIES):
        PERPLEXITY_BUCKET.acquire()
        resp = httpx.post(url, headers=headers, json=payload, timeout=45.0)
        if resp.status_code == 429:
            retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
            log.warning(
                "perplexity 429 for %s; sleeping %.1fs (attempt %d/%d)",
                symbol, retry_after, attempt + 1, _MAX_RETRIES,
            )
            time.sleep(retry_after)
            continue
        if resp.status_code >= 500:
            retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
            if attempt + 1 < _MAX_RETRIES:
                log.warning(
                    "perplexity %d for %s; sleeping %.1fs (attempt %d/%d)",
                    resp.status_code, symbol, retry_after, attempt + 1, _MAX_RETRIES,
                )
                time.sleep(retry_after)
                continue
        resp.raise_for_status()
        return resp
    log.warning("perplexity gave up on %s after %d retries", symbol, _MAX_RETRIES)
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
