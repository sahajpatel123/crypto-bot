"""W3-24H §4 execution races: partial-vs-cancel, stop-leg reject."""
from datetime import UTC, datetime, timedelta

from cryptobot.execution import FakeVenue, OrderManager, OrderState

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _manager(venue, tmp_path, **kw):
    clock = kw.pop("clock", lambda: NOW)
    return OrderManager(venue, log_path=tmp_path / "orders.jsonl",
                        now_utc=clock, **kw)


def test_partial_fill_then_cancel_preserves_exposure(tmp_path):
    venue = FakeVenue()
    manager = _manager(venue, tmp_path)
    venue.fail_next_submit("partial", fractions=(0.5, 0.5))
    order = manager.submit_entry("BTCUSDT", "LONG", 0.02, 67005.0,
                                 expire_at_utc=NOW + timedelta(seconds=60),
                                 kind="LIMIT", reservation_id="r-1")
    assert order.filled_qty == 0.01  # half arrived before the cancel.
    venue.cancel(order.client_id)  # cancel wins the race for the remainder.
    assert venue.settle() == []  # remainder never fills after cancel.
    view = manager.reconcile(order.client_id)
    assert view is not None and view.status == "CANCELLED"
    assert order.filled_qty == 0.01
    assert manager.position_net("r-1") == 0.01  # exposure preserved, not zeroed.


def test_stop_leg_reject_leaves_no_false_cover(tmp_path):
    venue = FakeVenue()
    venue.set_last_price("BTCUSDT", 67000.0)
    manager = _manager(venue, tmp_path)
    entry = manager.submit_entry("BTCUSDT", "LONG", 0.01, 67005.0,
                                 expire_at_utc=NOW + timedelta(seconds=60),
                                 kind="MARKET", reservation_id="r-2")
    assert entry.filled_qty == 0.01
    venue.fail_next_submit("reject", reason="venue-stop-reject")
    stop, target = manager.attach_siblings(entry, stop_price=66990.0,
                                           target_price=67020.0)
    assert stop.state == OrderState.REJECTED
    assert target.state == OrderState.OPEN
    assert manager.reconcile(stop.client_id).status == "REJECTED"
    # Rejected stop covers nothing; the entry exposure stands uncovered.
    assert manager.position_net("r-2") == 0.01
