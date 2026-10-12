"""Event gate tests (Worker 4, EV-001). Windows + fail-closed coverage."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.events.gate import EventGate, GateConfig
from cryptobot.events.sources import (
    CpiSource,
    FomcSource,
    StubAdapter,
    apply_snapshot,
)
from cryptobot.events.store import EventStore


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def _live_store(now):
    store = EventStore()
    apply_snapshot(store, FomcSource().load(now))
    apply_snapshot(store, CpiSource().load(now))
    return store


def test_quiet_day_is_clear():
    now = _utc(2026, 10, 12, 13, 10)
    decision = EventGate(_live_store(now)).check(now)
    assert decision.blocked is False
    assert decision.reason == "event:clear"


def test_cpi_pre_window_edges():
    now = _utc(2026, 10, 14, 12, 0)
    gate = EventGate(_live_store(now))
    assert gate.check(_utc(2026, 10, 14, 12, 14, 59)).reason == "event:clear"
    pre = gate.check(_utc(2026, 10, 14, 12, 15))
    assert pre.blocked is True
    assert pre.reason == "event:pre-window:CPI-2026-10-14"


def test_cpi_in_window_through_post_buffer():
    now = _utc(2026, 10, 14, 12, 30)
    gate = EventGate(_live_store(now))
    assert gate.check(_utc(2026, 10, 14, 12, 30)).reason == \
        "event:in-window:CPI-2026-10-14"
    assert gate.check(_utc(2026, 10, 14, 12, 45)).reason == \
        "event:in-window:CPI-2026-10-14"
    assert gate.check(_utc(2026, 10, 14, 12, 45, 1)).reason == "event:clear"


def test_cooldown_extends_post_window():
    now = _utc(2026, 10, 14, 12, 30)
    gate = EventGate(_live_store(now),
                     GateConfig(resume_cooldown_s=600))
    post = gate.check(_utc(2026, 10, 14, 12, 50))
    assert post.blocked is True
    assert post.reason == "event:post-window:CPI-2026-10-14"
    assert gate.check(_utc(2026, 10, 14, 12, 55, 1)).reason == "event:clear"


def test_fomc_decision_to_press_is_continuous():
    # Decision 18:00 -> block 17:45-18:15; press 18:30 -> block
    # 18:15-19:45. No gap an entry can slip through.
    now = _utc(2026, 9, 16, 18, 0)
    gate = EventGate(_live_store(now))
    assert gate.check(_utc(2026, 9, 16, 17, 44, 59)).reason == "event:clear"
    assert gate.check(_utc(2026, 9, 16, 17, 50)).reason == \
        "event:pre-window:FOMC-2026-09-16-decision"
    assert gate.check(_utc(2026, 9, 16, 18, 5)).reason == \
        "event:in-window:FOMC-2026-09-16-decision"
    assert gate.check(_utc(2026, 9, 16, 18, 15)).blocked is True
    assert gate.check(_utc(2026, 9, 16, 18, 45)).reason == \
        "event:press-window:FOMC-2026-09-16-press"
    assert gate.check(_utc(2026, 9, 16, 19, 45)).blocked is True
    assert gate.check(_utc(2026, 9, 16, 19, 45, 1)).reason == "event:clear"


def test_window_end_covers_all_hits():
    now = _utc(2026, 9, 16, 18, 15)
    decision = EventGate(_live_store(now)).check(now)
    assert decision.blocked is True
    assert decision.window_end_utc == _utc(2026, 9, 16, 19, 45)
    assert set(decision.event_ids) == {"FOMC-2026-09-16-decision",
                                       "FOMC-2026-09-16-press"}


def test_unknown_coverage_blocks():
    gate = EventGate(EventStore())
    decision = gate.check(_utc(2026, 10, 12, 13, 10))
    assert decision.blocked is True
    assert decision.reason == "event:stale-source:fomc:unknown"


def test_outage_blocks_with_explicit_reason():
    fomc = FomcSource()
    fomc.force_outage("403 from calendar")
    store = EventStore()
    apply_snapshot(store, fomc.load(_utc(2026, 10, 12, 13, 10)))
    apply_snapshot(store, CpiSource().load(_utc(2026, 10, 12, 13, 10)))
    decision = EventGate(store).check(_utc(2026, 10, 12, 13, 10))
    assert decision.blocked is True
    assert decision.reason == "event:stale-source:fomc:outage"


def test_stale_fetch_blocks_after_ttl():
    loaded = _utc(2026, 10, 12, 13, 10)
    gate = EventGate(_live_store(loaded))
    decision = gate.check(loaded + timedelta(hours=25))
    assert decision.blocked is True
    assert decision.reason == "event:stale-source:fomc:stale"


def test_elapsed_horizon_blocks():
    loaded = _utc(2026, 12, 11, 12, 0)
    gate = EventGate(_live_store(loaded))
    decision = gate.check(loaded)
    assert decision.blocked is True
    assert "expired-horizon" in decision.reason


def test_required_stub_blocks_optional_stub_ignored():
    now = _utc(2026, 10, 12, 13, 10)
    store = _live_store(now)
    apply_snapshot(store, StubAdapter(
        "employment", "https://www.bls.gov/schedule/").load(now))
    strict = EventGate(store, GateConfig(
        required_sources=("fomc", "cpi", "employment")))
    assert strict.check(now).reason == \
        "event:stale-source:employment:not-implemented"
    relaxed = EventGate(store)
    assert relaxed.check(now).reason == "event:clear"


def test_upcoming_prepare_flat():
    now = _utc(2026, 10, 14, 11, 0)
    gate = EventGate(_live_store(now))
    upcoming = gate.upcoming(now, 7200)
    assert [(u.event.event_id, u.action) for u in upcoming] == [
        ("CPI-2026-10-14", "prepare-flat")]
    assert upcoming[0].window_start_utc == _utc(2026, 10, 14, 12, 15)
    assert gate.upcoming(_utc(2026, 10, 1, 12, 0), 3600) == []


def test_cancelled_events_never_block():
    now = _utc(2026, 10, 14, 12, 30)
    store = _live_store(now)
    event = store.get("CPI-2026-10-14")
    import dataclasses
    store.upsert(dataclasses.replace(event, status="cancelled"))
    assert EventGate(store).check(now).reason == "event:clear"


def test_active_lists_in_window_events():
    now = _utc(2026, 9, 16, 18, 15)
    actives = EventGate(_live_store(now)).active(now)
    assert {e.event_id for e in actives} == {
        "FOMC-2026-09-16-decision", "FOMC-2026-09-16-press"}


def test_gate_has_no_exit_api_by_design():
    public = [name for name in dir(EventGate) if not name.startswith("_")]
    for name in public:
        lowered = name.lower()
        assert "exit" not in lowered, name
        assert "flatten" not in lowered, name
        assert "liquidat" not in lowered, name
        assert "cancel" not in lowered, name
        assert "close" not in lowered, name
