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


def find_spike(closes: np.ndarray, dates: np.ndarray, start: date, end: date) -> dict | None:
    """Return the single largest consecutive-bar close ratio inside [start, end].

    Returns None if the window has < 2 bars or the prior close is non-positive.
    """
    if len(closes) < 2 or len(dates) != len(closes):
        return None
    date_objs = np.array([_to_date(d) for d in dates])
    mask = (date_objs >= start) & (date_objs <= end)
    idx = np.flatnonzero(mask)
    if len(idx) < 2:
        return None
    lo, hi = int(idx[0]), int(idx[-1])
    seg_closes = closes[lo : hi + 1]
    seg_dates = date_objs[lo : hi + 1]
    prior = seg_closes[:-1]
    curr = seg_closes[1:]
    safe = prior > 0
    if not safe.any():
        return None
    ratios = np.where(safe, curr / np.where(safe, prior, 1.0), 0.0)
    best = int(np.argmax(ratios))
    return {
        "date": seg_dates[best + 1].isoformat(),
        "prior_date": seg_dates[best].isoformat(),
        "prior_close": float(prior[best]),
        "close": float(curr[best]),
        "single_day_multiplier": float(ratios[best]),
    }


def _to_date(value) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, np.datetime64):
        return value.astype("datetime64[D]").astype(date)
    return value.date() if hasattr(value, "date") else value


@dataclass
class Winner:
    """A 'steep, sustained rise' event used by Part 1 of the redesign.

    Definition: within a short window (`max_days` consecutive bars at most), price
    rose by `min_multiplier`+. The post-peak retention rule confirms the new level
    held (close at peak + N bars retained `post_peak_retention_min` of the peak).
    The breakout rule rejects pure crash-then-recovery rebounds.
    """
    symbol: str
    start_ts: date
    end_ts: date
    days_to_peak: int
    trough_price: float
    peak_price: float
    multiplier: float
    post_peak_retention: float | None
    breakout_ratio: float | None
    status: str  # 'held' | 'faded'


def detect_winners(
    symbol: str,
    closes: np.ndarray,
    dates: np.ndarray,
    *,
    min_multiplier: float = 5.0,
    max_multiplier: float = 50.0,
    max_days: int = 7,
    post_peak_retention_min: float = 0.70,
    breakout_vs_prior_high_min: float = 1.5,
    pre_trough_lookback_days: int = 180,
    post_peak_lookback_days: int = 30,
    min_bars: int = 400,
    max_trough_price: float = 50.0,
) -> list[Winner]:
    """Find every (start, peak) where price rose >= `min_multiplier` in <= `max_days`
    consecutive bars, the peak then held >= `post_peak_retention_min` for
    `post_peak_lookback_days`, and the peak was >= `breakout_vs_prior_high_min` x
    the max close in the `pre_trough_lookback_days` before the trough.

    Greedy scan: for each bar i, look back up to `max_days` bars and check the
    trough->i window. After accepting a window, skip past `i` so we don't double
    count overlapping events for the same symbol.

    Data-quality guards: a symbol with fewer than `min_bars` bars trades too
    sporadically to trust (stale prints fabricate huge ratios), and any single
    move above `max_multiplier` is treated as a bad print rather than a real
    move — both are skipped. A 3y daily series has ~750 bars; 400 keeps names
    that trade most days while dropping illiquid OTC-style tickers.

    Retail-accessibility: only show moves that started <=$max_trough_price
    (default $50). We want to find stocks that crossed the $50 threshold:
    - $12 -> $65 ✓ (started <$50, ended >$50 - crossed threshold)
    - $8 -> $45 ✓ (started <$50, stayed <$50 - accessible throughout)
    - $60 -> $100 ✗ (started >$50 - expensive entry point)
    """
    n = len(closes)
    if n < 2 or len(dates) != n:
        return []
    if n < min_bars:
        return []
    date_objs = np.array([_to_date(d) for d in dates])
    winners: list[Winner] = []
    i = 1
    while i < n:
        # Search the last `max_days` bars for the best trough->i ratio.
        lo_search = max(0, i - max_days)
        window = closes[lo_search : i + 1]
        if window.max() != closes[i] or closes[i] <= 0:
            i += 1
            continue
        trough_off = int(np.argmin(window))
        trough_idx = lo_search + trough_off
        if trough_idx >= i:
            i += 1
            continue
        trough = float(closes[trough_idx])
        peak = float(closes[i])
        if trough <= 0 or peak / trough < min_multiplier:
            i += 1
            continue
        # Reject implausible ratios: a >50x move in <=7 bars is a stale/erroneous
        # price print, not a real rally.
        if peak / trough > max_multiplier:
            i += 1
            continue
        # Retail-accessible: only show moves that started at a price <=$50.
        if trough > max_trough_price:
            i += 1
            continue

        # Breakout vs prior-high (180d before trough).
        trough_date = date_objs[trough_idx]
        cutoff = trough_date - timedelta(days=pre_trough_lookback_days)
        pre_mask = (date_objs >= cutoff) & (date_objs < trough_date)
        if pre_mask.any():
            pre_high = float(closes[pre_mask].max())
            breakout = peak / pre_high if pre_high > 0 else None
        else:
            pre_high = None  # newly listed - allow
            breakout = None
        if breakout is not None and breakout < breakout_vs_prior_high_min:
            i += 1
            continue

        # Post-peak retention: look at the close `post_peak_lookback_days` calendar
        # days after the peak. If we don't have that data yet, mark as 'held' only
        # if the most recent close is still above the threshold.
        peak_date = date_objs[i]
        post_target = peak_date + timedelta(days=post_peak_lookback_days)
        post_mask = (date_objs > peak_date) & (date_objs <= post_target)
        if post_mask.any():
            post_close = float(closes[post_mask][-1])
        elif i + 1 < n:
            post_close = float(closes[-1])  # use the latest available bar
        else:
            post_close = peak
        retention = post_close / peak if peak > 0 else None
        status = "held" if retention is not None and retention >= post_peak_retention_min else "faded"
        # Filter out 'faded': we only report sustained moves per the spec.
        if status != "held":
            i += 1
            continue

        winners.append(
            Winner(
                symbol=symbol,
                start_ts=trough_date,
                end_ts=peak_date,
                days_to_peak=int(i - trough_idx),
                trough_price=trough,
                peak_price=peak,
                multiplier=peak / trough,
                post_peak_retention=retention,
                breakout_ratio=breakout,
                status=status,
            )
        )
        # Skip past this winner's peak to avoid double-counting overlapping windows.
        i = i + post_peak_lookback_days + 1
    return winners
