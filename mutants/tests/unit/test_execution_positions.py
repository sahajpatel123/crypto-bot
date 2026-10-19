"""Fill deltas, positions, protection, settle window (Worker 2, E-005).

v0.2.0 execution side: exec-id delta records (fsync before sink call),
fill-first semantics, expiry settle window, top-up protection, overfill
freeze, bot-owned sweep scope. The recording stub implements the published
addendum signature and validates every delta like risk/ledger must.
Deterministic: fake venue + injected clock + tmp logs.
"""
import math
from datetime import datetime, timedelta, timezone

import pytest

from cryptobot.execution import FakeVenue, OrderManager, OrderState

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class RecordingSinkV2:
    """v0.2.0 recording stub: full delta signature with risk-side validation."""

    def __init__(self):
        self.calls = []
        self.deltas = []

    def note_fill(self, reservation_id):
        self.calls.append(("fill", reservation_id))

    def release(self, reservation_id):
        self.calls.append(("release", reservation_id))
        return True

    def note_flat(self):
        self.calls.append(("flat",))

    def note_fill_delta(self, reservation_id, exec_id, symbol, venue_side, qty, price, fee, ts_utc):
        assert math.isfinite(qty) and qty > 0, "delta qty must be positive finite"
        assert math.isfinite(price) and price >= 0, "delta price must be finite non-negative"
        assert math.isfinite(fee) and fee >= 0, "delta fee must be finite non-negative"
        assert venue_side in ("BUY", "SELL"), "unknown venue side"
        parsed = datetime.fromisoformat(ts_utc)
        assert parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0), "ts must be UTC-aware"
        self.deltas.append({"reservation_id": reservation_id, "exec_id": exec_id,
                            "symbol": symbol, "venue_side": venue_side,
                            "qty": qty, "price": price, "fee": fee})
        self.calls.append(("delta", exec_id))


class RecordingSinkV11:
    """v0.1.1-only stub (no note_fill_delta): exercises the hasattr fallback."""

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


def _log_text(tmp_path):
    return (tmp_path / "orders.jsonl").read_text()


# -- deltas ---------------------------------------------------------------

def test_each_increment_mints_propagated_exec_delta(tmp_path):
    venue = FakeVenue()
    venue.fail_next_submit("partial", fractions=(0.5, 0.5))
    sink = RecordingSinkV2()
    manager = _manager(venue, tmp_path, sink)
    order = manager.submit_entry("BTCUSDT", "LONG", 2.0, 100.0,
                                 expire_at_utc=_expiring(), reservation_id="r1")
    assert len(sink.deltas) == 1
    first = sink.deltas[0]
    assert first["exec_id"] == f"{order.client_id}:fill:0001"
    assert (first["qty"], first["price"]) == (pytest.approx(1.0), pytest.approx(100.0))
    assert (first["symbol"], first["venue_side"], first["fee"]) == ("BTCUSDT", "BUY", 0.0)
    venue.settle()
    manager.poll()
    assert len(sink.deltas) == 2
    assert sink.deltas[1]["exec_id"] == f"{order.client_id}:fill:0002"
    assert _log_text(tmp_path).count("fill-delta") == 2
    assert _log_text(tmp_path).count("delta-propagated") == 2


def test_delta_propagates_before_fill_transition(tmp_path):
    venue = FakeVenue()
    venue.set_last_price("BTCUSDT", 67000.0)
    sink = RecordingSinkV2()
    manager = _manager(venue, tmp_path, sink)
    manager.submit_entry("BTCUSDT", "LONG", 0.01, 67005.0,
                         expire_at_utc=_expiring(), reservation_id="r1")
    kinds = [c[0] for c in sink.calls]
    assert kinds[0] == "delta" and kinds[1] == "fill"  # v0.2.0: delta first, then transition.


def test_old_sink_falls_back_with_loud_log(tmp_path):
    venue = FakeVenue()
    venue.set_last_price("BTCUSDT", 67000.0)
    sink = RecordingSinkV11()
    manager = _manager(venue, tmp_path, sink)
    manager.submit_entry("BTCUSDT", "LONG", 0.01, 67005.0,
                         expire_at_utc=_expiring(), reservation_id="r1")
    assert sink.calls == [("fill", "r1")]  # v0.1.1 surface still works.
    assert "delta-not-propagated" in _log_text(tmp_path)


