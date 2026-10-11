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

from cryptobot.strategies.contract import ARM_IDS, STRATEGY_VERSION

from .synthetic import SCENARIOS

REGISTRY_VERSION = "0.1.0"
TRAIN_FRAC = 0.70
EMBARGO_FRAC = 0.05
VALIDATION_FRAC = 0.25
TRAIN_SEEDS = (11, 12, 13)
VALIDATION_SEEDS = (21, 22)

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
    "arms": list(ARM_IDS),
    "scenarios": list(SCENARIOS),
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

__all__ = [
    "EMBARGO_FRAC",
    "EXP_001",
    "NET_S1_V1",
    "REGISTRY_VERSION",
    "TRAIN_FRAC",
    "TRAIN_SEEDS",
    "VALIDATION_FRAC",
    "VALIDATION_SEEDS",
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
