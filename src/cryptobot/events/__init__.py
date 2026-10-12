"""Calendar/event-gate module (Worker 4, EV-001, six-agent-48h).

Deterministic macro-event store, cached official-calendar fixtures
(FOMC + CPI), an entry-blocking gate API for Session, and an
unscheduled-shock policy interface.

The gate blocks NEW ENTRIES ONLY. It has no exit-blocking API by design:
event restrictions never suppress protective exits. Session must consult
the gate in the entry path (``_maybe_admit``) and never in exit handling.
"""
from __future__ import annotations

from .anomaly import (AnomalyBaseline, AnomalyConfig, AnomalyDecision,
                      AnomalyReading, AnomalyState, evaluate)
from .gate import EventGate, GateConfig, GateDecision
from .sources import (CpiSource, FomcSource, SourceAdapter, SourceSnapshot,
                      StubAdapter, apply_snapshot, required_snapshots)
from .store import EventStore, coverage_status
from .timezones import (ET_NAME, IST_NAME, et_local, format_ist, parse_iso_utc,
                        to_ist, to_utc)
from .types import Event, Revision, SourceCoverage

__all__ = [
    "AnomalyBaseline",
    "AnomalyConfig",
    "AnomalyDecision",
    "AnomalyReading",
    "AnomalyState",
    "CpiSource",
    "ET_NAME",
    "Event",
    "EventGate",
    "EventStore",
    "FomcSource",
    "GateConfig",
    "GateDecision",
    "IST_NAME",
    "Revision",
    "SourceAdapter",
    "SourceCoverage",
    "SourceSnapshot",
    "StubAdapter",
    "apply_snapshot",
    "coverage_status",
    "et_local",
    "evaluate",
    "format_ist",
    "parse_iso_utc",
    "required_snapshots",
    "to_ist",
    "to_utc",
]
