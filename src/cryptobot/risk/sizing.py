"""Planned-loss position sizing (Worker 3, V-004 / F-CEO-04 correction).

Budget: ``max_loss_budget_pct * reconciled_equity`` must cover the stop loss
plus stressed execution costs **at the adverse permitted fill price**
(LONG: entry_high; SHORT: entry_low). Quantity is computed qty-first from
that bound, rounded DOWN to the venue step (per-instrument filter when
configured, else 1e-8), then rechecked against budget, leverage, and minimum
notional. Rounding never rounds up to meet a minimum.

V-006: when the caller supplies available margin, an additional margin gate
caps notional so ``(inflight + notional) / leverage_cap + fee_buffer <=
available`` (the leverage cap alone is not a margin substitute). Venue
max-qty / max-notional bounds cap down (safe direction); min-qty / min-
notional violations skip (never round up).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from cryptobot.coordination import Side

from .rounding import floor_to_step
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


def plan_size(
    intent,
    reconciled_equity: float,
    config: RiskConfig,
    *,
    available_margin_usdt: float | None = None,
    fee_buffer_usdt: float = 0.0,
    inflight_exposure_usdt: float = 0.0,
) -> SizePlan:
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
    if available_margin_usdt is not None and (
        not _finite(available_margin_usdt) or available_margin_usdt < 0
    ):
        raise SizeRejected("health:nonfinite-account")
    if not _finite(fee_buffer_usdt) or fee_buffer_usdt < 0:
        raise SizeRejected("health:nonfinite-account")
    if not _finite(inflight_exposure_usdt) or inflight_exposure_usdt < 0:
        raise SizeRejected("health:nonfinite-account")
    stop_dist = abs(adverse - intent.invalidation_price)
    if stop_dist <= 0:
        raise SizeRejected("sizing:undefined-risk")
    stressed = sum(legs) / 10000 * config.stress_multiplier
    budget = config.max_loss_budget_pct * reconciled_equity
    qty_raw = budget / (stop_dist + adverse * stressed)
    filt = config.instrument_filters.get(intent.instrument)
    step = filt.qty_step if filt is not None else 1e-8
    min_qty = filt.min_qty if filt is not None else 0.0
    max_qty = filt.max_qty if filt is not None else None
    if filt is not None:
        # MARKET entries respect MARKET_LOT_SIZE where the venue publishes
        # it (intersection with LOT_SIZE = tighter bound governs). Where
        # unpublished, LOT_SIZE suffices: pilot quantities sit orders of
        # magnitude below any venue maximum while the LOT minimum remains
        # the binding floor.
        if filt.market_min_qty is not None:
            min_qty = max(min_qty, filt.market_min_qty)
        if filt.market_max_qty is not None:
            max_qty = filt.market_max_qty if max_qty is None else min(max_qty, filt.market_max_qty)
    min_notional = filt.min_notional_usdt if filt is not None else config.min_notional_usdt
    max_notional = filt.max_notional_usdt if filt is not None else None

    def floored(qty: float) -> float:
        # V-008 §7: the one shared venue-rounding rule (risk leg).
        return floor_to_step(qty, step)

    def within_budget(qty: float) -> bool:
        return qty * stop_dist + qty * adverse * stressed <= budget * (1 + 1e-9)

    qty = floored(qty_raw)
    if max_qty is not None:
        qty = floored(min(qty, max_qty))
    if qty <= 0 or qty < min_qty:
        raise SizeRejected("skip:min-notional")
    if not within_budget(qty):
        raise SizeRejected("sizing:budget-exceeded")
    notional = qty * adverse
    if available_margin_usdt is not None:
        affordable = (available_margin_usdt - fee_buffer_usdt) * config.leverage_cap
        affordable -= inflight_exposure_usdt
        if affordable < min_notional:
            raise SizeRejected("margin:insufficient")
        if notional > affordable:
            qty = floored(affordable / adverse)
            if qty <= 0 or qty < min_qty or not within_budget(qty):
                raise SizeRejected("margin:insufficient")
            notional = qty * adverse
    if notional > config.leverage_cap * reconciled_equity:
        raise SizeRejected("leverage:cap-exceeded")
    if max_notional is not None and notional > max_notional:
        qty = floored(max_notional / adverse)
        if qty <= 0 or qty < min_qty or not within_budget(qty):
            raise SizeRejected("filters:notional-cap")
        notional = qty * adverse
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
