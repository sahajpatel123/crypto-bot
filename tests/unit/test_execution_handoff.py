"""v0.1.1 risk→execution handoff + F-E001 fixes (Worker 2, E-003).

Recording stub is built against the manager-owned RiskOutcomeSink Protocol;
a conformance assert pins the drop-in shape for the future V-001 wiring.
Deterministic: fake venue, injected clock, tmp logs — no network/creds/randomness.
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

from cryptobot.coordination import RiskOutcomeSink
from cryptobot.execution import FakeVenue, OrderManager, OrderState

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class RecordingSink:
    """Test double for the risk-side outcome surface (E-003 recording stub)."""

    def __init__(self):
        self.calls = []

    def note_fill(self, reservation_id):
        self.calls.append(("fill", reservation_id))

    def release(self, reservation_id):
        self.calls.append(("release", reservation_id))
        return True

    def note_flat(self):
        self.calls.append(("flat",))


def _manager(venue, tmp_path, sink=None, **kw):
    clock = kw.pop("clock", lambda: NOW)
    return OrderManager(venue, log_path=tmp_path / "orders.jsonl", now_utc=clock,
                        outcome_sink=sink, **kw)


def _expiring():
    return NOW + timedelta(seconds=60)


# -- stub conformance ------------------------------------------------------

def test_recording_stub_satisfies_outcome_protocol():
    sink = RecordingSink()
    assert isinstance(sink, RiskOutcomeSink)


# -- reservation threading -------------------------------------------------

def test_reservation_threads_onto_entry_and_siblings(tmp_path):
    venue = FakeVenue()
    venue.set_last_price("BTCUSDT", 67000.0)
    manager = _manager(venue, tmp_path, RecordingSink())
    entry = manager.submit_entry("BTCUSDT", "LONG", 0.01, 67005.0,
                                 expire_at_utc=_expiring(), reservation_id="r1")
    assert entry.reservation_id == "r1"
    stop, target = manager.attach_siblings(entry, stop_price=66850.0, target_price=67200.0)
    assert (stop.reservation_id, target.reservation_id) == ("r1", "r1")


def test_retry_chain_shares_one_reservation(tmp_path):
    venue = FakeVenue()
    venue.set_last_price("BTCUSDT", 67000.0)
    venue.fail_next_submit("timeout", received=False)
    manager = _manager(venue, tmp_path, RecordingSink())
    order = manager.submit_with_retry("BTCUSDT", "LONG", 0.01, 67005.0,
                                      expire_at_utc=_expiring(), reservation_id="r1")
    first_id = order.retry_of
    assert first_id is not None
    assert manager.orders[first_id].reservation_id == "r1" == order.reservation_id


# -- exactly-once callbacks --------------------------------------------------

def test_fill_fires_exactly_once(tmp_path):
    venue = FakeVenue()
    venue.set_last_price("BTCUSDT", 67000.0)
    sink = RecordingSink()
    manager = _manager(venue, tmp_path, sink)
    order = manager.submit_entry("BTCUSDT", "LONG", 0.01, 67005.0,
                                 expire_at_utc=_expiring(), reservation_id="r1")
    assert sink.calls == [("fill", "r1")]
    manager.poll()
    manager.reconcile(order.client_id)
    manager.poll()
    assert sink.calls == [("fill", "r1")]


def test_reject_releases_exactly_once(tmp_path):
    venue = FakeVenue()
    venue.fail_next_submit("reject", reason="MARGIN")
    sink = RecordingSink()
    manager = _manager(venue, tmp_path, sink)
    manager.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                         expire_at_utc=_expiring(), reservation_id="r2")
    assert sink.calls == [("release", "r2")]
    manager.poll()
    assert sink.calls == [("release", "r2")]


def test_expiry_releases_without_stranding(tmp_path):
    venue = FakeVenue()
    sink = RecordingSink()
    manager = _manager(venue, tmp_path, sink)
    manager.submit_entry("BTCUSDT", "LONG", 0.01, 67005.0,
                         expire_at_utc=_expiring(), kind="STOP_MARKET",
                         reservation_id="r3")
    assert sink.calls == []  # live reservation: no callback yet.
    manager.poll(NOW + timedelta(seconds=61))
    assert sink.calls == [("release", "r3")]  # freed at expiry, never stranded.
    manager.poll(NOW + timedelta(seconds=120))
    assert sink.calls == [("release", "r3")]


def test_flat_fires_once_when_protective_leg_fills(tmp_path):
    venue = FakeVenue()
    venue.set_last_price("BTCUSDT", 67000.0)
    sink = RecordingSink()
    manager = _manager(venue, tmp_path, sink)
    entry = manager.submit_entry("BTCUSDT", "LONG", 0.01, 67005.0,
                                 expire_at_utc=_expiring(), reservation_id="r1")
    manager.attach_siblings(entry, stop_price=66850.0, target_price=67200.0)
    assert sink.calls == [("fill", "r1")]  # open, not flat.
    venue.set_last_price("BTCUSDT", 66800.0)
    manager.poll()
    assert sink.calls == [("fill", "r1"), ("flat",)]
    manager.poll()
    assert sink.calls == [("fill", "r1"), ("flat",)]


def test_no_sink_no_callbacks_no_crash(tmp_path):
    venue = FakeVenue()
    venue.set_last_price("BTCUSDT", 67000.0)
    manager = _manager(venue, tmp_path)  # outcome_sink=None.
    order = manager.submit_entry("BTCUSDT", "LONG", 0.01, 67005.0,
                                 expire_at_utc=_expiring(), reservation_id="r1")
    assert order.reservation_id == "r1"
    manager.poll()


# -- halt → exit-only ----------------------------------------------------------

def test_halt_blocks_entries_but_not_protective_exits(tmp_path):
    venue = FakeVenue()
    venue.set_last_price("BTCUSDT", 67000.0)
    manager = _manager(venue, tmp_path, RecordingSink())
    entry = manager.submit_entry("BTCUSDT", "LONG", 0.01, 67005.0,
                                 expire_at_utc=_expiring(), reservation_id="r1")
    manager.set_halted(True, reason="daily-halt-test")
    with pytest.raises(PermissionError, match="exit-only"):
        manager.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                             expire_at_utc=_expiring(), reservation_id="r2")
    stop, _ = manager.attach_siblings(entry, stop_price=66850.0, target_price=67200.0)
    assert stop.state in (OrderState.OPEN, OrderState.PARTIAL)  # exits proceed.
    manager.poll()  # exposure management proceeds.


def test_halt_level_persists_across_restart_until_cleared(tmp_path):
    venue = FakeVenue()
    manager = _manager(venue, tmp_path, RecordingSink())
    manager.set_halted(True, reason="halt-test")
    manager.set_halted(True, reason="halt-test")  # level, not edge: no duplicate record.
    log_text = (tmp_path / "orders.jsonl").read_text()
    assert log_text.count("halt-engaged") == 1
    recovered = OrderManager.recover(venue, tmp_path / "orders.jsonl", now_utc=lambda: NOW,
                                     outcome_sink=RecordingSink())
    assert recovered.exit_only is True
    with pytest.raises(PermissionError, match="exit-only"):
        recovered.submit_entry("BTCUSDT", "LONG", 0.01, 1.0, expire_at_utc=_expiring())
    recovered.clear_halt_via_reconciliation()
    assert recovered.exit_only is False
    recovered.submit_entry("BTCUSDT", "LONG", 0.01, 1.0, expire_at_utc=_expiring(),
                           kind="STOP_MARKET")


# -- recovery: reservations + orphans (F-E001-02) -------------------------------

def test_recovery_releases_reservation_with_no_live_order(tmp_path):
    venue = FakeVenue()
    first = _manager(venue, tmp_path)  # no sink: release falls due unobserved.
    first.submit_entry("BTCUSDT", "LONG", 0.01, 67005.0,
                       expire_at_utc=_expiring(), kind="STOP_MARKET", reservation_id="r9")
    first.poll(NOW + timedelta(seconds=61))  # expired; no sink to tell.
    sink = RecordingSink()
    OrderManager.recover(venue, tmp_path / "orders.jsonl", now_utc=lambda: NOW, outcome_sink=sink)
    assert sink.calls == [("release", "r9")]
    log_text = (tmp_path / "orders.jsonl").read_text()
    assert "no-live-order" in log_text


def test_recovery_never_refires_callbacks(tmp_path):
    venue = FakeVenue()
    venue.set_last_price("BTCUSDT", 67000.0)
    sink_a = RecordingSink()
    manager = _manager(venue, tmp_path, sink_a)
    manager.submit_entry("BTCUSDT", "LONG", 0.01, 67005.0,
                         expire_at_utc=_expiring(), reservation_id="r1")
    assert sink_a.calls == [("fill", "r1")]
    sink_b = RecordingSink()  # fresh post-restart sink sees nothing repeated.
    recovered = OrderManager.recover(venue, tmp_path / "orders.jsonl", now_utc=lambda: NOW,
                                     outcome_sink=sink_b)
    recovered.poll()
    assert sink_b.calls == []


def test_orphan_sweep_cancels_venue_order_with_no_local_record(tmp_path):
    venue = FakeVenue()
    venue.set_last_price("BTCUSDT", 67000.0)
    # Simulate the F-E001-02 crash window: venue.submit landed, _log never ran.
    venue.submit("ghost-1", "BTCUSDT", "SELL", "STOP_MARKET", 0.01, stop_price=66850.0)
    venue.submit("ghost-2", "BTCUSDT", "BUY", "MARKET", 0.01)  # fills: terminal stranger.
    manager = _manager(venue, tmp_path, RecordingSink())
    swept = manager.sweep_venue_orphans()
    assert swept == ["ghost-1"]
    assert venue.query("ghost-1").status == "CANCELLED"
    assert venue.query("ghost-2").status == "FILLED"  # terminal: observed, untouched.
    log_text = (tmp_path / "orders.jsonl").read_text()
    assert "orphan-swept" in log_text and "orphan-observed-terminal" in log_text


def test_recover_runs_orphan_sweep(tmp_path):
    venue = FakeVenue()
    manager = _manager(venue, tmp_path, RecordingSink())
    manager.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                         expire_at_utc=_expiring(), kind="STOP_MARKET")
    venue.submit("ghost-3", "BTCUSDT", "SELL", "STOP_MARKET", 0.01, stop_price=1.0)
    OrderManager.recover(venue, tmp_path / "orders.jsonl", now_utc=lambda: NOW,
                         outcome_sink=RecordingSink())
    assert venue.query("ghost-3").status == "CANCELLED"


def test_log_append_fsyncs_every_record(tmp_path, monkeypatch):
    calls = []
    real_fsync = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: calls.append(fd) or real_fsync(fd))
    venue = FakeVenue()
    venue.set_last_price("BTCUSDT", 67000.0)
    manager = _manager(venue, tmp_path, RecordingSink())
    manager.submit_entry("BTCUSDT", "LONG", 0.01, 67005.0,
                         expire_at_utc=_expiring(), reservation_id="r1")
    assert len(calls) >= 2  # submitted + callback-fired records, each fsynced.


# -- F-E001-04 / F-E001-05 ---------------------------------------------------------

def test_market_submit_without_price_reference_raises_cleanly(tmp_path):
    venue = FakeVenue()  # no set_last_price: no reference exists.
    with pytest.raises(ValueError, match="no price reference"):
        venue.submit("c1", "BTCUSDT", "BUY", "MARKET", 0.01)
    assert venue.query("c1") is None  # rejected before storing: no residue.
    assert venue.list_orders() == []


def test_siblings_never_expire_m1_accepted_live_note(tmp_path):
    # F-E001-05 pin: entries expire; protective legs do not (M1-accepted, live needs leg policy).
    venue = FakeVenue()
    venue.set_last_price("BTCUSDT", 67000.0)
    manager = _manager(venue, tmp_path, RecordingSink())
    entry = manager.submit_entry("BTCUSDT", "LONG", 0.01, 67005.0,
                                 expire_at_utc=_expiring(), reservation_id="r1")
    stop, target = manager.attach_siblings(entry, stop_price=66850.0, target_price=67200.0)
    manager.poll(NOW + timedelta(days=30))
    assert (stop.state, target.state) == (OrderState.OPEN, OrderState.OPEN)
