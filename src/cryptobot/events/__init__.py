"""Calendar/event-gate module (Worker 4, EV-001, six-agent-48h).

Deterministic macro-event store, cached official-calendar fixtures
(FOMC + CPI), an entry-blocking gate API for Session, and an
unscheduled-shock policy interface.

The gate blocks NEW ENTRIES ONLY. It has no exit-blocking API by design:
event restrictions never suppress protective exits. Session must consult
the gate in the entry path (``_maybe_admit``) and never in exit handling.
"""
from __future__ import annotations

from .anomaly import (
                      AnomalyBaseline,
                      AnomalyConfig,
                      AnomalyDecision,
                      AnomalyReading,
                      AnomalyState,
                      evaluate,
)
from .evidence import EvidenceLog, read_evidence, replay_evidence
from .freshness import (
                      CACHE_TTL,
                      REFRESH_INTERVAL_S,
                      FreshnessTracker,
                      HttpResponse,
                      RefreshResult,
                      SourceState,
                      SourceStateStore,
                      default_http_get,
                      parse_cpi_release_dates,
                      parse_employment_dates,
                      parse_fomc_decision_dates,
)
from .gate import EventGate, GateConfig, GateDecision
from .profiles import OperationalProfile, ReplayCutoff, ResearchProfile, load_profile
from .runtime import ProtectionDecision, ProtectionRuntime
from .sources import (
                      CpiSource,
                      EmploymentSource,
                      FomcSource,
                      SourceAdapter,
                      SourceSnapshot,
                      StubAdapter,
                      adapters_for,
                      apply_snapshot,
                      required_snapshots,
)
from .store import EventStore, coverage_status
from .timezones import ET_NAME, IST_NAME, et_local, format_ist, parse_iso_utc, to_ist, to_utc
from .types import Event, Revision, SourceCoverage

__all__ = [
    "AnomalyBaseline",
    "AnomalyConfig",
    "AnomalyDecision",
    "AnomalyReading",
    "AnomalyState",
    "CACHE_TTL",
    "CpiSource",
    "ET_NAME",
    "EmploymentSource",
    "Event",
    "EventGate",
    "EventStore",
    "EvidenceLog",
    "FomcSource",
    "FreshnessTracker",
    "GateConfig",
    "GateDecision",
    "HttpResponse",
    "IST_NAME",
    "OperationalProfile",
    "ProtectionDecision",
    "ProtectionRuntime",
    "REFRESH_INTERVAL_S",
    "RefreshResult",
    "ReplayCutoff",
    "ResearchProfile",
    "Revision",
    "SourceAdapter",
    "SourceCoverage",
    "SourceSnapshot",
    "SourceState",
    "SourceStateStore",
    "StubAdapter",
    "adapters_for",
    "apply_snapshot",
    "coverage_status",
    "default_http_get",
    "et_local",
    "evaluate",
    "format_ist",
    "load_profile",
    "parse_cpi_release_dates",
    "parse_employment_dates",
    "parse_fomc_decision_dates",
    "parse_iso_utc",
    "read_evidence",
    "replay_evidence",
    "required_snapshots",
    "to_ist",
    "to_utc",
]
