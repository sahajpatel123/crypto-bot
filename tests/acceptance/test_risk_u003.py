"""V-003 U-003 disposition tests: pinned simulation defaults, bounded."""
from __future__ import annotations

from datetime import timedelta

import pytest

from conftest import NOW, build_account, build_intent, load_fixture, make_policy
from cryptobot.risk import Approved, Rejected, RiskConfig, plan_size

INTENTS = load_fixture("risk_intents.json")
ACCOUNTS = load_fixture("risk_accounts.json")


def test_stress_multiplier_scales_only_stressed_costs():
    intent = build_intent(INTENTS["canonical_long"])
    plans = [plan_size(intent, 10000.0, RiskConfig(stress_multiplier=m)) for m in (1.0, 1.5, 3.0)]
    assert plans[0].stop_pct == plans[1].stop_pct == plans[2].stop_pct
    assert plans[1].stressed_cost_pct == pytest.approx(plans[0].stressed_cost_pct * 1.5)
    assert plans[2].stressed_cost_pct == pytest.approx(plans[0].stressed_cost_pct * 3.0)
    assert plans[0].reserved_risk == plans[1].reserved_risk == plans[2].reserved_risk
    assert plans[0].reserved_risk == pytest.approx(25.0)
    assert plans[0].notional_usdt > plans[1].notional_usdt > plans[2].notional_usdt


def test_evidence_age_boundary_exact_max_passes(tmp_path):
    spec = dict(INTENTS["canonical_long"])
    spec["evidence_ts_utc"] = (NOW - timedelta(seconds=120)).isoformat()
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    out = policy.evaluate(build_intent(spec), build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Approved)


def test_evidence_age_one_second_past_max_rejects(tmp_path):
    spec = dict(INTENTS["canonical_long"])
    spec["evidence_ts_utc"] = (NOW - timedelta(seconds=121)).isoformat()
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    out = policy.evaluate(build_intent(spec), build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Rejected) and out.reason == "stale:evidence-age"


def test_evidence_age_bound_is_the_pinned_config(tmp_path):
    spec = dict(INTENTS["canonical_long"])
    spec["evidence_ts_utc"] = (NOW - timedelta(seconds=30)).isoformat()
    policy = make_policy(tmp_path, max_evidence_age_s=10.0)
    policy.reconcile_day(10000.0)
    out = policy.evaluate(build_intent(spec), build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Rejected) and out.reason == "stale:evidence-age"
