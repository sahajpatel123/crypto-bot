"""Order-manager unit tests (Worker 2, E-001). Deterministic clock, fake venue."""
from datetime import datetime, timedelta, timezone

import pytest

from cryptobot.execution import FakeVenue, OrderManager, OrderState

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _manager(venue, tmp_path, **kw):
    clock = kw.pop("clock", lambda: NOW)
    return OrderManager(venue, log_path=tmp_path / "orders.jsonl", now_utc=clock, **kw)


def test_client_ids_unique_and_prefixed(tmp_path):
    manager = _manager(FakeVenue(), tmp_path)
    ids = {manager.new_client_id() for _ in range(1000)}
    assert len(ids) == 1000
    assert all(i.startswith("w2-") for i in ids)


def test_entry_submits_and_fills(tmp_path):
    venue = FakeVenue()
    venue.set_last_price("BTCUSDT", 67000.0)
    manager = _manager(venue, tmp_path)
    order = manager.submit_entry("BTCUSDT", "LONG", 0.01, 67005.0,
                                 expire_at_utc=NOW + timedelta(seconds=60))
    assert order.state == OrderState.FILLED
    assert order.venue_side == "BUY" and order.filled_qty == 0.01


def test_unfilled_entry_expires_and_cancels_at_venue(tmp_path):
    venue = FakeVenue()
    manager = _manager(venue, tmp_path)
    # STOP_MARKET with no stop price never triggers: stays OPEN until expiry.
    order = manager.submit_entry("BTCUSDT", "LONG", 0.01, 67005.0,
                                 expire_at_utc=NOW + timedelta(seconds=60),
                                 kind="STOP_MARKET")
    assert order.state == OrderState.OPEN
    events = manager.poll(NOW + timedelta(seconds=61))
    assert order.state == OrderState.EXPIRED
    assert venue.query(order.client_id) is not None
    assert venue.query(order.client_id).status == "CANCELLED"
    assert any(e["event"] == "expired" for e in events)


def test_exit_only_refuses_entries(tmp_path):
    manager = _manager(FakeVenue(), tmp_path, exit_only=True)
    with pytest.raises(PermissionError, match="exit-only"):
        manager.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                             expire_at_utc=NOW + timedelta(seconds=60))


def test_partial_fill_tracked_across_polls(tmp_path):
    venue = FakeVenue()
    venue.fail_next_submit("partial", fractions=(0.4, 0.6))
    manager = _manager(venue, tmp_path)
    order = manager.submit_entry("BTCUSDT", "LONG", 1.0, 10.0,
                                 expire_at_utc=NOW + timedelta(seconds=60))
    assert order.state == OrderState.PARTIAL
    assert order.filled_qty == pytest.approx(0.4)
    venue.settle()
    manager.poll()
    assert order.state == OrderState.FILLED
    assert order.filled_qty == pytest.approx(1.0)


def test_retry_after_unknown_timeout_uses_new_id_without_duplicate(tmp_path):
    venue = FakeVenue()
    venue.set_last_price("BTCUSDT", 67000.0)
    venue.fail_next_submit("timeout", received=False)
    manager = _manager(venue, tmp_path)
    order = manager.submit_with_retry("BTCUSDT", "LONG", 0.01, 67005.0,
                                      expire_at_utc=NOW + timedelta(seconds=60))
    assert order.state == OrderState.FILLED
    assert order.retry_of is not None and order.retry_of != order.client_id
    assert venue.query(order.retry_of) is None  # first ID never reached the venue.
    assert len(venue.fills) == 1  # exactly one fill: no duplicate exposure.


def test_retry_adopts_venue_order_when_timeout_had_received(tmp_path):
    venue = FakeVenue()
    venue.set_last_price("BTCUSDT", 67000.0)
    venue.fail_next_submit("timeout", received=True)
    manager = _manager(venue, tmp_path)
    order = manager.submit_with_retry("BTCUSDT", "LONG", 0.01, 67005.0,
                                      expire_at_utc=NOW + timedelta(seconds=60))
    assert order.state == OrderState.FILLED and order.retry_of is None
    assert order.reconciled and order.venue_known
    assert len(venue.fills) == 1


def test_reconcile_marks_unknown_venue_state(tmp_path):
    venue = FakeVenue()
    venue.fail_next_submit("timeout", received=False)
    manager = _manager(venue, tmp_path)
    order = manager.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                                 expire_at_utc=NOW + timedelta(seconds=60))
    assert order.state == OrderState.AMBIGUOUS
    assert manager.reconcile(order.client_id) is None
    assert not order.venue_known and order.reconciled


def test_siblings_verified_independently_and_winner_cancels_loser(tmp_path):
    venue = FakeVenue()
    venue.set_last_price("BTCUSDT", 67000.0)
    manager = _manager(venue, tmp_path)
    entry = manager.submit_entry("BTCUSDT", "LONG", 0.01, 67005.0,
                                 expire_at_utc=NOW + timedelta(seconds=60))
    stop, target = manager.attach_siblings(entry, stop_price=66850.0, target_price=67200.0)
    assert stop.reconciled and target.reconciled
    assert stop.venue_known and target.venue_known
    assert stop.group_id == target.group_id != ""
    venue.set_last_price("BTCUSDT", 66800.0)  # stop triggers.
    manager.poll()
    assert stop.state == OrderState.FILLED
    assert target.state == OrderState.CANCELLED  # best-effort verified cancel.
    assert venue.query(target.client_id) is not None
    assert venue.query(target.client_id).status == "CANCELLED"


def test_siblings_rejected_for_unfilled_entry(tmp_path):
    manager = _manager(FakeVenue(), tmp_path)
    order = manager.submit_entry("BTCUSDT", "LONG", 0.01, 67005.0,
                                 expire_at_utc=NOW + timedelta(seconds=60),
                                 kind="STOP_MARKET")
    with pytest.raises(ValueError, match="FILLED entry"):
        manager.attach_siblings(order, stop_price=1.0, target_price=2.0)


def test_restart_recovery_reconciles_open_and_ambiguous(tmp_path):
    venue = FakeVenue()
    venue.fail_next_submit("timeout", received=True)
    manager = _manager(venue, tmp_path)
    # STOP_MARKET without stop price: received at venue as NEW, ambiguous locally.
    ambiguous = manager.submit_entry("BTCUSDT", "LONG", 0.01, 67005.0,
                                     expire_at_utc=NOW + timedelta(seconds=600),
                                     kind="STOP_MARKET")
    assert ambiguous.state == OrderState.AMBIGUOUS
    log_path = tmp_path / "orders.jsonl"

    recovered = OrderManager.recover(venue, log_path, now_utc=lambda: NOW)
    order = recovered.orders[ambiguous.client_id]
    assert order.state == OrderState.OPEN  # venue truth adopted on recovery.
    assert order.reconciled and order.venue_known
    # New IDs after recovery still unique against pre-crash IDs.
    assert recovered.new_client_id() != ambiguous.client_id


def test_recovery_with_missing_log_is_empty(tmp_path):
    recovered = OrderManager.recover(FakeVenue(), tmp_path / "nope.jsonl", now_utc=lambda: NOW)
    assert recovered.orders == {}
