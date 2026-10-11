"""Experiment registry (Worker 1, Q-001): preregistration, splits, trial log.

EXP-001 is PREREGISTERED (plan only): the first S1 comparison runs after the
baseline integrates with replay/risk review. Zero trials have been executed;
the trial log ships empty and the logging mechanism is covered by unit tests.
Seeds are documented below; no seed, arm, or parameter is promoted.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from cryptobot.strategies.contract import (
    ARM_IDS_S1,
    ARM_IDS_S2,
    ARM_IDS_S3,
    ARM_IDS_S4,
    STRATEGY_VERSION,
)

from .synthetic import (
    SCENARIO_CHOPPY,
    SCENARIO_FLAT,
    SCENARIO_GAP,
    SCENARIO_LONG,
    SCENARIO_S2_LONG,
    SCENARIO_S2_SHORT,
    SCENARIO_S3_LONG,
    SCENARIO_S3_SHORT,
    SCENARIO_S4_LONG,
    SCENARIO_S4_SHORT,
    SCENARIO_SHORT,
    SCENARIO_WIDE_SPREAD,
)

REGISTRY_VERSION = "0.3.0"
TRAIN_FRAC = 0.70
EMBARGO_FRAC = 0.05
VALIDATION_FRAC = 0.25
TRAIN_SEEDS = (11, 12, 13)
VALIDATION_SEEDS = (21, 22)
TRAIN_SEEDS_S2 = (31, 32, 33)
VALIDATION_SEEDS_S2 = (41, 42)
TRAIN_SEEDS_S3 = (51, 52, 53)
VALIDATION_SEEDS_S3 = (61, 62)
TRAIN_SEEDS_S4 = (71, 72, 73)
VALIDATION_SEEDS_S4 = (81, 82)

# Preregistrations pin their scenario lists: later generator additions must
# never retroactively change a filed experiment.
S1_SCENARIOS = (
    SCENARIO_LONG,
    SCENARIO_SHORT,
    SCENARIO_FLAT,
    SCENARIO_CHOPPY,
    SCENARIO_GAP,
    SCENARIO_WIDE_SPREAD,
)
S2_SCENARIOS = (
    SCENARIO_S2_LONG,
    SCENARIO_S2_SHORT,
    SCENARIO_FLAT,
    SCENARIO_CHOPPY,
)
S3_SCENARIOS = (
    SCENARIO_S3_LONG,
    SCENARIO_S3_SHORT,
    SCENARIO_FLAT,
    SCENARIO_CHOPPY,
)
S4_SCENARIOS = (
    SCENARIO_S4_LONG,
    SCENARIO_S4_SHORT,
    SCENARIO_FLAT,
    SCENARIO_CHOPPY,
)

NET_S1_V1 = """NET_S1_V1 net-economics method (labelled, conservative-simulation):
per-side cost bps = fee + slippage + spread/2 + funding*horizon_share;
round-trip estimate = 2*(fee+slippage) + spread + funding.
S1 preset: fee=5.0 spread=5.0 slippage=5.0 funding=1.0 (bps, all non-zero).
PnL estimates are descriptive simulation diagnostics, never live fills."""

EXP_001 = {
    "exp_id": "EXP-001",
    "question": "Do volume/flow confirmation gates change S1 breakout signal "
                "counts and reject mix vs breakout alone (descriptive)?",
    "strategy_version": STRATEGY_VERSION,
    "arms": list(ARM_IDS_S1),
    "scenarios": list(S1_SCENARIOS),
    "train_seeds": list(TRAIN_SEEDS),
    "validation_seeds": list(VALIDATION_SEEDS),
    "split": {"train_frac": TRAIN_FRAC, "embargo_frac": EMBARGO_FRAC,
              "validation_frac": VALIDATION_FRAC},
    "cost_method": "NET_S1_V1",
    "metrics": ["n_signals_long", "n_signals_short", "reject_counts",
                "net_bps_estimate"],
    "promotion_rule": "NONE - descriptive only; no arm may be promoted "
                      "from EXP-001",
    "status": "preregistered",
    "trials_executed": 0,
}

EXP_002 = {
    "exp_id": "EXP-002",
    "question": "Do volume/flow confirmation gates change S2 pullback signal "
                "counts and reject mix vs pullback alone (descriptive)?",
    "strategy_version": STRATEGY_VERSION,
    "arms": list(ARM_IDS_S2),
    "scenarios": list(S2_SCENARIOS),
    "train_seeds": list(TRAIN_SEEDS_S2),
    "validation_seeds": list(VALIDATION_SEEDS_S2),
    "split": {"train_frac": TRAIN_FRAC, "embargo_frac": EMBARGO_FRAC,
              "validation_frac": VALIDATION_FRAC},
    "cost_method": "NET_S1_V1",
    "metrics": ["n_signals_long", "n_signals_short", "reject_counts",
                "net_bps_estimate"],
    "promotion_rule": "NONE - descriptive only; no arm may be promoted "
                      "from EXP-002",
    "status": "preregistered",
    "trials_executed": 0,
}

EXP_003 = {
    "exp_id": "EXP-003",
    "question": "Do the S3-R regime filter and S3-C cost cover change S3 "
                "fade signal counts and reject mix vs unfiltered S3 "
                "(descriptive)?",
    "strategy_version": STRATEGY_VERSION,
    "arms": list(ARM_IDS_S3),
    "scenarios": list(S3_SCENARIOS),
    "train_seeds": list(TRAIN_SEEDS_S3),
    "validation_seeds": list(VALIDATION_SEEDS_S3),
    "split": {"train_frac": TRAIN_FRAC, "embargo_frac": EMBARGO_FRAC,
              "validation_frac": VALIDATION_FRAC},
    "cost_method": "NET_S1_V1",
    "metrics": ["n_signals_long", "n_signals_short", "reject_counts",
                "net_bps_estimate"],
    "promotion_rule": "NONE - descriptive only; no arm may be promoted "
                      "from EXP-003",
    "status": "preregistered",
    "trials_executed": 0,
}

EXP_004 = {
    "exp_id": "EXP-004",
    "question": "Does the S4 pierce requirement change reclaim signal "
                "counts and reject mix vs the simple-reversal baseline S4-S "
                "(descriptive)?",
    "strategy_version": STRATEGY_VERSION,
    "arms": list(ARM_IDS_S4),
    "scenarios": list(S4_SCENARIOS),
    "train_seeds": list(TRAIN_SEEDS_S4),
    "validation_seeds": list(VALIDATION_SEEDS_S4),
    "split": {"train_frac": TRAIN_FRAC, "embargo_frac": EMBARGO_FRAC,
              "validation_frac": VALIDATION_FRAC},
    "cost_method": "NET_S1_V1",
    "metrics": ["n_signals_long", "n_signals_short", "reject_counts",
                "net_bps_estimate"],
    "promotion_rule": "NONE - descriptive only; no arm may be promoted "
                      "from EXP-004",
    "status": "preregistered",
    "trials_executed": 0,
}

__all__ = [
    "EMBARGO_FRAC",
    "EXP_001",
    "EXP_002",
    "EXP_003",
    "EXP_004",
    "NET_S1_V1",
    "REGISTRY_VERSION",
    "S1_SCENARIOS",
    "S2_SCENARIOS",
    "S3_SCENARIOS",
    "S4_SCENARIOS",
    "TRAIN_FRAC",
    "TRAIN_SEEDS",
    "TRAIN_SEEDS_S2",
    "TRAIN_SEEDS_S3",
    "TRAIN_SEEDS_S4",
    "VALIDATION_FRAC",
    "VALIDATION_SEEDS",
    "VALIDATION_SEEDS_S2",
    "VALIDATION_SEEDS_S3",
    "VALIDATION_SEEDS_S4",
    "Split",
    "TrialLog",
    "TrialRecord",
    "split_indices",
]


@dataclass(frozen=True)
class Split:
    """Index split with embargo: train=[0,train_end), val=[val_start,n)."""

    n_bars: int
    train_end: int
    val_start: int

    def __post_init__(self) -> None:
        if not 0 < self.train_end < self.val_start < self.n_bars:
            raise ValueError("split must satisfy 0 < train_end < val_start < n")


def split_indices(n_bars: int) -> Split:
    """70/5/25 time split with an embargo gap between train and validation."""
    if n_bars < 20:
        raise ValueError("n_bars must be >= 20 for a meaningful split")
    train_end = int(n_bars * TRAIN_FRAC)
    val_start = n_bars - int(n_bars * VALIDATION_FRAC)
    if not 0 < train_end < val_start < n_bars:
        raise ValueError(f"degenerate split for n_bars={n_bars}")
    return Split(n_bars, train_end, val_start)


@dataclass(frozen=True)
class TrialRecord:
    trial_id: str
    exp_id: str
    arm: str
    seed: int
    split: str  # "train" | "validation"
    status: str  # "ok" | "failed"
    reason: str
    utc: str
    metrics: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if self.split not in ("train", "validation"):
            raise ValueError("split must be train or validation")
        if self.status not in ("ok", "failed"):
            raise ValueError("status must be ok or failed")
        if not self.trial_id:
            raise ValueError("trial_id must be non-empty")

    def to_dict(self) -> dict:
        return {
            "trial_id": self.trial_id,
            "exp_id": self.exp_id,
            "arm": self.arm,
            "seed": self.seed,
            "split": self.split,
            "status": self.status,
            "reason": self.reason,
            "utc": self.utc,
            "metrics": [list(p) for p in self.metrics],
        }

    @staticmethod
    def utcnow() -> str:
        return datetime.now(timezone.utc).isoformat()


@dataclass
class TrialLog:
    """Append-only trial log; every failed trial stays recorded."""

    trials: list[TrialRecord] = field(default_factory=list)

    def log_trial(self, record: TrialRecord) -> None:
        if any(t.trial_id == record.trial_id for t in self.trials):
            raise ValueError(f"duplicate trial_id {record.trial_id}")
        self.trials.append(record)

    def failed(self) -> list[TrialRecord]:
        return [t for t in self.trials if t.status == "failed"]

    def to_json(self) -> str:
        return json.dumps([t.to_dict() for t in self.trials], indent=2)
