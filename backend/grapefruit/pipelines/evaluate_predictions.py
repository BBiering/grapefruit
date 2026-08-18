"""Evaluate predicted catalysts after their expected dates pass.

This is a price-based review, not proof of causality: it compares the close
before the event with the best close in the next ten trading bars and records
whether the predicted direction/magnitude was broadly achieved.
"""
from __future__ import annotations

import logging
from datetime import date

from grapefruit import storage

log = logging.getLogger(__name__)


def classify_outcome(expected_pct: float | None, actual_pct: float) -> str:
    """Classify a prediction using a deliberately conservative threshold."""
    if expected_pct is None:
        return "unclear"
    threshold = max(5.0, abs(expected_pct) * 0.5)
    if expected_pct >= 0:
        if actual_pct >= threshold:
            return "occurred"
        if actual_pct < 0:
            return "missed"
        return "unclear"
    if actual_pct <= -threshold:
        return "occurred"
    if actual_pct > 0:
        return "missed"
    return "unclear"


def measure_reaction(symbol: str, event_date: date) -> tuple[float, str] | None:
    """Return (actual impact %, notes) or None if price data is insufficient."""
    bars = storage.load_symbol(symbol)
    if bars.empty:
        return None

    before = bars[bars["ts"] <= event_date]
    after = bars[bars["ts"] > event_date].head(10)
    if before.empty or len(after) < 3:
        return None

    baseline = float(before.iloc[-1]["close"])
    closes = [float(value) for value in after["close"] if value is not None]
    if baseline <= 0 or not closes:
        return None

    best = max(closes)
    actual_pct = (best / baseline - 1.0) * 100.0
    notes = (
        f"Compared close {baseline:.2f} on {before.iloc[-1]['ts']} with the "
        f"best close {best:.2f} in the next {len(closes)} trading bars."
    )
    return actual_pct, notes


def run(limit: int = 1000) -> int:
    pending = storage.load_pending_predictions(limit=limit)
    reviewed = 0
    for prediction in pending:
        try:
            event_date = date.fromisoformat(prediction["expected_window"])
        except (TypeError, ValueError):
            continue

        reaction = measure_reaction(prediction["symbol"], event_date)
        if reaction is None:
            continue

        actual_pct, notes = reaction
        outcome = classify_outcome(prediction.get("expected_impact_pct"), actual_pct)
        storage.update_prediction_outcome(
            prediction["id"],
            outcome=outcome,
            actual_impact_pct=actual_pct,
            notes=notes,
        )
        reviewed += 1

    log.info("evaluate_predictions reviewed %d/%d pending predictions", reviewed, len(pending))
    return reviewed
