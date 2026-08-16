from datetime import date, timedelta

import numpy as np

from grapefruit import screening


def _dates(n: int):
    start = date(2024, 1, 1)
    return np.array([start + timedelta(days=i) for i in range(n)])


# ---------- passes_hard_filter ----------

def test_hard_filter_accepts_liquid_midprice():
    assert screening.passes_hard_filter(20.0, 5_000_000.0)


def test_hard_filter_rejects_penny_stock():
    assert not screening.passes_hard_filter(0.50, 5_000_000.0)


def test_hard_filter_rejects_expensive():
    assert not screening.passes_hard_filter(75.0, 5_000_000.0)


def test_hard_filter_rejects_illiquid():
    assert not screening.passes_hard_filter(20.0, 100_000.0)


def test_hard_filter_rejects_none():
    assert not screening.passes_hard_filter(None, 5_000_000.0)
    assert not screening.passes_hard_filter(20.0, None)


def test_hard_filter_edges_inclusive():
    assert screening.passes_hard_filter(1.0, 1_000_000.0)
    assert screening.passes_hard_filter(50.0, 1_000_000.0)


# ---------- quality_score ----------

def test_quality_neutral_when_missing():
    assert screening.quality_score(None, None) == screening.NEUTRAL


def test_quality_rewards_profit_penalizes_loss():
    assert screening.quality_score(1e9, 0.2) > screening.NEUTRAL
    assert screening.quality_score(-1e9, -0.1) < screening.NEUTRAL
