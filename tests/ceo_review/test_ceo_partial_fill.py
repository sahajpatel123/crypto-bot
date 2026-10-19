"""F-CEO-02: partial fills are protected; expiry cannot free live exposure."""
from datetime import timedelta

from helpers import audit_account, audit_intent, make_clock

from cryptobot.execution import FakeVenue, OrderManager
from cryptobot.risk import Approved, Rejected, RiskPolicy


def _half_filled(tmp_path):
    cell, clock = make_clock()
    policy = RiskPolicy(state_path=tmp_path / "risk.json", now_utc=clock)
    policy.reconcile_day(1000)
    account = audit_account()
    approval = policy.evaluate(audit_intent(cell[0]), account)
    assert isinstance(approval, Approved)
    venue = FakeVenue()
    venue.fail_next_submit("partial", fractions=(0.5, 0.5))
    manager = OrderManager(venue, log_path=tmp_path / "orders.jsonl",
                           now_utc=clock, outcome_sink=policy)
    entry = manager.submit_entry("BTCUSDT", "LONG", approval.qty, 100,
                                 expire_at_utc=cell[0] + timedelta(seconds=5),
                                 reservation_id=approval.reservation_id)
    assert entry.filled_qty == approval.qty * 0.5
    return cell, clock, policy, account, venue, manager, entry, approval


def test_partial_fill_gets_protection(tmp_path):
    cell, clock, policy, account, venue, manager, entry, approval = _half_filled(tmp_path)
    stop, target = manager.attach_siblings(entry, stop_price=99, target_price=101)
    assert stop.qty == entry.filled_qty
    assert target.qty == entry.filled_qty


def test_expiry_after_partial_fill_keeps_risk_occupied(tmp_path):
    cell, clock, policy, account, venue, manager, entry, approval = _half_filled(tmp_path)
    cell[0] += timedelta(seconds=6)
    events = manager.poll()
    assert any(e.get("event") == "expired" for e in events)
    assert sum(f.qty for f in venue.fills) > 0  # filled exposure remains
    nxt = policy.evaluate(audit_intent(cell[0]), account)
    assert isinstance(nxt, Rejected)  # never Approved while exposure lives


def test_expired_reservation_with_fills_is_retained(tmp_path):
    cell, clock, policy, account, venue, manager, entry, approval = _half_filled(tmp_path)
    cell[0] += timedelta(seconds=6)
    manager.poll()
    # v0.2.0 precise ruling: a filled reservation is CONSUMED into
    # open-position state at first fill; the post-expiry block rides booked
    # exposure, and release refuses while exposure is open.
    assert hasattr(policy, "booked_net"), \
        "policy must expose booked_net (v0.2.0 ruling)"
    assert policy.booked_net(approval.reservation_id) != 0
    assert policy.release(approval.reservation_id) is False  # block retained
