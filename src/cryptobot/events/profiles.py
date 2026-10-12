"""Operational vs research event profiles (Worker 4, W4-24H).

Two explicit postures, classified from the run TOML:

- protected-operational: events_enabled=true AND an [events] section that
  requires verified freshness and wired anomaly decisions. Paper/live use
  with a current calendar. Invalid combinations fail closed at load.
- research-only: anything else (events disabled, verification not
  required, anomaly off). Historical replays whose calendar availability
  is unknown stay here: the gate may run ADVISORY (would-block logged,
  never enforced) but must not block entries.

profiles.py never edits manager-owned configs; it classifies them.
configs/paper-protected.toml (W4-24H carve-out) is the reference
protected profile. ReplayCutoff filters a store to events known at the
replay instant (first_seen_utc <= now); until Session wires the cutoff,
replays MUST stay research-only.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .anomaly import AnomalyConfig
from .gate import GateConfig
from .store import EventStore

PROTECTED = "protected-operational"
RESEARCH = "research-only"


@dataclass(frozen=True)
class OperationalProfile:
    mode: str
    events_enabled: bool
    require_verified: bool
    anomaly_enabled: bool
    cache_ttl_days: int
    refresh_interval_s: int
    advisory_only: bool
    reason: str
    gate: GateConfig
    anomaly: AnomalyConfig

    @property
    def posture(self) -> str:
        return PROTECTED


@dataclass(frozen=True)
class ResearchProfile:
    events_enabled: bool
    reason: str

    @property
    def posture(self) -> str:
        return RESEARCH

    @property
    def advisory_only(self) -> bool:
        return True


def _events_section(path: Path) -> dict[str, Any]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"profile {path} unreadable: {exc}") from exc
    run = data.get("run", {})
    events = data.get("events", {})
    if not isinstance(run, dict) or not isinstance(events, dict):
        raise ValueError(f"profile {path}: [run]/[events] must be tables")
    return {"run": run, "events": events}


def load_profile(path: str | Path) -> OperationalProfile | ResearchProfile:
    """Classify a run TOML and build its event profile (fail-closed)."""
    path = Path(path)
    sections = _events_section(path)
    run, events = sections["run"], sections["events"]
    enabled = bool(run.get("events_enabled", False))
    if not enabled:
        return ResearchProfile(
            events_enabled=False,
            reason="events_enabled is false: calendar/anomaly off, "
                   "explicit research-only")
    mode = str(run.get("mode", "replay"))
    require_verified = bool(events.get("require_verified_freshness", False))
    anomaly_enabled = bool(events.get("enable_anomaly", False))
    advisory = bool(events.get("advisory_only", False))
    if advisory or not require_verified or not anomaly_enabled:
        why = []
        if advisory:
            why.append("advisory_only=true")
        if not require_verified:
            why.append("verified freshness not required")
        if not anomaly_enabled:
            why.append("anomaly decisions off")
        return ResearchProfile(
            events_enabled=True,
            reason="events on but not protected (" + "; ".join(why) +
                   "): explicit research-only, advisory at most")
    try:
        cache_days = int(events.get("cache_ttl_days", 7))
        refresh_s = int(events.get("refresh_interval_s", 6 * 3600))
        gate = GateConfig(
            pre_buffer_s=int(events.get("pre_buffer_s", 900)),
            post_buffer_s=int(events.get("post_buffer_s", 900)),
            press_duration_s=int(events.get("press_duration_s", 3600)),
            resume_cooldown_s=int(events.get("resume_cooldown_s", 0)))
        anomaly = AnomalyConfig(
            spread_widen_bps=float(events.get("spread_widen_bps", 25.0)),
            book_thin_ratio=float(events.get("book_thin_ratio", 0.3)),
            abs_return_bps=float(events.get("abs_return_bps", 50.0)),
            latency_ms=float(events.get("latency_ms", 2000.0)),
            exchange_errors=int(events.get("exchange_errors", 3)),
            cooldown_s=int(events.get("anomaly_cooldown_s", 300)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"profile {path}: bad [events] value: {exc}") from exc
    if cache_days <= 0 or refresh_s <= 0:
        raise ValueError(f"profile {path}: cache_ttl_days and "
                         f"refresh_interval_s must be positive")
    if mode == "replay" and not bool(events.get("replay_cutoff", False)):
        return ResearchProfile(
            events_enabled=True,
            reason="replay without first_seen cutoff: historical calendar "
                   "availability unknown, explicit research-only")
    return OperationalProfile(
        mode=mode, events_enabled=True, require_verified=True,
        anomaly_enabled=True, cache_ttl_days=cache_days,
        refresh_interval_s=refresh_s, advisory_only=False,
        reason="protected-operational: verified freshness + wired anomaly",
        gate=gate, anomaly=anomaly)


class ReplayCutoff:
    """First-seen filter for historical replays (spec section 7)."""

    @staticmethod
    def apply(store: EventStore, replay_now_utc: datetime,
              ) -> tuple[EventStore, dict[str, int]]:
        """Copy of store with only events known at replay_now_utc.

        Events with first_seen_utc > replay_now are future knowledge and
        must not gate a historical replay. Returns (filtered, counts).
        Coverage records carry over unchanged (freshness is orthogonal).
        """
        if replay_now_utc.tzinfo is None:
            raise ValueError("replay_now_utc must be timezone-aware")
        filtered = EventStore()
        kept = dropped = 0
        for event in store.all():
            if event.first_seen_utc <= replay_now_utc:
                filtered.upsert(event)
                kept += 1
            else:
                dropped += 1
        for coverage in store.coverage_map().values():
            filtered.set_coverage(coverage)
        return filtered, {"kept": kept, "dropped_future": dropped}
