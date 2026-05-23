"""Shared rate limiters for outbound API calls."""
from __future__ import annotations

import re
import time


class TokenBucket:
    """Simple sliding-window per-minute rate limiter."""

    def __init__(self, per_min: int):
        self.per_min = per_min
        self.timestamps: list[float] = []

    def acquire(self) -> None:
        now = time.monotonic()
        self.timestamps = [t for t in self.timestamps if now - t < 60.0]
        if len(self.timestamps) >= self.per_min:
            sleep_for = 60.0 - (now - self.timestamps[0]) + 0.05
            if sleep_for > 0:
                time.sleep(sleep_for)
            now = time.monotonic()
            self.timestamps = [t for t in self.timestamps if now - t < 60.0]
        self.timestamps.append(now)


# Finnhub free tier is 60/min. Stay a touch below.
FINNHUB_BUCKET = TokenBucket(per_min=55)
# Perplexity sonar tiers vary; 40/min keeps us under free + low-tier paid limits.
PERPLEXITY_BUCKET = TokenBucket(per_min=40)


_TOKEN_RE = re.compile(r"(token|api[_-]?key|authorization)=[^&\s\"'<>]+", re.IGNORECASE)


def redact(text: str) -> str:
    """Strip API tokens from a string so it's safe to log."""
    return _TOKEN_RE.sub(r"\1=REDACTED", text)
