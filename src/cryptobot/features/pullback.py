"""Trend/pullback/resumption primitives for S2 (Worker 1, Q-002).

Pure causal functions in the style of ``breakout.py``: every function reads
only indices ``<= t``. Windows ending at ``t-1`` describe the setup (known
before the trigger bar); the trigger bar's own close drives resumption.
"""
from __future__ import annotations

from .breakout import _window

__all__ = [
    "pullback_high",
    "pullback_low",
    "resume_max",
    "resume_min",
    "swing_high_before",
    "swing_low_before",
]


def swing_high_before(
    highs: list[float | None] | tuple[float | None, ...],
    t: int,
    n: int = 60,
) -> tuple[float, int]:
    """``(level, first_index)`` of max high over bars ``t-n..t-1``."""
    window = _window(highs, t - n, t, "swing_high_before")
    level = max(window)
    return level, (t - n) + window.index(level)


def swing_low_before(
    lows: list[float | None] | tuple[float | None, ...],
    t: int,
    n: int = 60,
) -> tuple[float, int]:
    """``(level, first_index)`` of min low over bars ``t-n..t-1``."""
    window = _window(lows, t - n, t, "swing_low_before")
    level = min(window)
    return level, (t - n) + window.index(level)


def pullback_low(
    lows: list[float | None] | tuple[float | None, ...],
    t: int,
    m: int = 10,
) -> float:
    """Min low over the pullback window ending at ``t`` (inclusive)."""
    return min(_window(lows, t - m + 1, t + 1, "pullback_low"))


def pullback_high(
    highs: list[float | None] | tuple[float | None, ...],
    t: int,
    m: int = 10,
) -> float:
    """Max high over the pullback window ending at ``t`` (inclusive)."""
    return max(_window(highs, t - m + 1, t + 1, "pullback_high"))


def resume_max(
    closes: list[float | None] | tuple[float | None, ...],
    t: int,
    k: int = 5,
) -> float:
    """Max close over bars ``t-k..t-1`` (resumption reference)."""
    return max(_window(closes, t - k, t, "resume_max"))


def resume_min(
    closes: list[float | None] | tuple[float | None, ...],
    t: int,
    k: int = 5,
) -> float:
    """Min close over bars ``t-k..t-1`` (resumption reference)."""
    return min(_window(closes, t - k, t, "resume_min"))
