"""Planned-loss position sizing incl. stressed costs (Worker 3, R-001..R-003).

Budget: ``max_loss_budget_pct * reconciled_equity`` must cover the stop loss
plus stressed execution costs. Notional is then capped by the leverage cap
(under one-way, isolated, <=3x, required margin ``notional/3 <= equity`` is
the same inequality, so leverage/margin/exposure collapse to one check) and
floored by the venue minimum notional (skip, consuming nothing).
"""
from __future__ import annotations

from dataclasses import dataclass

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


def plan_size(intent, reconciled_equity: float, config: RiskConfig) -> SizePlan:
    ref = (intent.entry_low + intent.entry_high) / 2
    if ref <= 0:
        raise SizeRejected("sizing:bad-reference")
    stop_pct = abs(ref - intent.invalidation_price) / ref
    fc = intent.forecast_cost
    stressed = (fc.fee_bps + fc.spread_bps + fc.slippage_bps + fc.funding_bps) / 10000
    stressed *= config.stress_multiplier
    denom = stop_pct + stressed
    if denom <= 0:
        raise SizeRejected("sizing:undefined-risk")
    budget = config.max_loss_budget_pct * reconciled_equity
    notional = budget / denom
    if notional > config.leverage_cap * reconciled_equity:
        raise SizeRejected("leverage:cap-exceeded")
    if notional < config.min_notional_usdt:
        raise SizeRejected("skip:min-notional")
    return SizePlan(
        notional_usdt=notional,
        qty=notional / ref,
        reserved_risk=budget,
        stop_pct=stop_pct,
        stressed_cost_pct=stressed,
    )
