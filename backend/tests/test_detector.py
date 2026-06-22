from datetime import date, timedelta

import numpy as np

from grapefruit.detector import detect_hits, detect_winners, find_spike


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


def test_gap_in_dates_breaks_window():
    # 20 flat bars, then a 365-day gap, then a small in-segment rise that's
    # too short to be a 30-bar window on its own. A naive sliding window would
    # span the gap and report a fake 10x.
    flat = np.full(20, 1.0)
    rise = np.linspace(1.0, 12.0, 15)  # only 15 bars, < window=30
    closes = np.concatenate([flat, rise])
    first = [date(2020, 1, 1) + timedelta(days=i) for i in range(20)]
    gap_start = first[-1] + timedelta(days=365)
    second = [gap_start + timedelta(days=i) for i in range(15)]
    dates = np.array(first + second)
    hits = detect_hits("TEST", closes, dates, window=30, threshold=10.0)
    assert hits == []


def test_find_spike_picks_largest_overnight_move():
    closes = np.array([1.0, 1.0, 1.0, 1.0, 10.0, 11.0, 12.0, 12.0])
    dates = _dates(8)
    spike = find_spike(closes, dates, dates[0], dates[-1])
    assert spike is not None
    assert spike["single_day_multiplier"] == 10.0
    assert spike["date"] == dates[4].isoformat()
    assert spike["prior_close"] == 1.0
    assert spike["close"] == 10.0


def test_find_spike_window_too_short():
    closes = np.array([1.0])
    dates = _dates(1)
    assert find_spike(closes, dates, dates[0], dates[0]) is None


def test_find_spike_respects_window_bounds():
    # Biggest jump (1->10) is at index 4 but we restrict to [day5, day7] where
    # the moves are tiny.
    closes = np.array([1.0, 1.0, 1.0, 1.0, 10.0, 11.0, 12.0, 12.0])
    dates = _dates(8)
    spike = find_spike(closes, dates, dates[5], dates[7])
    assert spike is not None
    assert spike["single_day_multiplier"] < 1.5
    assert spike["date"] == dates[6].isoformat()


def test_two_separate_rises_in_separate_runs_both_detected():
    rise = np.linspace(1.0, 12.0, 30)
    closes = np.concatenate([rise, rise])
    first = [date(2020, 1, 1) + timedelta(days=i) for i in range(30)]
    gap_start = first[-1] + timedelta(days=365)
    second = [gap_start + timedelta(days=i) for i in range(30)]
    dates = np.array(first + second)
    hits = detect_hits("TEST", closes, dates, window=30, threshold=10.0)
    assert len(hits) == 2
    assert all(h.multiplier >= 10.0 for h in hits)
    assert hits[0].end_ts < hits[1].start_ts


# ---------- detect_winners (Part 1) ----------


def _calendar_dates(n: int, start_day: int = 1):
    """n consecutive *calendar* days, so post-peak windows of 30 days can be tested."""
    start = date(2024, 1, start_day)
    return np.array([start + timedelta(days=i) for i in range(n)])


def test_detect_winners_clean_breakout_passes():
    # 30 flat at $1, jumps 3-6-10 in 3 bars, holds at $10 for 30 days.
    closes = np.concatenate([np.full(30, 1.0), np.array([3.0, 6.0, 10.0]), np.full(30, 10.0)])
    dates = _calendar_dates(len(closes))
    winners = detect_winners("CLEAN", closes, dates)
    assert len(winners) == 1
    w = winners[0]
    assert w.multiplier >= 5.0
    assert w.status == "held"
    assert w.breakout_ratio is not None and w.breakout_ratio >= 1.5
    assert w.days_to_peak <= 7


def test_detect_winners_crash_then_recover_fails_breakout():
    # 30 at $10, crashes to $1 for 20, recovers to $10 -> peak < 1.5 x prior high.
    closes = np.concatenate(
        [np.full(30, 10.0), np.full(20, 1.0), np.array([3.0, 6.0, 10.0]), np.full(30, 10.0)]
    )
    dates = _calendar_dates(len(closes))
    winners = detect_winners("CRASH", closes, dates)
    assert winners == []


def test_detect_winners_faded_post_peak_is_dropped():
    # Same jump but post-peak collapses back to $3 -> retention 0.30 < 0.70.
    closes = np.concatenate([np.full(30, 1.0), np.array([3.0, 6.0, 10.0]), np.full(30, 3.0)])
    dates = _calendar_dates(len(closes))
    winners = detect_winners("FADED", closes, dates)
    assert winners == []


def test_detect_winners_gradual_rise_fails_max_days():
    # 1 -> 10 over 90 days; max_days=7 means no single 7-bar window achieves 5x.
    closes = np.linspace(1.0, 10.0, 90)
    dates = _calendar_dates(90)
    winners = detect_winners("SLOW", closes, dates)
    assert winners == []