def test_recovery_replays_unpropagated_deltas(tmp_path):
    venue = FakeVenue()
    venue.fail_next_submit("partial", fractions=(0.5, 0.5))
    manager = _manager(venue, tmp_path, RecordingSinkV11())
    manager.submit_entry("BTCUSDT", "LONG", 2.0, 100.0,
                         expire_at_utc=_expiring(), reservation_id="r1")
    venue.settle()
    manager.poll()
    sink = RecordingSinkV2()
    OrderManager.recover(venue, tmp_path / "orders.jsonl", now_utc=lambda: NOW, outcome_sink=sink)
    assert len(sink.deltas) == 2  # both increments replayed exactly once.
    assert sink.deltas[0]["exec_id"].endswith(":fill:0001")


# -- F-CEO-02: partial protection, no release while exposed ------------------

def test_partial_entry_protected_and_never_released_while_exposed(tmp_path):
    venue = FakeVenue()
    venue.fail_next_submit("partial", fractions=(0.5, 0.5))
    sink = RecordingSinkV2()
    manager = _manager(venue, tmp_path, sink)
    entry = manager.submit_entry("BTCUSDT", "LONG", 2.0, 100.0,
                                 expire_at_utc=_expiring(), reservation_id="r1")
    assert entry.state == OrderState.PARTIAL
    stop, target = manager.attach_siblings(entry, stop_price=99.0, target_price=101.0)
    assert (stop.qty, target.qty) == (pytest.approx(1.0), pytest.approx(1.0))
    assert ("fill", "r1") in sink.calls  # first nonzero fill converts.
    manager.poll(NOW + timedelta(seconds=61))  # expiry cancels the remainder only.
    assert entry.state == OrderState.EXPIRED
    assert manager.position_net("r1") == pytest.approx(1.0)  # filled qty survives expiry.
    assert stop.state == OrderState.OPEN  # protection stays live.
    manager.poll(NOW + timedelta(seconds=62))
    manager.poll(NOW + timedelta(seconds=63))
    assert ("release", "r1") not in sink.calls  # exposed reservations are never released.


def test_position_net_tracks_entries_minus_exits(tmp_path):
    venue = FakeVenue()
    venue.fail_next_submit("partial", fractions=(0.5, 0.5))
    manager = _manager(venue, tmp_path, RecordingSinkV2())
    entry = manager.submit_entry("BTCUSDT", "LONG", 4.0, 100.0,
                                 expire_at_utc=_expiring(), reservation_id="r1")
    manager.attach_siblings(entry, stop_price=99.0, target_price=101.0)
    assert manager.position_net("r1") == pytest.approx(2.0)
    venue.inject_fill(entry.client_id, 1.0, 100.0)
    manager.poll()
    assert manager.position_net("r1") == pytest.approx(3.0)


def test_topup_extends_protection_on_later_fill(tmp_path):
    venue = FakeVenue()
    venue.fail_next_submit("partial", fractions=(0.5, 0.5))
    manager = _manager(venue, tmp_path, RecordingSinkV2())
    entry = manager.submit_entry("BTCUSDT", "LONG", 2.0, 100.0,
                                 expire_at_utc=_expiring(), reservation_id="r1")
    manager.attach_siblings(entry, stop_price=99.0, target_price=101.0)
    venue.settle()  # entry completes to 2.0.
    events = manager.poll()
    assert any(e.get("event", "").startswith("protection-topup") for e in events)
    stops = [o for o in manager.orders.values() if o.role == "stop"]
    assert sum(s.qty for s in stops) == pytest.approx(2.0)
    assert len({s.group_id for s in stops}) == 2  # incremental pair, own group.


def test_stop_failure_has_bounded_response_then_terminal_gap(tmp_path):
    venue = FakeVenue()
    venue.fail_next_submit("partial", fractions=(0.5, 0.5))
    manager = _manager(venue, tmp_path, RecordingSinkV2())
    entry = manager.submit_entry("BTCUSDT", "LONG", 2.0, 100.0,
                                 expire_at_utc=_expiring(), reservation_id="r1")
    manager.attach_siblings(entry, stop_price=99.0, target_price=101.0)
    venue.settle()  # entry completes to 2.0; protection gap of 1.0 opens.
    for _ in range(5):
        venue.fail_next_submit("reject", reason="NO-LIQUIDITY")
        venue.fail_next_submit("reject", reason="NO-LIQUIDITY")
        manager.poll()
    manager.poll()  # 6th poll: attempt bound reached, terminal gap stands.
    assert "protection-gap-unresolved" in _log_text(tmp_path)
    before = len(venue.list_orders())
    manager.poll()
    manager.poll()
    assert len(venue.list_orders()) == before  # bound reached: no further submits.


