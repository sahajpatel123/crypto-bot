"""Planned-loss position sizing (Worker 3, V-004 / F-CEO-04 correction).

Budget: ``max_loss_budget_pct * reconciled_equity`` must cover the stop loss
plus stressed execution costs **at the adverse permitted fill price**
(LONG: entry_high; SHORT: entry_low). Quantity is computed qty-first from
that bound, rounded DOWN to the venue step (per-instrument filter when
configured, else 1e-8), then rechecked against budget, leverage, and minimum
notional. Rounding never rounds up to meet a minimum.

Under one-way, isolated, <=3x, required margin ``notional/3 <= equity`` is
the same inequality as the leverage cap, so leverage/margin/exposure collapse
to one check. True available-margin input awaits a v0.2.0 execution-side
addendum (proposed, not landed).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from cryptobot.coordination import Side

from .types import RiskConfig


class SizeRejected(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class SizePlan:
    notional_usdt: float
    qty: float
    reserved_risk: float
    stop_pct: float
    stressed_cost_pct: float
    adverse_price: float


def _finite(value: float) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def plan_size(intent, reconciled_equity: float, config: RiskConfig) -> SizePlan:
    if intent.side == Side.LONG:
        adverse = intent.entry_high
    elif intent.side == Side.SHORT:
        adverse = intent.entry_low
    else:
        raise SizeRejected("health:invalid-enum")
    for name in ("entry_low", "entry_high", "invalidation_price"):
        if not _finite(getattr(intent, name)):
            raise SizeRejected("health:nonfinite-price")
    if intent.entry_low <= 0 or intent.entry_high <= 0 or intent.invalidation_price <= 0:
        raise SizeRejected("health:nonpositive-price")
    if adverse <= 0:
        raise SizeRejected("sizing:bad-reference")
    fc = intent.forecast_cost
    legs = (fc.fee_bps, fc.spread_bps, fc.slippage_bps, fc.funding_bps)
    if not all(_finite(v) for v in legs):
        raise SizeRejected("health:nonfinite-cost")
    if not _finite(reconciled_equity) or reconciled_equity <= 0:
        raise SizeRejected("health:nonfinite-account")
    stop_dist = abs(adverse - intent.invalidation_price)
    if stop_dist <= 0:
        raise SizeRejected("sizing:undefined-risk")
    stressed = sum(legs) / 10000 * config.stress_multiplier
    budget = config.max_loss_budget_pct * reconciled_equity
    qty_raw = budget / (stop_dist + adverse * stressed)
    filt = config.instrument_filters.get(intent.instrument)
    step = filt.qty_step if filt is not None else 1e-8
    qty = math.floor(qty_raw / step * (1 + 1e-9)) * step
    if qty <= 0:
        raise SizeRejected("skip:min-notional")
    if qty * stop_dist + qty * adverse * stressed > budget * (1 + 1e-9):
        raise SizeRejected("sizing:budget-exceeded")
    notional = qty * adverse
    if notional > config.leverage_cap * reconciled_equity:
        raise SizeRejected("leverage:cap-exceeded")
    min_notional = filt.min_notional_usdt if filt is not None else config.min_notional_usdt
    if notional < min_notional:
        raise SizeRejected("skip:min-notional")
    return SizePlan(
        notional_usdt=notional,
        qty=qty,
        reserved_risk=budget,
        stop_pct=stop_dist / adverse,
        stressed_cost_pct=stressed,
        adverse_price=adverse,
    )
