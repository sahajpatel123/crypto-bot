"""R-008 profit protection: arming, upward-only floor, persistence."""
from __future__ import annotations

from datetime import datetime

from conftest import build_account, build_intent, load_fixture, make_policy
from cryptobot.risk import Approved, Rejected

INTENTS = load_fixture("risk_intents.json")
ACCOUNTS = load_fixture("risk_accounts.json")


def test_unarmed_passes(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]), build_account(ACCOUNTS["profit_unarmed"]))
    assert isinstance(out, Approved)


def test_armed_below_floor_rejected(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    out = policy.evaluate(
        build_intent(INTENTS["canonical_long"]), build_account(ACCOUNTS["profit_armed_below_floor"]))
    assert isinstance(out, Rejected) and out.reason == "halt:profit-protection"


def test_armed_above_floor_passes(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    out = policy.evaluate(
        build_intent(INTENTS["canonical_long"]), build_account(ACCOUNTS["profit_armed_above_floor"]))
    assert isinstance(out, Approved)


def test_floor_ratchets_up_never_down(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    intent = build_intent(INTENTS["canonical_long"])

    def acct(marked, realised):
        base = dict(ACCOUNTS["healthy_10k"])
        base.update(reconciled_equity=marked, marked_equity=marked,
                    net_liquidation=marked - 1, net_realised_global=realised)
        return build_account(base)

    assert isinstance(policy.evaluate(intent, acct(10090.0, 120.0)), Approved)  # floor 10084
    assert policy.release("r-000001") is True
    out = policy.evaluate(intent, acct(10150.0, 200.0))  # floor ratchets to 10140
    assert isinstance(out, Approved)
    assert policy.release("r-000002") is True
    # Realised falls back but the floor must not: 10100 < 10140 still rejected.
    out2 = policy.evaluate(intent, acct(10100.0, 50.0))
    assert isinstance(out2, Rejected) and out2.reason == "halt:profit-protection"


def test_floor_survives_restart_and_day_change(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    intent = build_intent(INTENTS["canonical_long"])
    assert isinstance(policy.evaluate(
        intent, build_account(ACCOUNTS["profit_armed_above_floor"])), Approved)
    restarted = make_policy(tmp_path)
    out = restarted.evaluate(intent, build_account(ACCOUNTS["profit_armed_below_floor"]))
    assert isinstance(out, Rejected) and out.reason == "halt:profit-protection"
    next_day = datetime.fromisoformat("2026-10-11T18:30:01+00:00")  # 2026-10-12 IST
    day2_spec = dict(INTENTS["canonical_long"])
    day2_spec["evidence_ts_utc"] = "2026-10-11T18:29:55+00:00"
    day2_spec["entry_expiry_utc"] = "2026-10-11T18:31:00+00:00"
    rolled = make_policy(tmp_path, now=next_day)
    rolled.reconcile_day(10060.0)
    out2 = rolled.evaluate(build_intent(day2_spec), build_account(ACCOUNTS["profit_armed_below_floor"]))
    assert isinstance(out2, Rejected) and out2.reason == "halt:profit-protection"
