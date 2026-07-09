"""Pure scoring functions for the look-ahead screener. No I/O — unit-testable.

Currency note: Only absolute thresholds (price band, dollar-volume) require USD
conversion, which the caller does before calling `passes_hard_filter`.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from grapefruit.detector import _to_date


NEUTRAL = 50.0  # 0–100 score used when an input dimension is unavailable.


def passes_hard_filter(
    usd_price: float | None,
    usd_dollar_volume: float | None,
    *,
    min_price: float = 1.0,
    max_price: float = 50.0,
    min_dollar_volume: float = 1_000_000.0,
) -> bool:
    """Liquidity + price-band gate. Inputs are already USD-converted.

    Rejects penny-stock noise (price < min_price), expensive names
    (price > max_price), and illiquid names (dollar-volume below the floor,
    so a manual entry/exit won't move the market).
    """
    if usd_price is None or usd_dollar_volume is None:
        return False
    if not (min_price <= usd_price <= max_price):
        return False
    return usd_dollar_volume >= min_dollar_volume


# Momentum calculation removed - no longer used in screening strategy


def quality_score(net_income: float | None, profit_margin: float | None) -> float:
    """0–100 from profitability. Neutral (50) when both inputs are missing.

    Positive net income and a healthy margin push the score up; losses pull it
    down. Deliberately coarse — it's a tilt, not a valuation model.
    """
    if net_income is None and profit_margin is None:
        return NEUTRAL
    score = NEUTRAL
    if net_income is not None:
        score += 20.0 if net_income > 0 else -20.0
    if profit_margin is not None:
        # profit_margin is a fraction (0.15 == 15%). Map [-0.2, +0.3] -> [-30, +30].
        score += float(np.clip(profit_margin, -0.2, 0.3) * 100.0)
    return float(np.clip(score, 0.0, 100.0))


def insider_score(transactions: list[dict]) -> float:
    """0–100 from net insider *buy* value. Neutral (50) when there's no data.

    EODHD insider rows have a `transactionAcquiredDisposed` ('A'/'D') and a
    `transactionValue`. Net positive (more acquired than disposed) tilts up.
    """
    if not transactions:
        return NEUTRAL
    net = 0.0
    saw_value = False
    for t in transactions:
        val = t.get("transactionValue") or t.get("value")
        if not isinstance(val, (int, float)):
            continue
        saw_value = True
        side = (t.get("transactionAcquiredDisposed") or t.get("ownership") or "").upper()
        net += float(val) if side.startswith("A") else -float(val)
    if not saw_value:
        return NEUTRAL
    if net > 0:
        return float(min(100.0, NEUTRAL + 30.0 + min(20.0, net / 1_000_000.0)))
    if net < 0:
        return float(max(0.0, NEUTRAL - 20.0))
    return NEUTRAL


def combined_score(
    quality: float,
    insider: float,
    *,
    w_q: float = 0.6,
    w_i: float = 0.4,
) -> float:
    """Weighted blend of two 0–100 components: quality (60%) and insider activity (40%).

    Momentum has been removed from the screening strategy."""
    total = w_q + w_i
    return (w_q * quality + w_i * insider) / total
