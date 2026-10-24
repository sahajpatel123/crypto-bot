"""h2_trades_fast must equal the preregistered h2_trades exactly."""
from __future__ import annotations

import random

from cryptobot.research.h_eval import Bar, h2_trades, h2_trades_fast


def _walk(n: int, seed: int) -> list[Bar]:
    rng = random.Random(seed)
    px, bars = 100.0, []
    for k in range(n):
        vol = 0.002 if (k // 300) % 2 else 0.012  # alternating regimes
        o = px
        c = max(1.0, o * (1 + rng.gauss(0.0003, vol)))
        hi = max(o, c) * (1 + abs(rng.gauss(0, vol / 2)))
        lo = min(o, c) * (1 - abs(rng.gauss(0, vol / 2)))
        bars.append(Bar(ts_ms=k * 3_600_000, open=o, high=hi, low=lo, close=c))
        px = c
    return bars


def test_fast_equals_reference():
    for seed in (1, 2, 3):
        bars = _walk(2500, seed)
        ref = h2_trades(bars)
        assert ref, "fixture must produce trades"
        assert h2_trades_fast(bars) == ref
