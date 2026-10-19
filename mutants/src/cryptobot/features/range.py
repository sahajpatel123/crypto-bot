"""Range/VWAP primitives for S3 (Worker 1, Q-004). Pure + causal.

All functions read only indices ``<= t``. VWAP uses typical price
``(high+low+close)/3`` weighted by bar volume over an explicit trailing
window; touches count edge approaches inside a tolerance band.
"""
from __future__ import annotations

from .breakout import _window

__all__ = ["edge_touches", "vwap_typical"]


def vwap_typical(
    highs: list[float | None] | tuple[float | None, ...],
    lows: list[float | None] | tuple[float | None, ...],
    closes: list[float | None] | tuple[float | None, ...],
    volumes: list[float | None] | tuple[float | None, ...],
    t: int,
    n: int = 60,
) -> float | None:
    """Typical-price VWAP over bars ``t-n..t-1``; None on zero volume."""
    h = _window(highs, t - n, t, "vwap_typical")
    low = _window(lows, t - n, t, "vwap_typical")
    c = _window(closes, t - n, t, "vwap_typical")
    v = _window(volumes, t - n, t, "vwap_typical")
    for x in v:
        if x < 0:
            raise ValueError("vwap_typical: negative volume")
    total = sum(v)
    if total <= 0:
        return None
    return sum((hi + li + ci) / 3 * vi for hi, li, ci, vi in zip(h, low, c, v)) / total


def edge_touches(
    extremes: list[float | None] | tuple[float | None, ...],
    level: float,
    t: int,
    m: int = 60,
    tol_bps: float = 4.0,
    *,
    edge: str = "low",
) -> int:
    """Count bars in ``[t-m, t)`` within ``tol_bps`` of ``level``.

    ``edge="low"`` counts values at/above the low edge
    (``(v-level)/level``); ``edge="high"`` counts values at/below the high
    edge (``(level-v)/level``). Pass lows for low edges, highs for high.
    """
    if level <= 0:
        raise ValueError("edge_touches: nonpositive level")
    if edge not in ("low", "high"):
        raise ValueError("edge_touches: edge must be 'low' or 'high'")
    window = _window(extremes, t - m, t, "edge_touches")
    if edge == "low":
        return sum(1 for v in window if (v - level) / level * 1e4 <= tol_bps)
    return sum(1 for v in window if (level - v) / level * 1e4 <= tol_bps)
