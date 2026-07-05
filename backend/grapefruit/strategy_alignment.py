"""Strategy alignment tagging for layered funnel system.

Assigns each watchlist stock a tag based on which strategies align:
- Strategy A (Momentum): momentum_score ≥ 70
- Strategy B (Catalyst): forward_catalyst.detected = true
- Strategy C (Quality): quality_score > 50 (profitable)

Tagging rules:
- BUY MANUALLY: Quality + Catalyst (C + B)
- WATCHLIST: Quality only (C), no Momentum yet
- PASS: All other cases (no quality alignment, or momentum without quality)
"""
from __future__ import annotations


MOMENTUM_THRESHOLD = 70  # momentum_score ≥ 70
QUALITY_THRESHOLD = 50   # quality_score > 50 (profitable)


def compute_strategy_tag(
    momentum_score: float | None,
    quality_score: float | None,
    catalyst_detected: bool | None,
) -> str:
    """
    Compute strategy tag based on alignment rules.

    Args:
        momentum_score: 0-100 percentile rank within watchlist
        quality_score: 0-100 profitability score
        catalyst_detected: True if forward catalyst detected

    Returns:
        "Buy Manually", "Watchlist", or "Pass"

    Logic:
        1. If Quality + Catalyst → BUY MANUALLY (best case)
        2. If Quality only (no Momentum) → WATCHLIST (wait for momentum)
        3. All other cases → PASS (including Momentum without Quality)
    """
    # Strategy flags
    has_momentum = momentum_score is not None and momentum_score >= MOMENTUM_THRESHOLD
    has_quality = quality_score is not None and quality_score > QUALITY_THRESHOLD
    has_catalyst = catalyst_detected is True

    # Rule 1: Quality + Catalyst = BUY MANUALLY
    # This is the holy grail: fundamentally safe company with positive catalyst
    # Momentum will likely follow, so buy before the trend-followers
    if has_quality and has_catalyst:
        return "Buy Manually"

    # Rule 2: Quality only (no Momentum yet) = WATCHLIST
    # Wait for momentum to develop before committing capital
    # Exception: if has catalyst, already caught by Rule 1
    if has_quality and not has_momentum:
        return "Watchlist"

    # Rule 3: All other cases = PASS
    # This includes:
    # - Momentum without Quality (toxic fundamentals, gap-down risk)
    # - Catalyst without Quality (risky speculation)
    # - No alignment at all
    return "Pass"
