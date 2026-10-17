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
    """Per-instrument venue filters (V-004; extended V-006; fixed V-006-F1).

    ``None`` means unconstraining (non-run use). Run mode requires a
    complete record (see :meth:`complete`): only venue-published fields.
    The venue publishes no max-notional filter, so ``max_notional_usdt``
    is an optional OPERATOR cap (caps down when set, never blocks
    completeness). Likewise ``market_min_qty``/``market_max_qty`` apply
    where the venue publishes MARKET_LOT_SIZE; entries are price-protected
    IOC (LIMIT-kind on the economic path) so LOT_SIZE governs, and at
    pilot sizes both maxima exceed any sized quantity by orders of
    magnitude (see sizing notes).
    """

    min_notional_usdt: float = 5.0
    qty_step: float = 1e-8
    max_notional_usdt: float | None = None
    min_qty: float = 0.0
    max_qty: float | None = None
    tick_size: float | None = None
    market_min_qty: float | None = None
    market_max_qty: float | None = None

    def __post_init__(self) -> None:
        _finite(self.min_notional_usdt, "min_notional_usdt")
        _finite(self.qty_step, "qty_step")
        _finite(self.min_qty, "min_qty")
        if self.min_notional_usdt < 0:
            raise ValueError("min_notional_usdt must be >= 0")
        if self.qty_step <= 0:
            raise ValueError("qty_step must be > 0")
        if self.min_qty < 0:
            raise ValueError("min_qty must be >= 0")
        for name in ("max_notional_usdt", "max_qty", "tick_size",
                     "market_min_qty", "market_max_qty"):
            value = getattr(self, name)
            if value is not None:
                _finite(value, name)
                if value <= 0:
                    raise ValueError(f"{name} must be > 0")
        if self.max_notional_usdt is not None and self.max_notional_usdt < self.min_notional_usdt:
            raise ValueError("max_notional_usdt must be >= min_notional_usdt")
        if self.max_qty is not None and self.max_qty < self.min_qty:
            raise ValueError("max_qty must be >= min_qty")
        if (self.market_min_qty is not None and self.market_max_qty is not None
                and self.market_max_qty < self.market_min_qty):
            raise ValueError("market_max_qty must be >= market_min_qty")

    def complete(self) -> bool:
        """True when the record carries every venue-published run field."""
        return (
            self.min_qty > 0
            and self.max_qty is not None
            and self.tick_size is not None
        )


