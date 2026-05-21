from collections import deque
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np


MAX_GAP_DAYS = 10  # calendar days; larger gaps split the series into separate runs.


@dataclass
class Hit:
    symbol: str
    start_ts: date
    end_ts: date
    trough_price: float
    peak_price: float
    multiplier: float


def detect_hits(
    symbol: str,
    closes: np.ndarray,
    dates: np.ndarray,
    window: int,
    threshold: float = 10.0,
    max_gap_days: int = MAX_GAP_DAYS,
) -> list[Hit]:
    """
    Find non-overlapping clusters of qualifying sliding-windows where
    max(close)/min(close) >= threshold and the max occurs after the min.

    The series is first split into contiguous runs at any consecutive-bar
    calendar gap greater than ``max_gap_days``, so windows can't span gaps
    that would inflate the multiplier across unrelated periods.
    """
    if window <= 1 or len(closes) < window:
        return []
    hits: list[Hit] = []
    for run_lo, run_hi in _runs(dates, max_gap_days):
        if run_hi - run_lo + 1 < window:
            continue
        hits.extend(
            _detect_in_run(
                symbol,
                closes[run_lo : run_hi + 1],
                dates[run_lo : run_hi + 1],
                window,
                threshold,
            )
        )
    return hits


def _runs(dates: np.ndarray, max_gap_days: int) -> list[tuple[int, int]]:
    """Return [(lo, hi)] inclusive index ranges, split at gaps > max_gap_days."""
    n = len(dates)
    if n == 0:
        return []
    gap = timedelta(days=max_gap_days)
    runs: list[tuple[int, int]] = []
    lo = 0
    for i in range(1, n):
        if _to_date(dates[i]) - _to_date(dates[i - 1]) > gap:
            runs.append((lo, i - 1))
            lo = i
    runs.append((lo, n - 1))
    return runs


def _detect_in_run(
    symbol: str,
    closes: np.ndarray,
    dates: np.ndarray,
    window: int,
    threshold: float,
) -> list[Hit]:
    n = len(closes)
    max_dq: deque[int] = deque()  # decreasing, front = window max index
    min_dq: deque[int] = deque()  # increasing, front = window min index

    qualifying: list[tuple[int, int]] = []  # (window_start, window_end) inclusive

    for i in range(n):
        while max_dq and closes[max_dq[-1]] <= closes[i]:
            max_dq.pop()
        max_dq.append(i)
        while min_dq and closes[min_dq[-1]] >= closes[i]:
            min_dq.pop()
        min_dq.append(i)

        lo = i - window + 1
        while max_dq and max_dq[0] < lo:
            max_dq.popleft()
        while min_dq and min_dq[0] < lo:
            min_dq.popleft()

        if i >= window - 1:
            max_idx = max_dq[0]
            min_idx = min_dq[0]
            if (
                max_idx > min_idx
                and closes[min_idx] > 0
                and closes[max_idx] / closes[min_idx] >= threshold
            ):
                qualifying.append((lo, i))

    if not qualifying:
        return []

    hits: list[Hit] = []
    cluster_lo, cluster_hi = qualifying[0]
    for ws, we in qualifying[1:]:
        if ws <= cluster_hi:
            cluster_hi = max(cluster_hi, we)
        else:
            hits.append(_cluster_to_hit(symbol, closes, dates, cluster_lo, cluster_hi))
            cluster_lo, cluster_hi = ws, we
    hits.append(_cluster_to_hit(symbol, closes, dates, cluster_lo, cluster_hi))
    return hits


def _cluster_to_hit(
    symbol: str,
    closes: np.ndarray,
    dates: np.ndarray,
    lo: int,
    hi: int,
) -> Hit:
    segment = closes[lo : hi + 1]
    peak_off = int(np.argmax(segment))
    # trough = min strictly before the peak inside the cluster
    pre_peak = segment[: peak_off + 1]
    trough_off = int(np.argmin(pre_peak))
    peak_idx = lo + peak_off
    trough_idx = lo + trough_off
    return Hit(
        symbol=symbol,
        start_ts=_to_date(dates[trough_idx]),
        end_ts=_to_date(dates[peak_idx]),
        trough_price=float(closes[trough_idx]),
        peak_price=float(closes[peak_idx]),
        multiplier=float(closes[peak_idx] / closes[trough_idx]),
    )


def _to_date(value) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, np.datetime64):
        return value.astype("datetime64[D]").astype(date)
    # pandas Timestamp
    return value.date() if hasattr(value, "date") else value
