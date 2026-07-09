"""Strategy alignment tagging for simplified quality + catalyst system.

Assigns each watchlist stock a tag based on alignment:
- Strategy A (Catalyst): forward_catalyst.detected = true
- Strategy B (Quality): quality_score >= 60 (profitable with margin)

Tagging rules:
- BUY MANUALLY: Quality + Catalyst (high confidence, actionable signal)
- WATCHLIST: Quality only (good fundamentals, waiting for catalyst)
- PASS: Low quality (< 60 score)
"""
from __future__ import annotations


QUALITY_THRESHOLD = 60   # quality_score >= 60 (profitable with healthy margin)


def compute_strategy_tag(
    quality_score: float | None,
    catalyst_detected: bool | None,
) -> str:
    """
    Compute strategy tag based on quality and catalyst alignment.

    Args:
        quality_score: 0-100 profitability score (60% weight) + insider activity (40% weight)
        catalyst_detected: True if forward catalyst detected

    Returns:
        "Buy Manually", "Watchlist", or "Pass"

    Logic:
        1. If Quality + Catalyst → BUY MANUALLY (best case: fundamentals + catalyst)
        2. If Quality only (no Catalyst yet) → WATCHLIST (good fundamentals, monitor)
        3. If Quality below threshold → PASS (risky fundamentals)
    """
    has_quality = quality_score is not None and quality_score >= QUALITY_THRESHOLD
    has_catalyst = catalyst_detected is True

    # Rule 1: Quality + Catalyst = BUY MANUALLY
    # Strong fundamentals + forward catalyst = high conviction signal
    if has_quality and has_catalyst:
        return "Buy Manually"

    # Rule 2: Quality only (no Catalyst yet) = WATCHLIST
    # Monitor for catalyst development or momentum emergence
    if has_quality:
        return "Watchlist"

    # Rule 3: Low quality = PASS
    # Weak fundamentals make catalyst plays too risky
    return "Pass"
