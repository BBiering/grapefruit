from datetime import date, timedelta

import numpy as np

from grapefruit.detector import detect_hits


def _dates(n: int):
    start = date(2020, 1, 1)
    return np.array([start + timedelta(days=i) for i in range(n)])


def test_linear_ramp_qualifies():
    closes = np.linspace(1.0, 12.0, 30)
    hits = detect_hits("TEST", closes, _dates(30), window=30, threshold=10.0)
    assert len(hits) == 1
    assert hits[0].multiplier >= 10.0
    assert hits[0].trough_price < hits[0].peak_price
    assert hits[0].start_ts < hits[0].end_ts


def test_flat_series_no_hit():
    closes = np.full(50, 5.0)
    hits = detect_hits("TEST", closes, _dates(50), window=30, threshold=10.0)
    assert hits == []


def test_short_burst_below_threshold():
    # 1 -> 5 -> 1 round trip; never hits 10x
    rise = np.linspace(1.0, 5.0, 30)
    fall = np.linspace(5.0, 1.0, 30)
    closes = np.concatenate([rise, fall])
    hits = detect_hits("TEST", closes, _dates(60), window=30, threshold=10.0)
    assert hits == []


def test_crash_then_recovery_does_not_hit():
    # Falls 10 -> 1 then back to 10. max/min within window can be 10x but
    # max_idx < min_idx for the falling part; the recovery alone is 10x with
    # max_idx > min_idx and SHOULD count. Verify that.
    fall = np.linspace(10.0, 1.0, 25)
    rise = np.linspace(1.0, 10.0, 25)
    closes = np.concatenate([fall, rise])
    hits = detect_hits("TEST", closes, _dates(50), window=25, threshold=10.0)
    assert len(hits) == 1
    assert hits[0].multiplier >= 10.0


def test_window_too_small_no_hit():
    closes = np.linspace(1.0, 12.0, 30)
    # window of 5 only covers ~1.0 -> 2.9, never 10x
    hits = detect_hits("TEST", closes, _dates(30), window=5, threshold=10.0)
    assert hits == []


def test_short_series_returns_empty():
    closes = np.array([1.0, 2.0, 3.0])
    hits = detect_hits("TEST", closes, _dates(3), window=30, threshold=10.0)
    assert hits == []


def test_overlapping_qualifying_windows_merge_to_one_cluster():
    # Exponential ramp so multiple overlapping 30-day windows qualify.
    closes = np.geomspace(1.0, 5000.0, 100)
    hits = detect_hits("TEST", closes, _dates(100), window=30, threshold=10.0)
    assert len(hits) == 1
    assert hits[0].multiplier >= 10.0
