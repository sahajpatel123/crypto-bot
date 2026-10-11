"""Fake-venue unit tests (Worker 2, E-001). No network, no randomness."""
import pytest

from cryptobot.execution import FakeVenue, VenueTimeoutError


def test_market_submit_fills_immediately():
    venue = FakeVenue()
    venue.set_last_price("BTCUSDT", 67000.0)
    result = venue.submit("c1", "BTCUSDT", "BUY", "MARKET", 0.01)
    assert result.accepted
    view = venue.query("c1")
    assert view is not None and view.status == "FILLED"
    assert view.filled_qty == 0.01 and view.avg_price == 67000.0
    assert len(venue.fills) == 1


def test_client_id_is_idempotent_no_duplicate_order():
    venue = FakeVenue()
    venue.submit("c1", "BTCUSDT", "BUY", "MARKET", 0.01)
    again = venue.submit("c1", "BTCUSDT", "BUY", "MARKET", 99.0)
    assert "duplicate-client-id" in again.reason
    assert venue.query("c1") is not None and venue.query("c1").qty == 0.01
    assert len(venue.fills) == 1


def test_reject_fault_marks_order_rejected():
    venue = FakeVenue()
    venue.fail_next_submit("reject", reason="INSUFFICIENT_MARGIN")
    result = venue.submit("c1", "BTCUSDT", "BUY", "LIMIT", 0.01, price=1.0)
    assert not result.accepted and result.reason == "INSUFFICIENT_MARGIN"
    assert venue.query("c1") is not None and venue.query("c1").status == "REJECTED"


def test_timeout_without_receipt_leaves_venue_empty():
    venue = FakeVenue()
    venue.fail_next_submit("timeout", received=False)
    with pytest.raises(VenueTimeoutError):
        venue.submit("c1", "BTCUSDT", "BUY", "LIMIT", 0.01, price=1.0)
    assert venue.query("c1") is None  # safe to retry with a new ID.


def test_timeout_with_receipt_keeps_venue_order():
    venue = FakeVenue()
    venue.set_last_price("BTCUSDT", 67000.0)
    venue.fail_next_submit("timeout", received=True)
    with pytest.raises(VenueTimeoutError):
        venue.submit("c1", "BTCUSDT", "BUY", "MARKET", 0.01)
    view = venue.query("c1")  # blind retry now would double exposure.
    assert view is not None and view.status == "FILLED"


def test_partial_fault_then_settle_completes():
    venue = FakeVenue()
    venue.fail_next_submit("partial", fractions=(0.4, 0.6))
    venue.submit("c1", "BTCUSDT", "BUY", "LIMIT", 1.0, price=10.0)
    assert venue.query("c1") is not None and venue.query("c1").status == "PARTIALLY_FILLED"
    assert venue.query("c1").filled_qty == pytest.approx(0.4)
    venue.settle()
    assert venue.query("c1") is not None and venue.query("c1").status == "FILLED"
    assert venue.query("c1").filled_qty == pytest.approx(1.0)


def test_stop_triggers_on_price_and_cancel_is_verified():
    venue = FakeVenue()
    venue.set_last_price("BTCUSDT", 67000.0)
    venue.submit("stop1", "BTCUSDT", "SELL", "STOP_MARKET", 0.01, stop_price=66850.0)
    assert venue.query("stop1") is not None and venue.query("stop1").status == "NEW"
    venue.set_last_price("BTCUSDT", 66900.0)  # no trigger yet.
    assert venue.query("stop1") is not None and venue.query("stop1").status == "NEW"
    venue.set_last_price("BTCUSDT", 66800.0)  # triggers.
    assert venue.query("stop1") is not None and venue.query("stop1").status == "FILLED"
    # Cancelling a filled order is a verified no-op.
    assert venue.cancel("stop1") is not None and venue.cancel("stop1").status == "FILLED"
    assert venue.query("missing") is None
    assert venue.cancel("missing") is None


def test_invalid_fault_and_qty_rejected():
    venue = FakeVenue()
    with pytest.raises(ValueError, match="unknown fault mode"):
        venue.fail_next_submit("explode")
    with pytest.raises(ValueError, match="qty must be > 0"):
        venue.submit("c1", "BTCUSDT", "BUY", "MARKET", 0.0)
