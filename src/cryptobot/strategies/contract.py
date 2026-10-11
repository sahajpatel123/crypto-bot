"""Strategy-side contract builders (Worker 1, CONTRACTS v0.1.1).

Reuses the manager-owned ``cryptobot.coordination`` classes as the single
Intent/DecisionRecord types shared with the coordinator. This module adds
only strategy-side conventions: S1 arm ids, the strategy version pin, the
deterministic evidence-ref format, and the frozen S1 conservative cost
preset. It defines no competing schema.
"""
from __future__ import annotations

from datetime import datetime

from cryptobot.coordination import (
    DataQuality,
    DecisionRecord,
    FeatureEvidence,
    ForecastCost,
    Intent,
    Side,
)

CONTRACT_VERSION = "v0.1.1"
STRATEGY_VERSION = "0.1.0"

ARM_BASE = "S1"
ARM_VOLUME = "S1-V"
ARM_FLOW = "S1-F"
ARM_IDS_S1 = (ARM_BASE, ARM_VOLUME, ARM_FLOW)

S2_BASE = "S2"
S2_VOLUME = "S2-V"
S2_FLOW = "S2-F"
ARM_IDS_S2 = (S2_BASE, S2_VOLUME, S2_FLOW)

ARM_IDS = ARM_IDS_S1 + ARM_IDS_S2

COST_LABEL = "conservative-simulation"

# Frozen S1 cost preset: every leg non-zero, labelled conservative-simulation.
# Per-side estimates; net method NET_S1_V1 is documented in EXP-001.
S1_FORECAST_COST = ForecastCost(
    fee_bps=5.0, spread_bps=5.0, slippage_bps=5.0, funding_bps=1.0
)

# S2 uses the same frozen preset values under its own name.
S2_FORECAST_COST = ForecastCost(
    fee_bps=5.0, spread_bps=5.0, slippage_bps=5.0, funding_bps=1.0
)

__all__ = [
    "ARM_BASE",
    "ARM_FLOW",
    "ARM_IDS",
    "ARM_IDS_S1",
    "ARM_IDS_S2",
    "ARM_VOLUME",
    "CONTRACT_VERSION",
    "COST_LABEL",
    "STRATEGY_VERSION",
    "S1_FORECAST_COST",
    "S2_BASE",
    "S2_FLOW",
    "S2_VOLUME",
    "S2_FORECAST_COST",
    "DataQuality",
    "DecisionRecord",
    "FeatureEvidence",
    "ForecastCost",
    "Intent",
    "Side",
    "build_evidence_ref",
    "build_intent",
]


def build_evidence_ref(
    strategy: str,
    version: str,
    instrument: str,
    side: Side,
    evidence_ts_utc: datetime,
) -> str:
    """Deterministic evidence ref / record id (S1.md section 6)."""
    return (
        f"{strategy}:{version}:{instrument}:{side.value}:"
        f"{evidence_ts_utc.isoformat()}"
    )


def build_intent(
    *,
    strategy: str,
    instrument: str,
    side: Side,
    evidence_ts_utc: datetime,
    entry_low: float,
    entry_high: float,
    entry_expiry_utc: datetime,
    invalidation_price: float,
    exit_rule: str,
    holding_limit_s: int,
    evidence_ref: str,
    data_quality: DataQuality,
    data_quality_reason: str = "",
    forecast_cost: ForecastCost = S1_FORECAST_COST,
    version: str = STRATEGY_VERSION,
) -> Intent:
    """Build a strategy Intent enforcing S1 naming/cost conventions.

    Structural invariants (bounds, invalidation side, expiry, holding time)
    are enforced by the manager-owned ``Intent`` itself.
    """
    if strategy not in ARM_IDS:
        raise ValueError(f"unknown S1 arm {strategy!r}; expected one of {ARM_IDS}")
    if version != STRATEGY_VERSION:
        raise ValueError(
            f"strategy version {version!r} != pinned {STRATEGY_VERSION}"
        )
    if forecast_cost.label != COST_LABEL:
        raise ValueError(
            f"forecast_cost.label {forecast_cost.label!r} != {COST_LABEL!r}"
        )
    return Intent(
        strategy=strategy,
        version=version,
        instrument=instrument,
        side=side,
        evidence_ts_utc=evidence_ts_utc,
        entry_low=entry_low,
        entry_high=entry_high,
        entry_expiry_utc=entry_expiry_utc,
        invalidation_price=invalidation_price,
        exit_rule=exit_rule,
        holding_limit_s=holding_limit_s,
        forecast_cost=forecast_cost,
        evidence_ref=evidence_ref,
        data_quality=data_quality,
        data_quality_reason=data_quality_reason,
    )
