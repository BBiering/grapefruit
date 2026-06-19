from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from grapefruit.storage import _cur


@dataclass
class CandidateParams:
    lookback_days: int = 20
    gain_pct: float = 1.0  # 1.0 = require 2x
    vol_mult: float = 2.0
    high_lookback: int = 60


def scan_candidates(p: CandidateParams, limit: int = 100) -> list[dict]:
    """
    Heuristic scan of cached bars. Pulls the last ~250 trading days for every
    symbol that has data, then filters by:
      - new N-day closing high
      - >= (1 + gain_pct) over lookback_days
      - 20d volume mean >= vol_mult * 60d volume mean
      - close > SMA50 > SMA200 (uptrend)
    Returns top `limit` rows scored by gain * log(vol_ratio).
    """
    today = date.today()
    cutoff = today - timedelta(days=400)
    with _cur() as cur:
        cur.execute(
            """
            SELECT symbol, ts, close, volume
            FROM bars
            WHERE ts >= %s
            ORDER BY symbol, ts
            """,
            [cutoff],
        )
        rows = cur.fetchall()
    if not rows:
        return []
    df = pd.DataFrame(rows, columns=["symbol", "ts", "close", "volume"])

    out: list[dict] = []
    for symbol, g in df.groupby("symbol", sort=False):
        if len(g) < max(p.high_lookback, 200, p.lookback_days + 1):
            continue
        closes = g["close"].to_numpy()
        volumes = g["volume"].to_numpy(dtype=float)
        last_close = closes[-1]
        if last_close <= 0:
            continue

        high_window = closes[-p.high_lookback :]
        if last_close < high_window.max():
            continue

        prev_close = closes[-(p.lookback_days + 1)]
        if prev_close <= 0:
            continue
        gain = last_close / prev_close - 1.0
        if gain < p.gain_pct:
            continue

        vol_recent = volumes[-20:].mean()
        vol_base = volumes[-60:].mean()
        if vol_base <= 0:
            continue
        vol_ratio = vol_recent / vol_base
        if vol_ratio < p.vol_mult:
            continue

        sma50 = closes[-50:].mean()
        sma200 = closes[-200:].mean()
        if not (last_close > sma50 > sma200):
            continue

        score = gain * float(np.log(max(vol_ratio, 1.0001)))
        out.append(
            {
                "symbol": symbol,
                "close": float(last_close),
                "gain": float(gain),
                "vol_ratio": float(vol_ratio),
                "sma50": float(sma50),
                "sma200": float(sma200),
                "score": float(score),
                "as_of": pd.to_datetime(g["ts"].iloc[-1]).date().isoformat(),
            }
        )

    out.sort(key=lambda r: r["score"], reverse=True)
    return out[:limit]
