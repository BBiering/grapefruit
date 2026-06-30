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
    # price OK, but only $100k daily dollar-volume
    assert not screening.passes_hard_filter(20.0, 100_000.0)


def test_hard_filter_rejects_none():
    assert not screening.passes_hard_filter(None, 5_000_000.0)
    assert not screening.passes_hard_filter(20.0, None)


def test_hard_filter_edges_inclusive():
    assert screening.passes_hard_filter(1.0, 1_000_000.0)
    assert screening.passes_hard_filter(50.0, 1_000_000.0)


# ---------- momentum_180d ----------

def test_momentum_180d_doubling_over_200_days():
    # 200 calendar days, price linear 10 -> 20. The bar ~180d before the last is
    # the baseline; momentum is (last/base - 1), clearly positive and < 1.0.
    n = 200
    closes = np.linspace(10.0, 20.0, n)
    m = screening.momentum_180d(closes, _dates(n))
    assert m is not None and m > 0


def test_momentum_180d_currency_independent():
    # Same shape scaled by 100 (e.g. pence vs pounds) -> identical momentum.
    n = 200
    a = np.linspace(10.0, 20.0, n)
    b = a * 100.0
    da, db = _dates(n), _dates(n)
    assert abs(screening.momentum_180d(a, da) - screening.momentum_180d(b, db)) < 1e-9


def test_momentum_180d_too_short():
    closes = np.array([10.0, 11.0])
    assert screening.momentum_180d(closes, _dates(2)) is None


# ---------- quality_score ----------

def test_quality_neutral_when_missing():
    assert screening.quality_score(None, None) == screening.NEUTRAL


def test_quality_rewards_profit_penalizes_loss():
    assert screening.quality_score(1e9, 0.2) > screening.NEUTRAL
    assert screening.quality_score(-1e9, -0.1) < screening.NEUTRAL


# ---------- insider_score ----------

def test_insider_neutral_when_empty():
    assert screening.insider_score([]) == screening.NEUTRAL


def test_insider_rewards_net_buying():
    txns = [{"transactionAcquiredDisposed": "A", "transactionValue": 2_000_000}]
    assert screening.insider_score(txns) > screening.NEUTRAL


def test_insider_penalizes_net_selling():
    txns = [{"transactionAcquiredDisposed": "D", "transactionValue": 2_000_000}]
    assert screening.insider_score(txns) < screening.NEUTRAL


# ---------- combined_score ----------

def test_combined_score_weighting():
    # All-100 inputs -> 100; all-0 -> 0; default weights sum to 1.
    assert abs(screening.combined_score(100.0, 100.0, 100.0) - 100.0) < 1e-9
    assert abs(screening.combined_score(0.0, 0.0, 0.0)) < 1e-9


def test_combined_score_momentum_dominant():
    # Momentum has the highest weight (0.5), so a high momentum pulls the blend up.
    high_mom = screening.combined_score(100.0, 50.0, 50.0)
    low_mom = screening.combined_score(0.0, 50.0, 50.0)
    assert high_mom > low_mom
