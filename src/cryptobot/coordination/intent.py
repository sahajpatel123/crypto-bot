"""Immutable strategy intent schema (CONTRACTS v0.1.0, manager-owned)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Side(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class DataQuality(str, Enum):
    CLEAN = "clean"
    DEGRADED = "degraded"
    HALT = "halt"


@dataclass(frozen=True)
class ForecastCost:
    fee_bps: float
    spread_bps: float
    slippage_bps: float
    funding_bps: float
    label: str = "conservative-simulation"

    def __post_init__(self) -> None:
        for name in ("fee_bps", "spread_bps", "slippage_bps", "funding_bps"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")


@dataclass(frozen=True)
class Intent:
    strategy: str
    version: str
    instrument: str
    side: Side
    evidence_ts_utc: datetime
    entry_low: float
    entry_high: float
    entry_expiry_utc: datetime
    invalidation_price: float
    exit_rule: str
    holding_limit_s: int
    forecast_cost: ForecastCost
    evidence_ref: str
    data_quality: DataQuality
    data_quality_reason: str = ""

    def __post_init__(self) -> None:
        if self.evidence_ts_utc > self.entry_expiry_utc:
            raise ValueError("evidence_ts_utc must be <= entry_expiry_utc")
        if self.entry_low > self.entry_high:
            raise ValueError("entry_low must be <= entry_high")
        if self.holding_limit_s <= 0:
            raise ValueError("holding_limit_s must be > 0")
        if self.side == Side.LONG and not self.invalidation_price < self.entry_low:
            raise ValueError("LONG invalidation must be below entry bounds")
        if self.side == Side.SHORT and not self.invalidation_price > self.entry_high:
            raise ValueError("SHORT invalidation must be above entry bounds")
