"""Causal numeric features for S1 (Worker 1, Q-001).

Pure functions over explicit sequences plus an evaluation index ``t``.
Every function reads only indices ``<= t`` (reference windows exclude ``t``),
so causality holds by construction: perturbing any index ``> t`` cannot
change the result at ``t``. No randomness, no hidden state.
"""
from __future__ import annotations

import math
from statistics import mean, pstdev
from typing import Sequence

STD_FLOOR = 1e-9

__all__ = [
    "STD_FLOOR",
    "InsufficientHistory",
    "MissingData",
    "flow_mean",
    "momentum_bps",
    "ref_high",
    "ref_low",
    "swing_high",
    "swing_low",
    "volume_z",
]


class InsufficientHistory(ValueError):
    """Raised when the window reaches before index 0 or past the data."""


class MissingData(ValueError):
    """Raised when a window cell is None (explicit missing bar)."""

    def __init__(self, index: int) -> None:
        super().__init__(f"missing data at index {index}")
        self.index = index


def _window(
    values: Sequence[float | None], lo: int, hi: int, name: str
) -> list[float]:
    """Return values[lo:hi] after bounds/None/finite checks (hi exclusive)."""
    if lo < 0 or hi > len(values) or lo >= hi:
        raise InsufficientHistory(f"{name}: need [{lo}:{hi}] of len {len(values)}")
    out: list[float] = []
    for i in range(lo, hi):
        v = values[i]
        if v is None:
            raise MissingData(i)
        if not math.isfinite(v):
            raise ValueError(f"{name}: non-finite value at index {i}")
        out.append(v)
    return out


def _single(values: Sequence[float | None], t: int, name: str) -> float:
    return _window(values, t, t + 1, name)[0]


def ref_high(highs: Sequence[float | None], t: int, n: int = 120) -> float:
    """Max high over bars ``t-n..t-1`` (trigger bar excluded)."""
    return max(_window(highs, t - n, t, "ref_high"))


def ref_low(lows: Sequence[float | None], t: int, n: int = 120) -> float:
    """Min low over bars ``t-n..t-1`` (trigger bar excluded)."""
    return min(_window(lows, t - n, t, "ref_low"))


def swing_high(highs: Sequence[float | None], t: int, m: int = 30) -> float:
    """Max high over bars ``t-m..t-1`` (SHORT invalidation level)."""
    return max(_window(highs, t - m, t, "swing_high"))


def swing_low(lows: Sequence[float | None], t: int, m: int = 30) -> float:
    """Min low over bars ``t-m..t-1`` (LONG invalidation level)."""
    return min(_window(lows, t - m, t, "swing_low"))


def momentum_bps(closes: Sequence[float | None], t: int, m: int = 30) -> float:
    """``(close[t]/close[t-m] - 1)`` in basis points."""
    c_t = _single(closes, t, "momentum_bps")
    c_m = _single(closes, t - m, "momentum_bps")
    if c_m <= 0:
        raise ValueError("momentum_bps: non-positive base price")
    return (c_t / c_m - 1.0) * 1e4


def volume_z(volumes: Sequence[float | None], t: int, v: int = 60) -> float:
    """Z-score of ``volumes[t]`` vs baseline ``volumes[t-v..t-1]``.

    Population std; flat-baseline rule: if ``std < 1e-9``, ``z = 0.0`` when
    the trigger volume is at/below the mean, else ``+inf``.
    """
    base = _window(volumes, t - v, t, "volume_z")
    v_t = _single(volumes, t, "volume_z")
    mu = mean(base)
    sd = pstdev(base)
    if sd < STD_FLOOR:
        return 0.0 if v_t <= mu else math.inf
    return (v_t - mu) / sd


def flow_mean(fracs: Sequence[float | None], t: int, f: int = 10) -> float:
    """Mean directional fraction over bars ``t-f+1..t`` (inclusive)."""
    window = _window(fracs, t - f + 1, t + 1, "flow_mean")
    for x in window:
        if not 0.0 <= x <= 1.0:
            raise ValueError("flow_mean: fraction outside [0, 1]")
    return mean(window)
