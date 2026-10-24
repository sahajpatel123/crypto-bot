"""Event source tests (Worker 4, EV-001). Fixtures + outage explicitness."""
import sys
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.events.sources import (
    CpiSource,
    FixtureAdapter,
    FomcSource,
    StubAdapter,
    apply_snapshot,
)
from cryptobot.events.store import EventStore

T0 = datetime(2026, 10, 12, 13, 10, tzinfo=UTC)
ET = ZoneInfo("America/New_York")


def test_fomc_fixture_counts_and_ids():
    snap = FomcSource().load(T0)
    # W4-24H: a local load is cached, never a verified fetch.
    assert snap.status == "cached"
    assert snap.source == "fomc"
    assert snap.source_url == ("https://www.federalreserve.gov/"
                              "monetarypolicy/fomccalendars.htm")
    assert len(snap.events) == 16
    kinds = [e.kind for e in snap.events]
    assert kinds.count("decision") == 8
    assert kinds.count("press-conference") == 8
    ids = {e.event_id for e in snap.events}
    assert "FOMC-2026-09-16-decision" in ids
    assert "FOMC-2026-10-28-press" in ids
    assert "FOMC-2026-12-09-decision" in ids
    assert snap.horizon_end_utc == datetime(2026, 12, 9, 20, 30,
                                            tzinfo=UTC)


def test_fomc_decision_days_match_official_calendar():
    snap = FomcSource().load(T0)
    days = sorted(e.scheduled_local_iso[:10] for e in snap.events
                  if e.kind == "decision")
    assert days == ["2026-01-28", "2026-03-18", "2026-04-29",
                    "2026-06-17", "2026-07-29", "2026-09-16",
                    "2026-10-28", "2026-12-09"]
    for event in snap.events:
        wall = datetime.fromisoformat(event.scheduled_local_iso)
        if event.kind == "decision":
            assert (wall.hour, wall.minute) == (14, 0)
        else:
            assert (wall.hour, wall.minute) == (14, 30)


def test_cpi_fixture_dates_and_release_time():
    snap = CpiSource().load(T0)
    # W4-24H: a local load is cached, never a verified fetch.
    assert snap.status == "cached"
    # REL-W3: program page; the BLS index no longer carries schedules
    # (verified live 2026-10-14).
    assert snap.source_url == "https://www.bls.gov/schedule/news_release/cpi.htm"
    assert len(snap.events) == 12
    days = [e.scheduled_local_iso[:10] for e in snap.events]
    assert days == ["2026-01-13", "2026-02-13", "2026-03-11",
                    "2026-04-10", "2026-05-12", "2026-06-10",
                    "2026-07-14", "2026-08-12", "2026-09-11",
                    "2026-10-14", "2026-11-10", "2026-12-10"]
    for event in snap.events:
        wall = datetime.fromisoformat(event.scheduled_local_iso)
        assert (wall.hour, wall.minute) == (8, 30)
    assert snap.horizon_end_utc == datetime(2026, 12, 10, 13, 30,
                                            tzinfo=UTC)


def test_every_fixture_instant_matches_wall_plus_zone():
    # Full DST audit: recompute each stored UTC instant independently.
    for snap in (FomcSource().load(T0), CpiSource().load(T0)):
        for event in snap.events:
            wall = datetime.fromisoformat(
                event.scheduled_local_iso).replace(tzinfo=ET)
            assert wall.astimezone(UTC) == event.scheduled_utc, \
                event.event_id
            if event.press_end_utc is not None:
                assert event.press_end_utc > event.scheduled_utc


def test_forced_outage_is_explicit():
    adapter = FomcSource()
    adapter.force_outage("connection refused")
    snap = adapter.load(T0)
    assert snap.status == "outage"
    assert snap.events == ()
    assert "refused" in snap.error
    store = EventStore()
    apply_snapshot(store, snap)
    assert len(store) == 0
    assert store.coverage("fomc").status == "outage"


def test_missing_fixture_is_outage_not_empty_calendar():
    adapter = FixtureAdapter("nope", "https://example.invalid/x",
                             "does-not-exist.json")
    snap = adapter.load(T0)
    assert snap.status == "outage"
    assert snap.events == ()
    assert snap.error != ""


def test_stub_source_is_explicitly_not_implemented():
    snap = StubAdapter("employment",
                       "https://www.bls.gov/schedule/").load(T0)
    assert snap.status == "not-implemented"
    assert snap.events == ()
    assert snap.horizon_end_utc is None
    assert "not-implemented" in snap.error or "EV-001" in snap.error


def test_apply_snapshot_loads_events_and_coverage():
    store = EventStore()
    apply_snapshot(store, FomcSource().load(T0))
    apply_snapshot(store, CpiSource().load(T0))
    assert len(store) == 28
    # W4-24H: direct apply of a local read is explicitly unverified.
    assert store.status_at(T0) == {"fomc": "unverified",
                                   "cpi": "unverified"}
    assert store.get("CPI-2026-10-14").scheduled_utc == datetime(
        2026, 10, 14, 12, 30, tzinfo=UTC)
