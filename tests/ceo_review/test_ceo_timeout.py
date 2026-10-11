"""F-CEO-03: reservation TTL expiry is not proof of no exposure."""
from datetime import timedelta

from helpers import audit_account, audit_intent, make_clock

from cryptobot.risk import Approved, Rejected, RiskPolicy


def test_expired_reservation_blocks_until_reconciled(tmp_path):
    cell, clock = make_clock()
    policy = RiskPolicy(state_path=tmp_path / "risk.json", now_utc=clock)
    policy.reconcile_day(1000)
    account = audit_account()
    first = policy.evaluate(audit_intent(cell[0]), account)
    assert isinstance(first, Approved)
    cell[0] += timedelta(seconds=6)  # past the 5s entry/reservation TTL
    second = policy.evaluate(audit_intent(cell[0]), account)
    assert isinstance(second, Rejected)  # unresolved exposure blocks
