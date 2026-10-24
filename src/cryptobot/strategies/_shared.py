"""Shared strategy-side helpers (Worker 1): bar columns + gap scan.

Used by the S1/S2 baselines (and future strategies) so window extraction
and missing-data semantics stay identical across strategies.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .s1 import Bar

__all__ = ["columns", "gap_scan"]


def columns(bars: list[Bar | None]) -> dict[str, list[float | None]]:
    """Numeric columns over the full bar list (None preserved for gaps)."""
    return {
        "high": [b.high if b else None for b in bars],
        "low": [b.low if b else None for b in bars],
        "close": [b.close if b else None for b in bars],
        "volume": [b.volume if b else None for b in bars],
        "buy_frac": [b.buy_frac if b else None for b in bars],
    }


def gap_scan(
    bars: list[Bar | None], lo: int, hi: int
) -> tuple[bool, int, bool]:
    """Return (gap_found, max_consecutive_missing, ts_disorder) over [lo:hi]."""
    max_consec = 0
    run = 0
    gap = False
    prev_ts: datetime | None = None
    disorder = False
    for b in bars[lo:hi]:
        if b is None:
            gap = True
            run += 1
            max_consec = max(max_consec, run)
            prev_ts = None
            continue
        run = 0
        if prev_ts is not None and b.ts_utc - prev_ts != timedelta(seconds=1):
            disorder = True
        prev_ts = b.ts_utc
    return gap, max_consec, disorder
