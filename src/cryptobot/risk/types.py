"""Risk gate types (Worker 3, CONTRACTS v0.1.0 + v0.1.1 wiring).

`evaluate(intent, account) -> Approved | Rejected`. Defaults mirror the
DECISIONS.md simulation defaults; they are not proven live settings.

V-004 (F-CEO-07): configuration is validated at construction; invalid
values raise ValueError instead of silently arming a broken gate.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime


def _finite(value: float, name: str) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return float(value)


@dataclass(frozen=True)
class InstrumentFilter:
    """Per-instrument venue filters (V-004, F-CEO-04)."""

    min_notional_usdt: float = 5.0
    qty_step: float = 1e-8

    def __post_init__(self) -> None:
        _finite(self.min_notional_usdt, "min_notional_usdt")
        _finite(self.qty_step, "qty_step")
        if self.min_notional_usdt < 0:
            raise ValueError("min_notional_usdt must be >= 0")
        if self.qty_step <= 0:
            raise ValueError("qty_step must be > 0")


@dataclass(frozen=True)
class RiskConfig:
    contract_version: str = "v0.1.1"
    max_loss_budget_pct: float = 0.0025
    leverage_cap: float = 3.0
    min_notional_usdt: float = 5.0
    # U-003 SIMULATION DEFAULT (unmeasured; see specs/acceptance-u003.md).
    stress_multiplier: float = 1.5
    daily_loss_halt_pct: float = 0.01
    daily_target_pct: float = 0.02
    profit_arm_pct: float = 0.01
    profit_retain_pct: float = 0.70
    # U-003 SIMULATION DEFAULT (unmeasured; see specs/acceptance-u003.md).
    max_evidence_age_s: float = 120.0
    max_clock_skew_s: float = 5.0
    instrument_filters: dict = field(default_factory=dict)
    filters_asof_utc: datetime | None = None
    filters_max_age_s: float = 3600.0

    def __post_init__(self) -> None:
        if not self.contract_version:
            raise ValueError("contract_version must be non-empty")
        for name in ("max_loss_budget_pct", "daily_loss_halt_pct", "profit_arm_pct",
                     "profit_retain_pct"):
            value = _finite(getattr(self, name), name)
            if not 0.0 < value < 1.0:
                raise ValueError(f"{name} must lie in (0, 1)")
        for name in ("leverage_cap", "stress_multiplier", "daily_target_pct",
                     "max_evidence_age_s", "filters_max_age_s"):
            value = _finite(getattr(self, name), name)
            if value <= 0:
                raise ValueError(f"{name} must be > 0")
        _finite(self.min_notional_usdt, "min_notional_usdt")
        if self.min_notional_usdt < 0:
            raise ValueError("min_notional_usdt must be >= 0")
        _finite(self.max_clock_skew_s, "max_clock_skew_s")
        if self.max_clock_skew_s < 0:
            raise ValueError("max_clock_skew_s must be >= 0")
        if self.filters_asof_utc is not None:
            if not isinstance(self.filters_asof_utc, datetime) or self.filters_asof_utc.tzinfo is None:
                raise ValueError("filters_asof_utc must be a tz-aware datetime or None")
        for symbol, filt in self.instrument_filters.items():
            if not symbol or not isinstance(symbol, str):
                raise ValueError("instrument filter keys must be non-empty symbols")
            if not isinstance(filt, InstrumentFilter):
                raise ValueError(f"filter for {symbol!r} must be an InstrumentFilter")


@dataclass(frozen=True)
class AccountSnapshot:
    reconciled_equity: float
    marked_equity: float
    net_liquidation: float
    net_realised_global: float
    open_position: bool
    # Lifetime net external flows (V-004, F-CEO-06). The policy backs out
    # post-baseline flows before comparing against day/global references, so
    # deposits can neither trip targets nor replenish profit protection.
    flows_cumulative: float = 0.0


@dataclass(frozen=True)
class Approved:
    reservation_id: str
    reserved_risk: float
    notional_usdt: float
    qty: float


@dataclass(frozen=True)
class Rejected:
    reason: str


@dataclass(frozen=True)
class HealthStatus:
    """Intent-free monitor verdict (V-004: monitoring runs without intents)."""

    ok: bool
    reasons: tuple[str, ...] = ()
    latched: tuple[str, ...] = ()
