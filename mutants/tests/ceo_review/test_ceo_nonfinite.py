"""F-CEO-07: nonfinite money/price/cost values are rejected, never approved."""
import math

import pytest
from helpers import T0, audit_account, audit_intent, make_clock

from cryptobot.coordination import ForecastCost
from cryptobot.risk import AccountSnapshot, Approved, Rejected, RiskPolicy


def _policy(tmp_path, clock):
    policy = RiskPolicy(state_path=tmp_path / "risk.json", now_utc=clock)
    policy.reconcile_day(1000)
    return policy


def test_nan_forecast_cost_rejected(tmp_path):
    cell, clock = make_clock()
    try:
        bad = ForecastCost(float("nan"), 1, 1, 0)
    except ValueError:
        return  # construction-time rejection is correct
    out = _policy(tmp_path, clock).evaluate(
        audit_intent(cell[0], forecast=bad), audit_account())
    assert isinstance(out, Rejected)
    assert not (isinstance(out, Approved) and
                (math.isnan(out.notional_usdt) or math.isnan(out.qty)))


def test_nan_account_values_rejected(tmp_path):
    cell, clock = make_clock()
    acct = AccountSnapshot(float("nan"), 1000, 1000, 0, False)
    out = _policy(tmp_path, clock).evaluate(audit_intent(cell[0]), acct)
    assert isinstance(out, Rejected)


def test_infinite_fee_rejected(tmp_path):
    cell, clock = make_clock()
    try:
        bad = ForecastCost(float("inf"), 1, 1, 0)
    except ValueError:
        return
    out = _policy(tmp_path, clock).evaluate(
        audit_intent(cell[0], forecast=bad), audit_account())
    assert isinstance(out, Rejected)
