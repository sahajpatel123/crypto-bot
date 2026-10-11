"""R-001 planned-loss sizing, R-002 leverage cap, R-003 min-size skip."""
from __future__ import annotations

import pytest

from conftest import NOW, build_account, build_intent, load_fixture, make_policy
from cryptobot.risk import Approved, Rejected

INTENTS = load_fixture("risk_intents.json")
ACCOUNTS = load_fixture("risk_accounts.json")


def _expected(intent_spec):
    ref = (intent_spec["entry_low"] + intent_spec["entry_high"]) / 2
    stop_pct = abs(ref - intent_spec["invalidation_price"]) / ref
    fc = intent_spec["forecast_cost"]
    stressed = (fc["fee_bps"] + fc["spread_bps"] + fc["slippage_bps"] + fc["funding_bps"]) / 10000 * 1.5
    return ref, stop_pct, stressed


def test_canonical_long_planned_loss_identity(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    spec = INTENTS["canonical_long"]
    out = policy.evaluate(build_intent(spec), build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Approved)
    assert out.reserved_risk == pytest.approx(25.0)
    ref, stop_pct, stressed = _expected(spec)
    assert out.notional_usdt == pytest.approx(25.0 / (stop_pct + stressed))
    assert out.notional_usdt * stop_pct + out.notional_usdt * stressed == pytest.approx(25.0)
    assert out.qty == pytest.approx(out.notional_usdt / ref)


def test_canonical_short_approved(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    out = policy.evaluate(build_intent(INTENTS["canonical_short"]), build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Approved)
    assert out.reserved_risk == pytest.approx(25.0)


def test_tiny_stop_rejected_over_leverage_cap(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    out = policy.evaluate(build_intent(INTENTS["tiny_stop"]), build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Rejected)
    assert out.reason == "leverage:cap-exceeded"


def test_leverage_boundary_just_under_3x_approved(tmp_path):
    base = dict(INTENTS["tiny_stop"])
    fc = base["forecast_cost"]
    stressed = (fc["fee_bps"] + fc["spread_bps"] + fc["slippage_bps"] + fc["funding_bps"]) / 10000 * 1.5
    ref = (base["entry_low"] + base["entry_high"]) / 2
    target = 3 * 10000.0 * (1 - 1e-6)
    stop_pct = 25.0 / target - stressed
    base["invalidation_price"] = ref - stop_pct * ref
    assert base["invalidation_price"] < base["entry_low"]
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    out = policy.evaluate(build_intent(base), build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Approved)
    assert out.notional_usdt <= 3 * 10000.0


def test_dust_skipped_and_consumes_nothing(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(100.0)
    out = policy.evaluate(build_intent(INTENTS["dust"]), build_account(ACCOUNTS["healthy_100"]))
    assert isinstance(out, Rejected)
    assert out.reason == "skip:min-notional"
    # A skipped evaluation must not leave a reservation behind: canonical still approves.
    out2 = policy.evaluate(build_intent(INTENTS["canonical_long"]), build_account(ACCOUNTS["healthy_100"]))
    assert isinstance(out2, Approved)
