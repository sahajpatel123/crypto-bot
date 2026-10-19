"""Event store tests (Worker 4, EV-001). CRUD, revisions, coverage, persist."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.events.store import EventStore, coverage_status
from cryptobot.events.types import Event, SourceCoverage

T0 = datetime(2026, 10, 12, 13, 10, tzinfo=timezone.utc)


def _event(eid="E-1", when=None, rev=0, seen=None, local=None):
    when = when or datetime(2026, 10, 14, 12, 30, tzinfo=timezone.utc)
    return Event(
        event_id=eid, source="cpi", title=eid, kind="release",
        source_url="https://www.bls.gov/schedule/",
        scheduled_local_iso=local or "2026-10-14T08:30:00",
        tz_name="America/New_York",
        scheduled_utc=when, first_seen_utc=seen or T0, fetch_utc=T0,
        revision=rev,
        horizon_end_utc=datetime(2026, 12, 10, 13, 30,
                                 tzinfo=timezone.utc),
        expires_utc=when + timedelta(days=7))


def _coverage(status="fresh", fetched=None, horizon=None):
    fetched = fetched or T0
    return SourceCoverage(
        source="cpi", source_url="https://www.bls.gov/schedule/",
        horizon_end_utc=horizon or datetime(2026, 12, 10, 13, 30,
                                            tzinfo=timezone.utc),
        fetched_utc=fetched, expires_utc=fetched + timedelta(hours=24),
        status=status)


def test_upsert_get_and_ordering():
    store = EventStore()
    late = _event("B", datetime(2026, 11, 10, 13, 30, tzinfo=timezone.utc),
                  local="2026-11-10T08:30:00")
    early = _event("A")
    store.upsert(late)
    store.upsert(early)
    assert [e.event_id for e in store.all()] == ["A", "B"]
    assert store.get("A") == early
    assert store.get("missing") is None
    assert len(store) == 2


def test_between_and_by_source():
    store = EventStore()
    store.upsert(_event("A"))
    fomc = Event.from_dict({**_event("F").to_dict(), "source": "fomc",
                            "event_id": "F"})
    store.upsert(fomc)
    assert [e.event_id for e in store.by_source("fomc")] == ["F"]
    window = store.between(datetime(2026, 10, 14, 12, 0,
                                    tzinfo=timezone.utc),
                           datetime(2026, 10, 14, 13, 0,
                                    tzinfo=timezone.utc))
    assert {e.event_id for e in window} == {"A", "F"}


def test_revision_monotonic_and_first_seen_immutable():
    store = EventStore()
    store.upsert(_event(rev=1))
    with pytest.raises(ValueError, match="backwards"):
        store.upsert(_event(rev=0))
    moved = _event(rev=1, seen=T0 + timedelta(hours=1))
    with pytest.raises(ValueError, match="first_seen"):
        store.upsert(moved)


def test_with_revision_records_change():
    event = _event()
    bumped = event.with_revision(
        datetime(2026, 10, 14, 12, 30, tzinfo=timezone.utc),
        T0 + timedelta(hours=1), "rescheduled press end",
        ("press_end_utc",))
    assert bumped.revision == 1
    assert bumped.status == "revised"
    assert bumped.first_seen_utc == T0
    assert bumped.revisions[-1].note == "rescheduled press end"


def test_coverage_states():
    assert coverage_status(None, T0) == "unknown"
    assert coverage_status(_coverage("outage"), T0) == "outage"
    assert coverage_status(_coverage("not-implemented"), T0) == \
        "not-implemented"
    # W4-24H: cached/unverified caches never read fresh.
    assert coverage_status(_coverage("cached"), T0) == "cached"
    assert coverage_status(_coverage("unverified"), T0) == "unverified"
    assert coverage_status(_coverage(), T0) == "fresh"
    assert coverage_status(_coverage(), T0 + timedelta(hours=25)) == "stale"
    past = _coverage(horizon=T0 - timedelta(hours=1))
    assert coverage_status(past, T0) == "expired-horizon"
    with pytest.raises(ValueError, match="timezone-aware"):
        coverage_status(_coverage(), datetime(2026, 1, 1))


def test_json_round_trip(tmp_path):
    store = EventStore()
    store.upsert(_event().with_revision(
        datetime(2026, 10, 14, 12, 30, tzinfo=timezone.utc),
        T0 + timedelta(hours=1), "n", ("title",)))
    store.set_coverage(_coverage())
    path = tmp_path / "events.json"
    store.save_json(path)
    loaded = EventStore.load_json(path)
    assert loaded.get("E-1") == store.get("E-1")
    assert loaded.coverage("cpi") == store.coverage("cpi")
    assert loaded.snapshot_meta() == {"format": "cryptobot-events/1",
                                      "events": 1, "sources": ["cpi"]}


def test_bad_format_rejected(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"format": "nope"}', encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported"):
        EventStore.load_json(path)


def test_prune_drops_expired_only():
    store = EventStore()
    store.upsert(_event("OLD"))
    store.upsert(_event("NEW", datetime(2027, 1, 5, 13, 30,
                                        tzinfo=timezone.utc),
                        local="2027-01-05T08:30:00"))
    pruned = store.prune(datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert pruned == ["OLD"]
    assert store.get("NEW") is not None