def test_both_legs_fill_freezes_without_compounding(tmp_path):
    venue = FakeVenue()
    venue.set_last_price("BTCUSDT", 67000.0)
    sink = RecordingSinkV2()
    manager = _manager(venue, tmp_path, sink)
    entry = manager.submit_entry("BTCUSDT", "LONG", 1.0, 67005.0,
                                 expire_at_utc=_expiring(), reservation_id="r1")
    stop, target = manager.attach_siblings(entry, stop_price=66850.0, target_price=67200.0)
    venue.inject_fill(stop.client_id, 1.0, 66850.0)  # venue-side race: both fill.
    venue.inject_fill(target.client_id, 1.0, 67200.0)
    events = manager.poll()
    assert manager.position_net("r1") == pytest.approx(-1.0)  # truthful book, reversed.
    assert any(e.get("event") == "exit-overfill-freeze" for e in events)
    assert ("flat",) not in sink.calls  # a reversal is not flat.
    assert len(venue.list_orders()) == 3  # no compounding orders issued.
    with pytest.raises(ValueError, match="frozen"):
        manager.attach_siblings(entry, stop_price=1.0, target_price=2.0)


# -- F-CEO-03 execution side: reconcile first, late fills ---------------------

def test_ambiguous_reconciled_before_expiry(tmp_path):
    venue = FakeVenue()
    venue.fail_next_submit("timeout", received=True)
    sink = RecordingSinkV2()
    manager = _manager(venue, tmp_path, sink)
    order = manager.submit_entry("BTCUSDT", "LONG", 0.01, 67005.0,
                                 expire_at_utc=_expiring(), kind="STOP_MARKET",
                                 reservation_id="r1")
    assert order.state == OrderState.AMBIGUOUS
    manager.poll(NOW + timedelta(seconds=61))  # reconcile adopts, then expiry cancels.
    assert order.state == OrderState.EXPIRED
    assert order.reconciled and order.venue_known
    assert venue.query(order.client_id).status == "CANCELLED"
    manager.poll(NOW + timedelta(seconds=62))
    manager.poll(NOW + timedelta(seconds=63))
    assert ("release", "r1") in sink.calls  # zero fills + settled: freed.


def test_late_fill_books_and_extends_protection(tmp_path):
    venue = FakeVenue()
    venue.fail_next_submit("partial", fractions=(0.5, 0.5))
    sink = RecordingSinkV2()
    manager = _manager(venue, tmp_path, sink)
    entry = manager.submit_entry("BTCUSDT", "LONG", 2.0, 100.0,
                                 expire_at_utc=_expiring(), reservation_id="r1")
    manager.attach_siblings(entry, stop_price=99.0, target_price=101.0)
    manager.poll(NOW + timedelta(seconds=61))  # expiry cancels the remainder.
    assert entry.state == OrderState.EXPIRED
    venue.inject_fill(entry.client_id, 1.0, 100.0)  # cancel race: fill landed anyway.
    events = manager.poll(NOW + timedelta(seconds=62))
    assert any(e.get("event") == "late-fill-booked" for e in events)
    assert sink.deltas[-1]["qty"] == pytest.approx(1.0)
    assert ("release", "r1") not in sink.calls
    assert any(e.get("event", "").startswith("protection-topup") for e in events)


def test_flat_waits_for_settle_window(tmp_path):
    venue = FakeVenue()
    venue.fail_next_submit("partial", fractions=(0.5, 0.5))
    sink = RecordingSinkV2()
    manager = _manager(venue, tmp_path, sink)
    entry = manager.submit_entry("BTCUSDT", "LONG", 2.0, 100.0,
                                 expire_at_utc=_expiring(), reservation_id="r1")
    stop, _ = manager.attach_siblings(entry, stop_price=99.0, target_price=101.0)
    manager.poll(NOW + timedelta(seconds=61))  # remainder cancelled; 1.0 exposed.
    venue.set_last_price("BTCUSDT", 98.0)  # stop fills the full exposed 1.0.
    manager.poll(NOW + timedelta(seconds=62))
    assert stop.state == OrderState.FILLED
    assert manager.position_net("r1") == pytest.approx(0.0)
    assert ("flat",) not in sink.calls  # entry still settling: flat waits.
    manager.poll(NOW + timedelta(seconds=63))
    manager.poll(NOW + timedelta(seconds=64))
    assert ("flat",) in sink.calls


