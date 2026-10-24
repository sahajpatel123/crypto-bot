"""Event and coverage record types (Worker 4, EV-001)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from .timezones import ET_NAME, parse_iso_utc, to_utc

EVENT_STATUSES = ("scheduled", "released", "revised", "cancelled")
EVENT_KINDS = ("decision", "press-conference", "release", "maintenance",
               "delisting")
COVERAGE_STATUSES = ("fresh", "stale", "expired-horizon", "outage",
                     "unknown", "not-implemented", "cached", "unverified")


@dataclass(frozen=True)
class Revision:
    rev: int
    fetched_utc: datetime
    note: str
    changed: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.rev < 0:
            raise ValueError("rev must be >= 0")
        if self.fetched_utc.tzinfo is None:
            raise ValueError("fetched_utc must be timezone-aware")
        object.__setattr__(self, "changed", tuple(self.changed))


@dataclass(frozen=True)
class Event:
    event_id: str
    source: str
    title: str
    kind: str
    source_url: str
    scheduled_local_iso: str
    tz_name: str
    scheduled_utc: datetime
    first_seen_utc: datetime
    fetch_utc: datetime
    revision: int
    horizon_end_utc: datetime | None
    expires_utc: datetime
    press_end_utc: datetime | None = None
    status: str = "scheduled"
    revisions: tuple[Revision, ...] = ()
    note: str = ""

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id required")
        if not self.source:
            raise ValueError("source required")
        if self.kind not in EVENT_KINDS:
            raise ValueError(f"unknown kind: {self.kind!r}")
        if self.status not in EVENT_STATUSES:
            raise ValueError(f"unknown status: {self.status!r}")
        for name in ("scheduled_utc", "first_seen_utc", "fetch_utc",
                     "expires_utc"):
            moment = getattr(self, name)
            if moment.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.horizon_end_utc is not None and self.horizon_end_utc.tzinfo is None:
            raise ValueError("horizon_end_utc must be timezone-aware")
        if self.press_end_utc is not None:
            if self.press_end_utc.tzinfo is None:
                raise ValueError("press_end_utc must be timezone-aware")
            if self.press_end_utc <= self.scheduled_utc:
                raise ValueError("press_end_utc must be after scheduled_utc")
        if self.expires_utc <= self.scheduled_utc:
            raise ValueError("expires_utc must be after scheduled_utc")
        if self.revision < 0:
            raise ValueError("revision must be >= 0")
        object.__setattr__(self, "revisions", tuple(self.revisions))
        # Fail loudly when the stored UTC instant disagrees with the
        # wall-time + zone (catches EST/EDT mixups at load time).
        zone = ZoneInfo(self.tz_name or ET_NAME)
        wall = datetime.fromisoformat(self.scheduled_local_iso)
        if wall.tzinfo is not None:
            raise ValueError("scheduled_local_iso must be naive wall time")
        expect = to_utc(wall.replace(tzinfo=zone, fold=0))
        if expect != self.scheduled_utc:
            raise ValueError(
                f"{self.event_id}: scheduled_utc {self.scheduled_utc.isoformat()} "
                f"!= {self.scheduled_local_iso} {self.tz_name} "
                f"({expect.isoformat()})")

    def with_revision(self, scheduled_utc: datetime, fetch_utc: datetime,
                      note: str, changed: tuple[str, ...],
                      local_iso: str | None = None,
                      press_end_utc: datetime | None = None) -> Event:
        """Return a copy bumped to revision+1 with the change recorded."""
        import dataclasses

        rev = Revision(rev=self.revision + 1, fetched_utc=fetch_utc,
                       note=note, changed=tuple(changed))
        return dataclasses.replace(
            self,
            scheduled_local_iso=local_iso or self.scheduled_local_iso,
            scheduled_utc=scheduled_utc,
            fetch_utc=fetch_utc,
            revision=self.revision + 1,
            status="revised",
            press_end_utc=self.press_end_utc if press_end_utc is None
            else press_end_utc,
            revisions=self.revisions + (rev,))

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "source": self.source,
            "title": self.title,
            "kind": self.kind,
            "source_url": self.source_url,
            "scheduled_local_iso": self.scheduled_local_iso,
            "tz_name": self.tz_name,
            "scheduled_utc": self.scheduled_utc.isoformat(),
            "first_seen_utc": self.first_seen_utc.isoformat(),
            "fetch_utc": self.fetch_utc.isoformat(),
            "revision": self.revision,
            "horizon_end_utc": (self.horizon_end_utc.isoformat()
                                if self.horizon_end_utc else None),
            "expires_utc": self.expires_utc.isoformat(),
            "press_end_utc": (self.press_end_utc.isoformat()
                              if self.press_end_utc else None),
            "status": self.status,
            "revisions": [{"rev": r.rev,
                           "fetched_utc": r.fetched_utc.isoformat(),
                           "note": r.note, "changed": list(r.changed)}
                          for r in self.revisions],
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Event:
        return cls(
            event_id=data["event_id"], source=data["source"],
            title=data["title"], kind=data["kind"],
            source_url=data["source_url"],
            scheduled_local_iso=data["scheduled_local_iso"],
            tz_name=data.get("tz_name", ET_NAME),
            scheduled_utc=parse_iso_utc(data["scheduled_utc"]),
            first_seen_utc=parse_iso_utc(data["first_seen_utc"]),
            fetch_utc=parse_iso_utc(data["fetch_utc"]),
            revision=int(data.get("revision", 0)),
            horizon_end_utc=(parse_iso_utc(data["horizon_end_utc"])
                             if data.get("horizon_end_utc") else None),
            expires_utc=parse_iso_utc(data["expires_utc"]),
            press_end_utc=(parse_iso_utc(data["press_end_utc"])
                           if data.get("press_end_utc") else None),
            status=data.get("status", "scheduled"),
            revisions=tuple(
                Revision(rev=int(r["rev"]),
                         fetched_utc=parse_iso_utc(r["fetched_utc"]),
                         note=r.get("note", ""),
                         changed=tuple(r.get("changed", ())))
                for r in data.get("revisions", ())),
            note=data.get("note", ""))


@dataclass(frozen=True)
class SourceCoverage:
    source: str
    source_url: str
    horizon_end_utc: datetime | None
    fetched_utc: datetime
    expires_utc: datetime
    status: str = "fresh"
    last_error: str = ""
    verified_utc: datetime | None = None

    def __post_init__(self) -> None:
        if self.status not in COVERAGE_STATUSES:
            raise ValueError(f"unknown coverage status: {self.status!r}")
        for name in ("fetched_utc", "expires_utc"):
            if getattr(self, name).tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if (self.horizon_end_utc is not None
                and self.horizon_end_utc.tzinfo is None):
            raise ValueError("horizon_end_utc must be timezone-aware")
        if self.verified_utc is not None and self.verified_utc.tzinfo is None:
            raise ValueError("verified_utc must be timezone-aware")

    def to_dict(self) -> dict:
        return {
            "source": self.source, "source_url": self.source_url,
            "horizon_end_utc": (self.horizon_end_utc.isoformat()
                                if self.horizon_end_utc else None),
            "fetched_utc": self.fetched_utc.isoformat(),
            "expires_utc": self.expires_utc.isoformat(),
            "status": self.status, "last_error": self.last_error,
            "verified_utc": (self.verified_utc.isoformat()
                             if self.verified_utc else None),
        }

    @classmethod
    def from_dict(cls, data: dict) -> SourceCoverage:
        return cls(
            source=data["source"], source_url=data["source_url"],
            horizon_end_utc=(parse_iso_utc(data["horizon_end_utc"])
                             if data.get("horizon_end_utc") else None),
            fetched_utc=parse_iso_utc(data["fetched_utc"]),
            expires_utc=parse_iso_utc(data["expires_utc"]),
            status=data.get("status", "fresh"),
            last_error=data.get("last_error", ""),
            verified_utc=(parse_iso_utc(data["verified_utc"])
                          if data.get("verified_utc") else None))
