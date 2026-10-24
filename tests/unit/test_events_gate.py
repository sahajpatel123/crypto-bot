"""Event gate tests (Worker 4, EV-001). Windows + fail-closed coverage."""
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import cryptobot.events as _evpkg  # noqa: E402
from cryptobot.events.freshness import FreshnessTracker, HttpResponse  # noqa: E402
from cryptobot.events.gate import EventGate, GateConfig  # noqa: E402
from cryptobot.events.sources import (  # noqa: E402
    CpiSource,
    FomcSource,
    StubAdapter,
    apply_snapshot,
)
from cryptobot.events.store import EventStore  # noqa: E402

CANNED = Path(_evpkg.__file__).parent / "fixtures" / "canned"


def _utc(*args):
    return datetime(*args, tzinfo=UTC)


def _canned(http_url, timeout_s=20):
    name = ("fomc_page_2026.txt" if "federalreserve" in http_url
            else "bls_cpi_page_2026.txt")
    return HttpResponse(status=200,
                        body=(CANNED / name).read_bytes(), url=http_url)


def _live_store(now, tmp_path):
    """Verified store via the real tracker path (W4-24H).

    Local load alone is unverified; verification runs through
    refresh_once() with canned official pages (no network).
    """
    store = EventStore()
    tracker = FreshnessTracker(tmp_path / "state.json",
                               [FomcSource(), CpiSource()])
    tracker.local_load(store, now)
    results = tracker.refresh_once(store, _canned, now)
    assert all(r.ok for r in results.values())
    return store


def test_quiet_day_is_clear(tmp_path):
    now = _utc(2026, 10, 12, 13, 10)
    decision = EventGate(_live_store(now, tmp_path)).check(now)
    assert decision.blocked is False
    assert decision.reason == "event:clear"


def test_cpi_pre_window_edges(tmp_path):
    # REL-W3: admission cutoff = window start (12:15) - max_hold (300s)
    # - exit budget (120s) = 12:08:00. Entries stop there, not at the
    # window, so the full hold + orderly exit fit before the window.
    now = _utc(2026, 10, 14, 12, 0)
    gate = EventGate(_live_store(now, tmp_path))
    assert gate.check(_utc(2026, 10, 14, 12, 7, 59)).reason == "event:clear"
    cutoff = gate.check(_utc(2026, 10, 14, 12, 8))
    assert cutoff.blocked is True
    assert cutoff.reason == "event:pre-window:CPI-2026-10-14"
    pre = gate.check(_utc(2026, 10, 14, 12, 15))
    assert pre.blocked is True
    assert pre.reason == "event:pre-window:CPI-2026-10-14"


def test_cpi_in_window_through_post_buffer(tmp_path):
    now = _utc(2026, 10, 14, 12, 30)
    gate = EventGate(_live_store(now, tmp_path))
    assert gate.check(_utc(2026, 10, 14, 12, 30)).reason == \
        "event:in-window:CPI-2026-10-14"
    assert gate.check(_utc(2026, 10, 14, 12, 45)).reason == \
        "event:in-window:CPI-2026-10-14"
    assert gate.check(_utc(2026, 10, 14, 12, 45, 1)).reason == "event:clear"


def test_cooldown_extends_post_window(tmp_path):
    now = _utc(2026, 10, 14, 12, 30)
    gate = EventGate(_live_store(now, tmp_path),
                     GateConfig(resume_cooldown_s=600))
    post = gate.check(_utc(2026, 10, 14, 12, 50))
    assert post.blocked is True
    assert post.reason == "event:post-window:CPI-2026-10-14"
    assert gate.check(_utc(2026, 10, 14, 12, 55, 1)).reason == "event:clear"


def test_fomc_decision_to_press_is_continuous(tmp_path):
    # Decision 18:00 -> block 17:45-18:15; press 18:30 -> block
    # 18:15-19:45. No gap an entry can slip through.
    now = _utc(2026, 9, 16, 18, 0)
    gate = EventGate(_live_store(now, tmp_path))
    # REL-W3: cutoff = 17:45 window start - 420s = 17:38:00.
    assert gate.check(_utc(2026, 9, 16, 17, 37, 59)).reason == "event:clear"
    assert gate.check(_utc(2026, 9, 16, 17, 38)).reason == \
        "event:pre-window:FOMC-2026-09-16-decision"
    assert gate.check(_utc(2026, 9, 16, 17, 50)).reason == \
        "event:pre-window:FOMC-2026-09-16-decision"
    assert gate.check(_utc(2026, 9, 16, 18, 5)).reason == \
        "event:in-window:FOMC-2026-09-16-decision"
    assert gate.check(_utc(2026, 9, 16, 18, 15)).blocked is True
    assert gate.check(_utc(2026, 9, 16, 18, 45)).reason == \
        "event:press-window:FOMC-2026-09-16-press"
    assert gate.check(_utc(2026, 9, 16, 19, 45)).blocked is True
    assert gate.check(_utc(2026, 9, 16, 19, 45, 1)).reason == "event:clear"


def test_window_end_covers_all_hits(tmp_path):
    now = _utc(2026, 9, 16, 18, 15)
    decision = EventGate(_live_store(now, tmp_path)).check(now)
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


def test_stale_fetch_blocks_after_ttl(tmp_path):
    # W4-24H: verified cache lives 7 days; only past-TTL reads stale.
    loaded = _utc(2026, 10, 12, 13, 10)
    gate = EventGate(_live_store(loaded, tmp_path))
    assert gate.check(loaded + timedelta(hours=25)).reason == "event:clear"
    decision = gate.check(loaded + timedelta(days=8))
    assert decision.blocked is True
    assert decision.reason == "event:stale-source:fomc:stale"


def test_elapsed_horizon_blocks(tmp_path):
    loaded = _utc(2026, 12, 11, 12, 0)
    gate = EventGate(_live_store(loaded, tmp_path))
    decision = gate.check(loaded)
    assert decision.blocked is True
    assert "expired-horizon" in decision.reason


def test_required_stub_blocks_optional_stub_ignored(tmp_path):
    now = _utc(2026, 10, 12, 13, 10)
    store = _live_store(now, tmp_path)
    apply_snapshot(store, StubAdapter(
        "employment", "https://www.bls.gov/schedule/").load(now))
    strict = EventGate(store, GateConfig(
        required_sources=("fomc", "cpi", "employment")))
    assert strict.check(now).reason == \
        "event:stale-source:employment:not-implemented"
    relaxed = EventGate(store)
    assert relaxed.check(now).reason == "event:clear"


def test_upcoming_prepare_flat(tmp_path):
    now = _utc(2026, 10, 14, 11, 0)
    gate = EventGate(_live_store(now, tmp_path))
    upcoming = gate.upcoming(now, 7200)
    assert [(u.event.event_id, u.action) for u in upcoming] == [
        ("CPI-2026-10-14", "prepare-flat")]
    assert upcoming[0].window_start_utc == _utc(2026, 10, 14, 12, 15)
    assert gate.upcoming(_utc(2026, 10, 1, 12, 0), 3600) == []


def test_cancelled_events_never_block(tmp_path):
    now = _utc(2026, 10, 14, 12, 30)
    store = _live_store(now, tmp_path)
    event = store.get("CPI-2026-10-14")
    import dataclasses
    store.upsert(dataclasses.replace(event, status="cancelled"))
    assert EventGate(store).check(now).reason == "event:clear"


def test_active_lists_in_window_events(tmp_path):
    now = _utc(2026, 9, 16, 18, 15)
    actives = EventGate(_live_store(now, tmp_path)).active(now)
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