@dataclass(frozen=True)
class RiskConfig:
    contract_version: str = "v0.1.1"
    # W3-24H versioned risk profile (§4): 0.125% max position risk incl
    # stressed costs; 0.5% daily operating stop (ACTION); 1% emergency
    # (persist + reduce + alert + reconciled recovery); 70% floor @1%.
    # All measured flow-adjusted net of costs vs the reconciled IST day
    # start. profile_version tags the parameter set for audit.
    profile_version: str = "24h-1"
    max_loss_budget_pct: float = 0.00125
    leverage_cap: float = 3.0
    min_notional_usdt: float = 5.0
    # U-003 SIMULATION DEFAULT (unmeasured; see specs/acceptance-u003.md).
    stress_multiplier: float = 1.5
    operating_stop_pct: float = 0.005
    emergency_stop_pct: float = 0.01
    # Deprecated alias for emergency_stop_pct (pre-24h configs/tests pass
    # daily_loss_halt_pct). Honored only when emergency_stop_pct is left
    # at default; conflicting values raise. Removed at manager migration.
    daily_loss_halt_pct: float | None = None
    daily_target_pct: float = 0.02
    profit_arm_pct: float = 0.01
    profit_retain_pct: float = 0.70
    # W3-24H stale-mark block: None disables; set = snapshots older than
    # this (or of unknown age) block admission and report unhealthy.
    max_mark_age_ms: float | None = None
    # U-003 SIMULATION DEFAULT (unmeasured; see specs/acceptance-u003.md).
    max_evidence_age_s: float = 120.0
    max_clock_skew_s: float = 5.0
    instrument_filters: dict = field(default_factory=dict)
    filters_asof_utc: datetime | None = None
    filters_max_age_s: float = 3600.0
    # F0.4a LIVE bracket gate: symbol -> leverage-bracket tiers as
    # published by GET /fapi/v1/leverageBracket (each tier:
    # {notionalCap, maintMarginRatio, cum}). Run mode requires fresh
    # brackets for the intent instrument; stale brackets always reject
    # when brackets are configured (fail closed: an unknown tier must
    # never admit size). Non-run without brackets skips the gate
    # (fault/replay tests).
    leverage_brackets: dict = field(default_factory=dict)
    brackets_asof_utc: datetime | None = None
    brackets_max_age_s: float = 3600.0
    # V-006 run mode: strict filter/metadata enforcement for session runtime.
    # Fault tests run with run_mode=False (filters optional, fee=0 allowed).
    run_mode: bool = False

    def __post_init__(self) -> None:
        if not self.contract_version:
            raise ValueError("contract_version must be non-empty")
        if not self.profile_version:
            raise ValueError("profile_version must be non-empty")
        if self.daily_loss_halt_pct is not None:
            import warnings
            warnings.warn("daily_loss_halt_pct is deprecated; use "
                          "emergency_stop_pct", DeprecationWarning,
                          stacklevel=2)
            alias = _finite(self.daily_loss_halt_pct, "daily_loss_halt_pct")
            if not 0.0 < alias < 1.0:
                raise ValueError("daily_loss_halt_pct must lie in (0, 1)")
            if self.emergency_stop_pct != 0.01:
                raise ValueError("conflicting emergency_stop_pct and "
                                 "daily_loss_halt_pct")
            object.__setattr__(self, "emergency_stop_pct", alias)
        for name in ("max_loss_budget_pct", "operating_stop_pct",
                     "emergency_stop_pct", "profit_arm_pct",
                     "profit_retain_pct"):
            value = _finite(getattr(self, name), name)
            if not 0.0 < value < 1.0:
                raise ValueError(f"{name} must lie in (0, 1)")
        if not self.operating_stop_pct < self.emergency_stop_pct:
            raise ValueError("operating_stop_pct must be < emergency_stop_pct")
        if self.max_mark_age_ms is not None:
            _finite(self.max_mark_age_ms, "max_mark_age_ms")
            if self.max_mark_age_ms <= 0:
                raise ValueError("max_mark_age_ms must be > 0")
        for name in ("leverage_cap", "stress_multiplier", "daily_target_pct",
                     "max_evidence_age_s", "filters_max_age_s"):
            value = _finite(getattr(self, name), name)
            if value <= 0:
                raise ValueError(f"{name} must be > 0")
        _finite(self.brackets_max_age_s, "brackets_max_age_s")
        if self.brackets_max_age_s <= 0:
            raise ValueError("brackets_max_age_s must be > 0")
        _finite(self.min_notional_usdt, "min_notional_usdt")
        if self.min_notional_usdt < 0:
            raise ValueError("min_notional_usdt must be >= 0")
        _finite(self.max_clock_skew_s, "max_clock_skew_s")
        if self.max_clock_skew_s < 0:
            raise ValueError("max_clock_skew_s must be >= 0")
        if self.filters_asof_utc is not None:
            if not isinstance(self.filters_asof_utc, datetime) or self.filters_asof_utc.tzinfo is None:
                raise ValueError("filters_asof_utc must be a tz-aware datetime or None")
        if self.brackets_asof_utc is not None:
            if not isinstance(self.brackets_asof_utc, datetime) or self.brackets_asof_utc.tzinfo is None:
                raise ValueError("brackets_asof_utc must be a tz-aware datetime or None")
        for symbol, filt in self.instrument_filters.items():
            if not symbol or not isinstance(symbol, str):
                raise ValueError("instrument filter keys must be non-empty symbols")
            if not isinstance(filt, InstrumentFilter):
                raise ValueError(f"filter for {symbol!r} must be an InstrumentFilter")
        for symbol, tiers in self.leverage_brackets.items():
            if not symbol or not isinstance(symbol, str):
                raise ValueError("leverage bracket keys must be non-empty symbols")
            if not isinstance(tiers, list) or not tiers:
                raise ValueError(f"brackets for {symbol!r} must be a non-empty list")
            for tier in tiers:
                for key in ("notionalCap", "maintMarginRatio"):
                    if key not in tier:
                        raise ValueError(
                            f"bracket tier for {symbol!r} missing {key!r}")
                    _finite(float(tier[key]), f"bracket {key}")
                if float(tier["notionalCap"]) <= 0:
                    raise ValueError("bracket notionalCap must be > 0")
                if not 0.0 <= float(tier["maintMarginRatio"]) < 1.0:
                    raise ValueError("bracket maintMarginRatio must lie in [0, 1)")
        if not isinstance(self.run_mode, bool):
            raise ValueError("run_mode must be a bool")


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
    # V-006 margin inputs (all USDT). None available_margin skips the margin
    # gate (leverage cap still applies); the session runtime always supplies it.
    available_margin_usdt: float | None = None
    fee_buffer_usdt: float = 0.0
    inflight_exposure_usdt: float = 0.0
    # W3-24H mark age (ms) at snapshot time; None = unrecorded. Blocks
    # when the profile configures max_mark_age_ms (fail closed).
    mark_age_ms: float | None = None


@dataclass(frozen=True)
class Approved:
    reservation_id: str
    reserved_risk: float
    notional_usdt: float
    qty: float
    # V-007 B8: quantity the protective stop must cover in full. Under the
    # one-way single-position pilot this equals qty; the manager verifies
    # the engine-acknowledged stop quantity against it (never falsely
    # protected). None only for legacy records that predate the field.
    required_stop_qty: float | None = None


@dataclass(frozen=True)
class Rejected:
    reason: str


@dataclass(frozen=True)
class HealthStatus:
    """Intent-free monitor verdict (V-004: monitoring runs without intents)."""

    ok: bool
    reasons: tuple[str, ...] = ()
    latched: tuple[str, ...] = ()
