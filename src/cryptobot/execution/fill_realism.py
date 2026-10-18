"""Pessimistic fill realism for paper/replay (T1.9).

Zero-slippage paper fills fabricate edge. This model walks the visible
book (worst covered level when depth is insufficient, plus an
empty-book penalty) and adds a latency penalty calibrated to measured
p95 feed age. It never improves a price: buys pay >= book VWAP, sells
receive <= book VWAP.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class PaperFillParameters:
    """Explicit adverse-fill model for paper/replay (F0.4c, F2.2).

    The old rule ("always slip exactly one tick") was unfalsifiable and
    ignored measured conditions. This model derives an expected adverse
    move in ticks from three measured inputs:

    * ``spread_bps`` — quoted spread at decision time (crossing cost);
    * ``depth_multiple`` — order qty / visible top-of-book qty (impact);
    * ``latency_ms`` — order-path latency, converted to drift with
      ``latency_drift_bps_per_s`` measured from the replay tape.

    ``floor_ticks`` keeps the model pessimistic when all measurements
    look benign (a fill is never better than one tick adverse), and
    ``cap_ticks`` bounds the paper simulator's one-tick Nautilus
    primitive. ``calibrate`` (F2.2) fits these parameters from recorded
    fills and may only make them MORE conservative automatically; a
    relaxation requires a fresh verdict run.
    """

    tick_size_bps: float = 1.0
    spread_bps: float = 2.0
    depth_multiple: float = 1.0
    latency_ms: float = 250.0
    latency_drift_bps_per_s: float = 2.0
    impact_bps_per_depth: float = 1.0
    floor_ticks: float = 1.0
    cap_ticks: float = 5.0

    def __post_init__(self) -> None:
        for name in ("tick_size_bps", "spread_bps", "latency_ms",
                     "latency_drift_bps_per_s", "impact_bps_per_depth",
                     "floor_ticks", "cap_ticks"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
            if value < 0:
                raise ValueError(f"{name} must be >= 0")
        if self.depth_multiple < 1.0:
            raise ValueError("depth_multiple must be >= 1 (order/visible)")
        if self.tick_size_bps <= 0:
            raise ValueError("tick_size_bps must be > 0")
        if self.cap_ticks < self.floor_ticks:
            raise ValueError("cap_ticks must be >= floor_ticks")

    @property
    def adverse_bps(self) -> float:
        """Expected adverse price move in bps (never below floor)."""
        half_spread = self.spread_bps / 2.0
        impact = (self.depth_multiple - 1.0) * self.impact_bps_per_depth
        drift = self.latency_ms / 1000.0 * self.latency_drift_bps_per_s
        raw_ticks = (half_spread + impact + drift) / self.tick_size_bps
        return max(self.floor_ticks, min(self.cap_ticks, raw_ticks)) \
            * self.tick_size_bps

    @property
    def expected_ticks(self) -> float:
        return self.adverse_bps / self.tick_size_bps

    @property
    def slippage_probability(self) -> float:
        """Probability parameter for the one-tick Nautilus fill model.

        The simulator applies at most one tick, so this saturates at
        1.0; the bps value above is what replay/paper accounting and any
        stress report must use. Keeping >=1.0 is the conservative rule.
        """
        return min(1.0, self.expected_ticks)


def pessimistic_fill_price(side: str, *, qty: float,
                           levels: list[tuple[float, float]],
                           latency_bps: float = 0.0,
                           empty_book_bps: float = 25.0) -> float:
    """Adverse book-walking fill price for ``qty`` against ``levels``.

    ``levels`` are (price, qty) in book order (best first). Uncovered
    remainder fills at the worst seen price plus ``empty_book_bps``.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if qty <= 0 or not math.isfinite(qty):
        raise ValueError("qty must be positive finite")
    if not levels:
        raise ValueError("levels must be non-empty (no book, no fill)")
    remaining = float(qty)
    cost = 0.0
    worst = float(levels[0][0])
    for price, avail in levels:
        if remaining <= 0:
            break
        take = min(remaining, float(avail))
        if take <= 0:
            continue
        cost += take * float(price)
        remaining -= take
        worst = float(price)
    if remaining > 0:
        penalty = 1.0 + empty_book_bps / 10000.0 if side == "BUY" \
            else 1.0 - empty_book_bps / 10000.0
        cost += remaining * worst * penalty
    vwap = cost / float(qty)
    latency = 1.0 + latency_bps / 10000.0 if side == "BUY" \
        else 1.0 - latency_bps / 10000.0
    return vwap * latency


def maker_fill(*, side: str, limit_price: float, qty: float,
               queue_ahead_qty: float,
               trades: list[tuple[float, float]]) -> float:
    """Conservative maker queue fill quantity (T5.2).

    ``trades`` are (price, qty) prints after placement. A print AT the
    limit only consumes queue ahead; a fill is credited solely for
    volume traded THROUGH the limit, or volume beyond the estimated
    queue once the queue is consumed. Touches earn nothing.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    ahead = float(queue_ahead_qty)
    filled = 0.0
    for price, tqty in trades:
        if filled >= qty:
            break
        through = (price < limit_price) if side == "BUY" \
            else (price > limit_price)
        at = price == limit_price
        if through:
            take = min(float(tqty), qty - filled)
            filled += take
        elif at:
            consume = min(float(tqty), ahead)
            ahead -= consume
            excess = float(tqty) - consume
            if excess > 0:
                filled += min(excess, qty - filled)
    return filled


def stressed_pnl(*, gross_pnl: float, costs_1x: float) -> dict[str, float]:
    """Report P&L at 1x and 2x costs (T1.9): 2x subtracts costs twice."""
    return {"gross": float(gross_pnl), "costs_1x": float(costs_1x),
            "pnl_1x": float(gross_pnl) - float(costs_1x),
            "pnl_2x": float(gross_pnl) - 2.0 * float(costs_1x)}
