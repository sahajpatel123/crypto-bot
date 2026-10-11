"""Causal decision records (manager-owned, CONTRACTS v0.1.0).

Each strategy Intent points at one record via ``evidence_ref`` (= ``record_id``).
Records carry the causal evidence behind a signal: regime, features with
windows/thresholds, the trigger clause, and the reject checks evaluated.
Long/short evidence stays separate because each Intent (hence each record) has
one side. No hand-assigned confidence percentages live here.
"""
from __future__ import annotations

from dataclasses import dataclass

from .intent import DataQuality, Side


@dataclass(frozen=True)
class FeatureEvidence:
    name: str
    window: str
    threshold: str
    observed: str


@dataclass(frozen=True)
class DecisionRecord:
    record_id: str
    side: Side
    regime: str
    features: tuple[FeatureEvidence, ...]
    trigger: str
    rejects_evaluated: tuple[str, ...]
    data_quality: DataQuality
    data_quality_reason: str = ""

    def __post_init__(self) -> None:
        if not self.record_id:
            raise ValueError("record_id must be non-empty")
        if not self.regime:
            raise ValueError("regime must be non-empty")
        if not self.features:
            raise ValueError("features must list the evidence used")
        if not self.trigger:
            raise ValueError("trigger must name the fired clause")
