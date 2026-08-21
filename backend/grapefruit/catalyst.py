"""Perplexity-backed catalyst analysis.

Two-step flow (Perplexity Search API + Sonar chat):
1. `/search` returns ranked web results as structured JSON (title, url,
   snippet, date) — cheap, per-request pricing, no token charges.
2. A Sonar chat completion extracts a structured catalyst report from those
   results, so `source_url` is grounded in real results, not hallucinated.

Also provides `explain_move` for past step changes, using the Agent API with
finance_search, web_search, and fetch_url for grounded historical explanations.
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

_SEARCH_URL = "https://api.perplexity.ai/search"
_MODEL = "agent-low"
_FORWARD_MODEL = "agent-fast"  # extraction from already-retrieved search results
_MAX_RETRIES = 3
_MAX_RETRY_SLEEP = 60.0

_perplexity_client = None
def _get_perplexity_client():
    """Create the Agent API client lazily so imports stay cheap for tests."""
    global _perplexity_client
    if _perplexity_client is None:
        from perplexity import Perplexity
        _perplexity_client = Perplexity(api_key=settings.perplexity_api_key)
    return _perplexity_client


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
    # Biotech-specific: focus on clinical trials and drug-approval milestones in
    # France/EU (EMA/CHMP, ANSM) and the US (FDA). Country-specific news plus
    # regulatory announcements drive these moves; ordinary earnings rarely do.
    query = (
        f"{label} biotech upcoming catalyst events next 3 months: "
        f"EMA CHMP opinion dates, European Commission decisions, Phase 2b/3 topline "
        f"readouts, FDA PDUFA target dates, FDA advisory committee votes, MAA/NDA "
        f"submissions, clinical trial data presentations. Exclude routine quarterly earnings. "
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
        "You are an institutional biotech research analyst. Based ONLY on the web "
        "search results below, identify SPECIFIC upcoming catalyst events in the "
        "next 3 months for this biotech stock "
        f"'{label}' (sector: {sector_str}, price ~{price_str}).\n\n"
        "Focus on scheduled, dateable drug-development catalysts that are often "
        "predictable in advance and can drive structural repricing: EMA CHMP opinion "
        "dates, European Commission decisions, Phase 2b/3 topline readouts, FDA PDUFA "
        "target dates, FDA advisory committee (AdCom) votes, MAA/NDA submissions, and "
        "clinical conference data presentations. EXCLUDE routine quarterly earnings, "
        "dividends, stock splits, and other non-drug catalysts. Ignore historical news.\n\n"
        "Search results:\n"
        f"{context}\n\n"
        "Return a JSON object with exactly these keys:\n"
        "{\n"
        '  "catalyst_detected": true or false,\n'
        '  "event_name": "specific event name or empty string",\n'
        '  "event_date": "YYYY-MM-DD or empty if not known",\n'
        '  "impact_type": "FDA Decision | EMA Decision | Phase 2 Readout | Phase 3 Readout | Conference Data | Drug Approval | Other",\n'
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

    The Agent API can combine the known price window with finance/search tools
    to find filings, transcripts, and contemporaneous news. Pure function —
    the caller persists.
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

    try:
        parsed, response = _agent_json(
            user_msg,
            preset="low",
            instructions=(
                "Use finance_search first for filings, earnings transcripts, company "
                "financials, and structured market data. Use web_search and fetch_url "
                "to verify the relevant announcement. Return only the requested JSON."
            ),
            tools=[
                {"type": "finance_search"},
                {"type": "web_search"},
                {"type": "fetch_url"},
            ],
            schema={
                "type": "object",
                "properties": {
                    "headline": {"type": "string"},
                    "summary": {"type": "string"},
                    "spike_explanation": {"type": "string"},
                    "was_foreseeable": {"type": ["boolean", "null"]},
                    "foreseeable_evidence": {"type": "string"},
                },
                "required": [
                    "headline", "summary", "spike_explanation",
                    "was_foreseeable", "foreseeable_evidence",
                ],
                "additionalProperties": False,
            },
        )
        raw = _response_text(response)
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
            "citations": _extract_urls(response),
        }
        if not result["summary"] and raw:
            result["summary"] = raw
        return result
    except Exception as exc:  # noqa: BLE001
        log.warning("perplexity Agent API failed for %s: %s", symbol, redact(str(exc)))
        return {**base, "error": f"agent_failed: {type(exc).__name__}"}


# ---------------------------------------------------------------------------
# low-level HTTP helpers
# ---------------------------------------------------------------------------

def _query_json(user_msg: str) -> dict:
    """Agent API extraction from already-retrieved Search API results."""
    parsed, _ = _agent_json(
        user_msg,
        preset="fast",
        instructions="Return only the JSON object requested by the user.",
    )
    return parsed


def _agent_json(
    user_msg: str,
    *,
    preset: str,
    instructions: str,
    tools: list[dict] | None = None,
    schema: dict | None = None,
):
    """Call Agent API and parse its output as JSON."""
    PERPLEXITY_BUCKET.acquire()
    kwargs = {
        "preset": preset,
        "input": user_msg,
        "instructions": instructions,
        "tools": tools or [],
        "max_steps": 5,
    }
    if schema:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "catalyst_report",
                "schema": schema,
                "strict": True,
            },
        }
    response = _get_perplexity_client().responses.create(**kwargs)
    return _parse_json_response(_response_text(response)), response


def _response_text(response) -> str:
    """Read Agent API message text without relying on SDK output_text.

    The SDK can expose tool output items with ``content=None``; its convenience
    property currently assumes every output item has iterable content.
    """
    if response is None:
        return ""
    texts: list[str] = []
    for item in getattr(response, "output", []) or []:
        for part in getattr(item, "content", None) or []:
            text = getattr(part, "text", None)
            if isinstance(text, str):
                texts.append(text)
    return "".join(texts)


def _extract_urls(response) -> list[str]:
    """Extract source URLs from Agent API output items for persistence."""
    if response is None:
        return []
    try:
        data = response.model_dump(warnings=False)
    except Exception:  # noqa: BLE001
        return []
    urls: list[str] = []

    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"url", "source_url"} and isinstance(item, str):
                    if item.startswith(("http://", "https://")) and item not in urls:
                        urls.append(item)
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(data)
    return urls[:20]


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
