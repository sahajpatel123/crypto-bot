"""Source adapters: cached fixtures + explicit outage behavior (EV-001).

EV-001 ships cached FOMC + CPI schedules as JSON fixtures. Adapters load
them into the store with fetch/horizon/expiry metadata. Live HTTP refresh
is out of scope; the snapshot status vocabulary already covers outage and
stale so a future live adapter plugs in without changing the gate.

Coverage TTL is 24h: a cached schedule older than that reads "stale" and
the gate fails closed until a refetch (fixture reload with a new fetch
timestamp, or a future live fetch) lands.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from .store import EventStore
from .timezones import ET_NAME, parse_iso_utc
from .types import Event, SourceCoverage

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
FIXTURE_FORMAT = "cryptobot-event-fixture/1"
COVERAGE_TTL = timedelta(hours=24)
EVENT_RETENTION = timedelta(days=7)

FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
CPI_URL = "https://www.bls.gov/schedule/"


@dataclass(frozen=True)
class SourceSnapshot:
    source: str
    source_url: str
    events: tuple[Event, ...]
    horizon_end_utc: datetime | None
    fetched_utc: datetime
    status: str
    error: str = ""

    def coverage(self, ttl: timedelta = COVERAGE_TTL) -> SourceCoverage:
        return SourceCoverage(
            source=self.source, source_url=self.source_url,
            horizon_end_utc=self.horizon_end_utc,
            fetched_utc=self.fetched_utc,
            expires_utc=self.fetched_utc + ttl,
            status=self.status if self.status in (
                "fresh", "outage", "not-implemented") else "fresh",
            last_error=self.error)


class SourceAdapter(Protocol):
    source_id: str
    source_url: str

    def load(self, now_utc: datetime) -> SourceSnapshot:
        """Load cached events; never raises for transport issues.

        Transport/outage problems surface as status="outage" with an
        explicit error string, never as an empty event list that could
        be mistaken for a quiet calendar.
        """
        ...


def _fixture_events(source: str, source_url: str, payload: dict,
                    first_seen_utc: datetime, fetch_utc: datetime,
                    horizon_end_utc: datetime | None) -> list[Event]:
    tz_name = payload.get("tz_name", ET_NAME)
    events = []
    for item in payload.get("events", []):
        scheduled_utc = parse_iso_utc(item["scheduled_utc"])
        press_end = (parse_iso_utc(item["press_end_utc"])
                     if item.get("press_end_utc") else None)
        events.append(Event(
            event_id=item["event_id"], source=source,
            title=item.get("title", item["event_id"]),
            kind=item.get("kind", "release"), source_url=source_url,
            scheduled_local_iso=item["scheduled_local_iso"],
            tz_name=tz_name, scheduled_utc=scheduled_utc,
            first_seen_utc=first_seen_utc, fetch_utc=fetch_utc,
            revision=int(payload.get("revision", 0)),
            horizon_end_utc=horizon_end_utc,
            expires_utc=scheduled_utc + EVENT_RETENTION,
            press_end_utc=press_end, status="scheduled",
            note=item.get("note", "")))
    return events


class FixtureAdapter:
    """Load a cached schedule fixture with explicit fetch metadata."""

    def __init__(self, source_id: str, source_url: str,
                 fixture: str) -> None:
        self.source_id = source_id
        self.source_url = source_url
        self.fixture = fixture
        self._forced_error: str | None = None

    def force_outage(self, error: str) -> None:
        """Inject an outage for the next load() (tests / drills)."""
        self._forced_error = error

    def clear_outage(self) -> None:
        self._forced_error = None

    def fixture_path(self) -> Path:
        return FIXTURE_DIR / self.fixture

    def load(self, now_utc: datetime) -> SourceSnapshot:
        if now_utc.tzinfo is None:
            raise ValueError("now_utc must be timezone-aware")
        if self._forced_error is not None:
            return SourceSnapshot(
                source=self.source_id, source_url=self.source_url,
                events=(), horizon_end_utc=None, fetched_utc=now_utc,
                status="outage", error=self._forced_error)
        try:
            payload = json.loads(
                self.fixture_path().read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return SourceSnapshot(
                source=self.source_id, source_url=self.source_url,
                events=(), horizon_end_utc=None, fetched_utc=now_utc,
                status="outage", error=f"fixture unreadable: {exc}")
        if payload.get("format") != FIXTURE_FORMAT:
            return SourceSnapshot(
                source=self.source_id, source_url=self.source_url,
                events=(), horizon_end_utc=None, fetched_utc=now_utc,
                status="outage",
                error=f"bad fixture format: {payload.get('format')!r}")
        if payload.get("source") != self.source_id:
            return SourceSnapshot(
                source=self.source_id, source_url=self.source_url,
                events=(), horizon_end_utc=None, fetched_utc=now_utc,
                status="outage",
                error=f"fixture source {payload.get('source')!r} != "
                      f"{self.source_id!r}")
        horizon = (parse_iso_utc(payload["horizon_end_utc"])
                   if payload.get("horizon_end_utc") else None)
        first_seen = (parse_iso_utc(payload["first_seen_utc"])
                      if payload.get("first_seen_utc") else now_utc)
        try:
            events = _fixture_events(self.source_id, self.source_url,
                                     payload, first_seen, now_utc, horizon)
        except ValueError as exc:
            return SourceSnapshot(
                source=self.source_id, source_url=self.source_url,
                events=(), horizon_end_utc=horizon, fetched_utc=now_utc,
                status="outage", error=f"fixture event invalid: {exc}")
        return SourceSnapshot(
            source=self.source_id, source_url=self.source_url,
            events=tuple(events), horizon_end_utc=horizon,
            fetched_utc=now_utc, status="fresh")


class FomcSource(FixtureAdapter):
    def __init__(self) -> None:
        super().__init__("fomc", FOMC_URL, "fomc_2026.json")


class CpiSource(FixtureAdapter):
    def __init__(self) -> None:
        super().__init__("cpi", CPI_URL, "cpi_2026.json")


class StubAdapter:
    """Explicit placeholder for sources EV-001 does not schedule yet.

    Returns status "not-implemented" with an empty event list and no
    horizon, so the gate treats a REQUIRED stub as blocking-unknown and
    an optional one as ignored-but-visible. Never silently "fresh".
    """

    def __init__(self, source_id: str, source_url: str) -> None:
        self.source_id = source_id
        self.source_url = source_url

    def load(self, now_utc: datetime) -> SourceSnapshot:
        if now_utc.tzinfo is None:
            raise ValueError("now_utc must be timezone-aware")
        return SourceSnapshot(
            source=self.source_id, source_url=self.source_url, events=(),
            horizon_end_utc=None, fetched_utc=now_utc,
            status="not-implemented",
            error=f"{self.source_id}: no cached schedule in EV-001")


def apply_snapshot(store: EventStore, snapshot: SourceSnapshot,
                   ttl: timedelta = COVERAGE_TTL) -> None:
    for event in snapshot.events:
        store.upsert(event)
    store.set_coverage(snapshot.coverage(ttl=ttl))


def required_snapshots(now_utc: datetime) -> list[SourceSnapshot]:
    """Load the EV-001 required sources (FOMC + CPI)."""
    return [FomcSource().load(now_utc), CpiSource().load(now_utc)]
