"""Deterministic event store with explicit coverage (Worker 4, EV-001).

The store keeps macro events plus one coverage record per source. A source
with no record, an outage, a stale fetch, or an elapsed horizon NEVER reads
as "no events": coverage_status() returns unknown/outage/stale/
expired-horizon and the gate fails closed.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .types import Event, SourceCoverage

STORE_FORMAT = "cryptobot-events/1"


def coverage_status(coverage: SourceCoverage | None,
                    now_utc: datetime) -> str:
    """Resolve the effective coverage state at ``now_utc``.

    Order matters: an explicit outage, unverified cache, or
    not-implemented marker wins over time-based checks; a stale fetch
    wins over horizon (refetch first).
    """
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    if coverage is None:
        return "unknown"
    if coverage.status in ("outage", "not-implemented", "unverified",
                           "cached"):
        return coverage.status
    if now_utc > coverage.expires_utc:
        return "stale"
    if (coverage.horizon_end_utc is not None
            and now_utc > coverage.horizon_end_utc):
        return "expired-horizon"
    return "fresh"


class EventStore:
    def __init__(self) -> None:
        self._events: dict[str, Event] = {}
        self._coverage: dict[str, SourceCoverage] = {}

    def __len__(self) -> int:
        return len(self._events)

    def upsert(self, event: Event) -> None:
        """Insert or replace by event_id.

        Replacements must not move the revision backwards and must keep
        the original first_seen_utc (first observation is immutable).
        """
        prior = self._events.get(event.event_id)
        if prior is not None:
            if event.revision < prior.revision:
                raise ValueError(
                    f"{event.event_id}: revision moved backwards "
                    f"{prior.revision} -> {event.revision}")
            if event.first_seen_utc != prior.first_seen_utc:
                raise ValueError(
                    f"{event.event_id}: first_seen_utc is immutable")
        self._events[event.event_id] = event

    def get(self, event_id: str) -> Event | None:
        return self._events.get(event_id)

    def all(self) -> list[Event]:
        return sorted(self._events.values(),
                      key=lambda e: (e.scheduled_utc, e.event_id))

    def by_source(self, source: str) -> list[Event]:
        return [e for e in self.all() if e.source == source]

    def between(self, start_utc: datetime,
                end_utc: datetime) -> list[Event]:
        if start_utc.tzinfo is None or end_utc.tzinfo is None:
            raise ValueError("bounds must be timezone-aware")
        return [e for e in self.all()
                if start_utc <= e.scheduled_utc <= end_utc]

    def set_coverage(self, coverage: SourceCoverage) -> None:
        self._coverage[coverage.source] = coverage

    def coverage(self, source: str) -> SourceCoverage | None:
        return self._coverage.get(source)

    def coverage_map(self) -> dict[str, SourceCoverage]:
        return dict(self._coverage)

    def status_at(self, now_utc: datetime) -> dict[str, str]:
        return {name: coverage_status(cov, now_utc)
                for name, cov in self._coverage.items()}

    def prune(self, now_utc: datetime) -> list[str]:
        """Drop records past expires_utc. Returns pruned event_ids."""
        if now_utc.tzinfo is None:
            raise ValueError("now_utc must be timezone-aware")
        pruned = [eid for eid, event in self._events.items()
                  if now_utc > event.expires_utc]
        for eid in pruned:
            del self._events[eid]
        return sorted(pruned)

    def save_json(self, path: str | Path) -> None:
        payload = {
            "format": STORE_FORMAT,
            "events": [e.to_dict() for e in self.all()],
            "coverage": [c.to_dict() for c in
                         sorted(self._coverage.values(),
                                key=lambda c: c.source)],
        }
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2, sort_keys=True),
                          encoding="utf-8")

    @classmethod
    def load_json(cls, path: str | Path) -> EventStore:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("format") != STORE_FORMAT:
            raise ValueError(
                f"unsupported event store format: {data.get('format')!r}")
        store = cls()
        for item in data.get("events", []):
            store.upsert(Event.from_dict(item))
        for item in data.get("coverage", []):
            store.set_coverage(SourceCoverage.from_dict(item))
        return store

    def snapshot_meta(self) -> dict[str, Any]:
        return {
            "format": STORE_FORMAT,
            "events": len(self._events),
            "sources": sorted(self._coverage),
        }
