"""Risk gate types (Worker 3, CONTRACTS v0.1.0).

`evaluate(intent, account) -> Approved | Rejected`. Defaults mirror the
DECISIONS.md simulation defaults; they are not proven live settings.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskConfig:
    contract_version: str = "v0.1.0"
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


@dataclass(frozen=True)
class AccountSnapshot:
    reconciled_equity: float
    marked_equity: float
    net_liquidation: float
    net_realised_global: float
    open_position: bool


@dataclass(frozen=True)
class Approved:
    reservation_id: str
    reserved_risk: float
    notional_usdt: float
    qty: float


@dataclass(frozen=True)
class Rejected:
    reason: str
