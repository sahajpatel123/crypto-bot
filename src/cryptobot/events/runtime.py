"""Protection runtime: the anomaly policy's first caller (W4-24H).

ProtectionRuntime fuses the calendar gate and the anomaly policy into one
entry decision with replayable evidence. Session (manager wiring) calls
check_entry() in the entry path and observe() per measurement tick; both
append full-input records to the evidence log. Advisory mode
(research-only profiles) logs would-block decisions without enforcing.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .anomaly import (
    AnomalyBaseline,
    AnomalyConfig,
    AnomalyDecision,
    AnomalyReading,
    AnomalyState,
    evaluate,
)
from .evidence import EvidenceLog
from .gate import EventGate, GateConfig
from .store import EventStore

BLOCKING_ANOMALY = ("reject-entries", "cancel-entries", "halt-entries")


@dataclass(frozen=True)
class ProtectionDecision:
    blocked: bool
    reason: str
    gate_reason: str
    anomaly_action: str
    advisory: bool
    seq: int | None = None


def fixture_fingerprint(store: EventStore) -> dict[str, Any]:
    ids = sorted(e.event_id for e in store.all())
    digest = hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()[:16]
    by_source: dict[str, int] = {}
    for event in store.all():
        by_source[event.source] = by_source.get(event.source, 0) + 1
    return {"schedule_sha": digest, "events": len(ids),
            "by_source": by_source}


class ProtectionRuntime:
    def __init__(self, store: EventStore,
                 gate_config: GateConfig | None = None,
                 anomaly_config: AnomalyConfig | None = None,
                 evidence_path: str | Path | None = None,
                 advisory_only: bool = False) -> None:
        self.store = store
        self.gate = EventGate(store, gate_config or GateConfig())
        self.anomaly_config = anomaly_config or AnomalyConfig()
        self.anomaly_state = AnomalyState()
        self.advisory_only = advisory_only
        self.evidence: EvidenceLog | None = None
        if evidence_path is not None:
            self.evidence = EvidenceLog(evidence_path, {
                "profile": "research-only/advisory" if advisory_only
                else "protected-operational",
                "schedule": fixture_fingerprint(store),
            })

    def _record(self, kind: str, ts_utc: datetime,
                payload: dict[str, Any]) -> int | None:
        if self.evidence is None:
            return None
        return self.evidence.append(kind, ts_utc, payload)

    @staticmethod
    def _reading_dict(reading: AnomalyReading,
                      baseline: AnomalyBaseline) -> dict[str, Any]:
        return {"spread_bps": reading.spread_bps,
                "book_depth_ratio": reading.book_depth_ratio,
                "abs_return_bps": reading.abs_return_bps,
                "latency_ms": reading.latency_ms,
                "exchange_error_count": reading.exchange_error_count,
                "baseline_spread_bps": baseline.spread_bps,
                "baseline_book_notional": baseline.book_depth_notional}

    def check_entry(self, now_utc: datetime,
                    reading: AnomalyReading | None = None,
                    baseline: AnomalyBaseline | None = None,
                    ) -> ProtectionDecision:
        """Fuse gate + anomaly into one entry decision (logged)."""
        if now_utc.tzinfo is None:
            raise ValueError("now_utc must be timezone-aware")
        reading = reading or AnomalyReading()
        baseline = baseline or AnomalyBaseline()
        gate = self.gate.check(now_utc)
        anomaly = evaluate(self.anomaly_config, reading, baseline,
                           self.anomaly_state, now_utc)
        blocked = gate.blocked or anomaly.action in BLOCKING_ANOMALY
        if gate.blocked:
            reason = gate.reason
        elif anomaly.action in BLOCKING_ANOMALY:
            reason = anomaly.reason
        else:
            reason = "protect:clear"
        advisory = self.advisory_only
        if advisory and blocked:
            reason = f"advisory-would-block:{reason}"
            blocked = False
        seq = self._record("entry-check", now_utc, {
            "inputs": self._reading_dict(reading, baseline),
            "gate": {"blocked": gate.blocked, "reason": gate.reason,
                     "event_ids": list(gate.event_ids)},
            "anomaly": {"action": anomaly.action, "reason": anomaly.reason,
                        "triggered": list(anomaly.triggered)},
            "final": {"blocked": blocked, "reason": reason,
                      "advisory": advisory}})
        return ProtectionDecision(
            blocked=blocked, reason=reason, gate_reason=gate.reason,
            anomaly_action=anomaly.action, advisory=advisory, seq=seq)

    def observe(self, now_utc: datetime, reading: AnomalyReading,
                baseline: AnomalyBaseline | None = None,
                ) -> AnomalyDecision:
        """Fold one measurement-tick reading (logged, never blocks here)."""
        if now_utc.tzinfo is None:
            raise ValueError("now_utc must be timezone-aware")
        baseline = baseline or AnomalyBaseline()
        decision = evaluate(self.anomaly_config, reading, baseline,
                            self.anomaly_state, now_utc)
        self._record("observation", now_utc, {
            "inputs": self._reading_dict(reading, baseline),
            "anomaly": {"action": decision.action, "reason": decision.reason,
                        "triggered": list(decision.triggered)}})
        return decision

    def log_refresh(self, now_utc: datetime,
                    results: dict[str, Any]) -> int | None:
        """Log a source-refresh round (counted, not re-folded)."""
        serializable = {
            name: {"ok": result.ok,
                   "verified_utc": (result.verified_utc.isoformat()
                                    if result.verified_utc else None),
                   "http_status": result.http_status, "error": result.error,
                   "missing": list(result.missing),
                   "extra": list(result.extra)}
            for name, result in results.items()}
        return self._record("refresh", now_utc, {"refresh": serializable})
