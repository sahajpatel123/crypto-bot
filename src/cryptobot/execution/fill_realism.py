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
class FillParams:
    """Calibrated adverse-fill parameters (F0.4c, replaces the fixed
    "one tick" rule as the model of record).

    adverse_bps is the expected adverse move between decision and fill:
    half-spread paid + depth walked + latency drift at measured p95
    feed age. Calibration path: `cryptobot calibrate` (F2.2) fits these
    from demo/paper fills and may only raise them automatically.
    The Nautilus FillModel can only express a 1-tick slip probability,
    so the paper engine maps adverse_bps onto that probability against
    a reference tick; the bps model here is the accounting truth.
    """

    spread_bps: float = 3.0
    depth_bps: float = 5.0
    latency_bps: float = 4.0

    @property
    def adverse_bps(self) -> float:
        return float(self.spread_bps + self.depth_bps + self.latency_bps)

    def slippage_prob(self, *, tick_bps_ref: float = 12.0) -> float:
        """Probability for a 1-tick-slip model to match adverse_bps."""
        if tick_bps_ref <= 0:
            raise ValueError("tick_bps_ref must be > 0")
        return max(0.0, min(1.0, self.adverse_bps / float(tick_bps_ref)))


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