def test_all_unknown_chain_releases_after_void(tmp_path):
    venue = FakeVenue()
    venue.fail_next_submit("timeout", received=False)
    sink = RecordingSinkV2()
    manager = _manager(venue, tmp_path, sink)
    order = manager.submit_with_retry("BTCUSDT", "LONG", 0.01, 67005.0,
                                      expire_at_utc=_expiring(), max_retries=0,
                                      reservation_id="r1")
    assert order.state == OrderState.AMBIGUOUS
    manager.poll()  # void-unknown: nothing can ever fill.
    assert order.state == OrderState.CANCELLED
    assert ("release", "r1") in sink.calls


# -- intents, recovery, venue faults --------------------------------------------

def test_submit_intent_persisted_before_side_effect(tmp_path):
    venue = FakeVenue()
    venue.set_last_price("BTCUSDT", 67000.0)
    manager = _manager(venue, tmp_path, RecordingSinkV2())
    order = manager.submit_entry("BTCUSDT", "LONG", 0.01, 67005.0,
                                 expire_at_utc=_expiring(), reservation_id="r1")
    lines = (tmp_path / "orders.jsonl").read_text().splitlines()
    kinds = [l for l in lines if f'"{order.client_id}"' in l]
    assert '"submit-intent"' in kinds[0]  # intent is the first record for the ID.
    assert order.client_id in manager._minted_ids


def test_cancel_intent_logged_on_expiry(tmp_path):
    venue = FakeVenue()
    manager = _manager(venue, tmp_path, RecordingSinkV2())
    manager.submit_entry("BTCUSDT", "LONG", 0.01, 67005.0,
                         expire_at_utc=_expiring(), kind="STOP_MARKET",
                         reservation_id="r1")
    manager.poll(NOW + timedelta(seconds=61))
    text = _log_text(tmp_path)
    assert text.index("cancel-intent") < text.index('"expired"')


def test_recovery_is_idempotent(tmp_path):
    venue = FakeVenue()
    venue.fail_next_submit("partial", fractions=(0.5, 0.5))
    sink_a = RecordingSinkV2()
    manager = _manager(venue, tmp_path, sink_a)
    entry = manager.submit_entry("BTCUSDT", "LONG", 2.0, 100.0,
                                 expire_at_utc=_expiring(), reservation_id="r1")
    manager.attach_siblings(entry, stop_price=99.0, target_price=101.0)
    manager.set_halted(True, reason="test-halt")
    log_path = tmp_path / "orders.jsonl"
    sink_b = RecordingSinkV2()
    first = OrderManager.recover(venue, log_path, now_utc=lambda: NOW, outcome_sink=sink_b)
    snap_orders = {c: (o.state.value, o.filled_qty) for c, o in first.orders.items()}
    snap_venue = [(v.client_id, v.status, v.filled_qty) for v in venue.list_orders()]
    assert first.exit_only is True
    sink_c = RecordingSinkV2()
    second = OrderManager.recover(venue, log_path, now_utc=lambda: NOW, outcome_sink=sink_c)
    assert {c: (o.state.value, o.filled_qty) for c, o in second.orders.items()} == snap_orders
    assert [(v.client_id, v.status, v.filled_qty) for v in venue.list_orders()] == snap_venue
    assert sink_b.calls == sink_c.calls == []  # everything already fired pre-crash.
    assert second.exit_only is True


def test_inject_fill_guards(tmp_path):
    venue = FakeVenue()
    with pytest.raises(KeyError, match="unknown order"):
        venue.inject_fill("nope", 1.0, 1.0)
    venue.fail_next_submit("reject", reason="X")
    venue.submit("c1", "BTCUSDT", "BUY", "LIMIT", 1.0, price=1.0)
    with pytest.raises(ValueError, match="rejected"):
        venue.inject_fill("c1", 1.0, 1.0)
    venue.set_last_price("BTCUSDT", 10.0)
    venue.submit("c2", "BTCUSDT", "BUY", "LIMIT", 1.0, price=10.0)
    with pytest.raises(ValueError, match="qty must be > 0"):
        venue.inject_fill("c2", 0.0, 10.0)
