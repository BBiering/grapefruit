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

# Lazy import perplexity SDK (only for Agent API calls)
_perplexity_client = None


def _get_perplexity_client():
    global _perplexity_client
    if _perplexity_client is None:
        try:
            from perplexity import Perplexity
            _perplexity_client = Perplexity(api_key=settings.perplexity_api_key)
        except ImportError:
            log.warning("perplexity SDK not installed; falling back to httpx")
            _perplexity_client = False  # sentinel
    return _perplexity_client if _perplexity_client is not False else None


def forward_catalyst(symbol: str, name: str | None, price: float | None) -> dict:
    """Scan the live web for an IMMINENT (next 1–90 days) forward-looking catalyst
    for `symbol`, using Perplexity Agent API with finance_search, web_search, and
    fetch_url tools. Falls back to chat completion if Agent API unavailable.

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

    # Try Agent API first (preferred for finance_search access)
    client = _get_perplexity_client()
    if client:
        return _forward_catalyst_agent_api(client, base, label, price_str, symbol)

    # Fallback to chat completion API
    return _forward_catalyst_chat_api(base, label, price_str, symbol)


def _forward_catalyst_agent_api(client, base: dict, label: str, price_str: str, symbol: str) -> dict:
    """Use Perplexity Agent API (Responses API) with finance_search tools."""
    user_msg = (
        "You are an institutional research analyst hunting for forward-looking, high-impact stock catalysts. "
        f"Analyze live data for ticker '{label}' (price ~{price_str}).\n\n"
        "Identify a SCHEDULED or highly anticipated FUTURE event in the next 1–90 days that could cause "
        "a large structural re-pricing (Phase 2/3 readouts, FDA PDUFA dates, scheduled spin-offs, earnings "
        "with expected guidance shifts, pending regulatory approvals, major contract decisions). "
        "Ignore old news unless it sets up an imminent future event.\n\n"
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

    instructions = (
        "You have access to finance_search, web_search, and fetch_url. "
        "Use finance_search first for any ticker-specific data (prices, filings, estimates, transcripts, earnings dates). "
        "Use web_search for catalyst calendars, trial registries, FDA calendars, and corporate IR pages. "
        "Use fetch_url to pull full 8-Ks, press releases, or clinical trial protocol pages when needed. "
        "Always verify the event is future-dated and scheduled, not historical. "
        "Return ONLY the JSON object, no surrounding text."
    )

    try:
        PERPLEXITY_BUCKET.acquire()
        # Agent API uses preset names, not model names
        # "pro-search" is the strongest preset with finance_search access
        response = client.responses.create(
            preset="pro-search",
            input=user_msg,
            tools=[
                {"type": "finance_search"},
                {"type": "web_search"},
                {"type": "fetch_url"},
            ],
            instructions=instructions,
        )

        # Extract content from Agent API response
        # Response.output is a list; the last message item contains the text response
        raw = ""
        if hasattr(response, "output") and response.output:
            for item in response.output:
                if hasattr(item, "type") and item.type == "message":
                    if hasattr(item, "content") and item.content:
                        for part in item.content:
                            if hasattr(part, "text"):
                                raw += part.text

        if not raw:
            raw = str(response)

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
    except Exception as exc:  # noqa: BLE001
        log.warning("perplexity agent API failed for %s: %s", symbol, redact(str(exc)))
        return {**base, "error": f"agent_api_failed: {type(exc).__name__}"}


def _forward_catalyst_chat_api(base: dict, label: str, price_str: str, symbol: str) -> dict:
    """Fallback to chat completion API (no finance_search tools)."""
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


# ============================================================================
# Tier-specific catalyst detection functions
# ============================================================================


def tier1_biotech_catalyst(symbol: str, name: str | None = None, price: float | None = None) -> dict:
    """Tier 1: Hunt for FDA PDUFA dates, AdCom votes, Phase 2b/3 readouts (biotech)."""
    label = f"{symbol} ({name or 'N/A'})"
    price_str = f"${price:.2f}" if price else "unknown"

    user_msg = (
        f"You are hunting for binary FDA and clinical trial catalysts for biotech ticker '{label}' (price ~{price_str}).\n\n"
        "TIER 1 CATALYSTS TO DETECT (highest priority):\n"
        "1. FDA PDUFA target action dates - exact decision deadline\n"
        "2. FDA AdCom meeting dates - advisory committee vote\n"
        "3. Phase 2b or Phase 3 topline data readout dates - final trial results unlock\n"
        "4. BLA/NDA submission acceptance with assigned PDUFA date\n\n"
        "Search:\n"
        "- FDA PDUFA calendar trackers\n"
        "- ClinicalTrials.gov for trial completion timelines\n"
        "- Company IR pages for trial milestone guidance\n"
        "- Biotech databases (e.g., BioPharmCatalyst)\n"
        "- SEC 8-K filings announcing regulatory milestones\n\n"
        "Return JSON:\n"
        "{\n"
        '  "tier1_catalyst_detected": true/false,\n'
        '  "event_name": "specific event name",\n'
        '  "event_type": "FDA PDUFA" | "FDA AdCom" | "Phase 3 Readout" | "Phase 2b Readout",\n'
        '  "event_date": "YYYY-MM-DD or empty if vague",\n'
        '  "expected_window": "Q2 2026" if no exact date,\n'
        '  "confidence": 0.0-1.0 (1.0 = official filing, 0.6 = management guidance),\n'
        '  "strategic_summary": "1-2 sentences on what\'s being decided and potential impact",\n'
        '  "source_url": "exact URL of official source"\n'
        "}\n\n"
        "Only return detected=true if there's a scheduled or highly anticipated event in next 1-180 days."
    )

    instructions = (
        "Use finance_search first for any ticker-specific data (prices, filings, estimates, transcripts). "
        "Use web_search for FDA calendars, ClinicalTrials.gov, biotech databases, and company IR pages. "
        "Use fetch_url to pull full 8-Ks, press releases, or clinical trial protocol pages when needed. "
        "Always verify the event is future-dated and scheduled, not historical."
    )

    base = {
        "symbol": symbol,
        "detected": False,
        "event_name": None,
        "impact_type": None,
        "expected_window": None,
        "strategic_summary": None,
        "source_url": None,
        "model": _FORWARD_MODEL,
        "tier": 1,
        "tier_name": "Systemic Volatility",
        "confidence_score": None,
        "sector_targeted": True,
    }

    label = f"{symbol} ({name})" if name else symbol
    price_str = f"${price:.2f}" if isinstance(price, (int, float)) else "unknown"

    try:
        client = _get_perplexity_client()
        if client:
            result = _forward_catalyst_agent_api(client, base, label, price_str, symbol)
        else:
            result = _forward_catalyst_chat_api(base, label, price_str, symbol)

        parsed = _parse_json_response(result)
        detected = parsed.get("tier1_catalyst_detected", False)

        return {
            **base,
            "detected": detected,
            "event_name": parsed.get("event_name") if detected else None,
            "impact_type": parsed.get("event_type") if detected else None,
            "expected_window": parsed.get("expected_window") or parsed.get("event_date") if detected else None,
            "strategic_summary": parsed.get("strategic_summary") if detected else None,
            "source_url": parsed.get("source_url") if detected else None,
            "confidence_score": parsed.get("confidence") if detected else None,
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("tier1 biotech catalyst failed for %s: %s", symbol, redact(str(exc)))
        return {**base, "error": f"fetch_failed: {type(exc).__name__}"}


def tier1_spinoff_catalyst(symbol: str, name: str | None = None, price: float | None = None) -> dict:
    """Tier 1: Hunt for corporate spin-offs and carve-outs."""
    label = f"{symbol} ({name or 'N/A'})"
    price_str = f"${price:.2f}" if price else "unknown"

    user_msg = (
        f"Search for corporate spin-off or carve-out activity for ticker '{label}' (price ~{price_str}).\n\n"
        "TIER 1 SPIN-OFF CATALYSTS:\n"
        "- Announced spin-offs with ex-date scheduled\n"
        "- Business unit carve-outs creating new publicly traded entities\n"
        "- Reverse Morris Trust transactions\n\n"
        "Search:\n"
        "- SEC Form 10-12B/A registration statements\n"
        "- SEC Form 8-K spin-off announcements\n"
        "- Investor presentations mentioning strategic separation\n"
        "- Proxy statements with spin-off shareholder votes\n\n"
        "Return JSON:\n"
        "{\n"
        '  "spinoff_detected": true/false,\n'
        '  "event_name": "specific spin-off name",\n'
        '  "event_date": "YYYY-MM-DD distribution date or empty",\n'
        '  "expected_window": "Q3 2026" if no exact date,\n'
        '  "confidence": 0.0-1.0,\n'
        '  "strategic_summary": "what entity is being spun off and why it\'s undervalued",\n'
        '  "source_url": "SEC filing or official announcement"\n'
        "}\n\n"
        "Only return detected=true if spin-off is officially announced and scheduled within 180 days."
    )

    instructions = (
        "Use finance_search for SEC filings and investor presentations. "
        "Use web_search for spin-off announcements and proxy statements. "
        "Use fetch_url to pull full Form 10-12B/A or 8-K filings. "
        "Verify the spin-off is officially announced, not just rumored."
    )

    base = {
        "symbol": symbol,
        "detected": False,
        "event_name": None,
        "impact_type": "Spin-off",
        "expected_window": None,
        "strategic_summary": None,
        "source_url": None,
        "model": _FORWARD_MODEL,
        "tier": 1,
        "tier_name": "Systemic Volatility",
        "confidence_score": None,
        "sector_targeted": False,
    }

    label = f"{symbol} ({name})" if name else symbol
    price_str = f"${price:.2f}" if isinstance(price, (int, float)) else "unknown"

    try:
        client = _get_perplexity_client()
        if client:
            result = _forward_catalyst_agent_api(client, base, label, price_str, symbol)
        else:
            result = _forward_catalyst_chat_api(base, label, price_str, symbol)

        parsed = _parse_json_response(result)
        detected = parsed.get("spinoff_detected", False)

        return {
            **base,
            "detected": detected,
            "event_name": parsed.get("event_name") if detected else None,
            "expected_window": parsed.get("expected_window") or parsed.get("event_date") if detected else None,
            "strategic_summary": parsed.get("strategic_summary") if detected else None,
            "source_url": parsed.get("source_url") if detected else None,
            "confidence_score": parsed.get("confidence") if detected else None,
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("tier1 spinoff catalyst failed for %s: %s", symbol, redact(str(exc)))
        return {**base, "error": f"fetch_failed: {type(exc).__name__}"}
