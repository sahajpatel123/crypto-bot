"""R-004 one position incl. reservations, R-009 health blocks."""
from __future__ import annotations

from datetime import timedelta

from conftest import NOW, build_account, build_intent, load_fixture, make_policy
from cryptobot.risk import Approved, Rejected

INTENTS = load_fixture("risk_intents.json")
ACCOUNTS = load_fixture("risk_accounts.json")


def _ready(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    return policy


def test_second_evaluate_while_reserved_rejected(tmp_path):
    policy = _ready(tmp_path)
    acct = build_account(ACCOUNTS["healthy_10k"])
    first = policy.evaluate(build_intent(INTENTS["canonical_long"]), acct)
    assert isinstance(first, Approved)
    second = policy.evaluate(build_intent(INTENTS["canonical_short"]), acct)
    assert isinstance(second, Rejected)
    assert second.reason == "exposure:one-position"


def test_open_position_blocks_new_entry(tmp_path):
    policy = _ready(tmp_path)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]), build_account(ACCOUNTS["position_open"]))
    assert isinstance(out, Rejected)
    assert out.reason == "exposure:one-position"


def test_release_unblocks(tmp_path):
    policy = _ready(tmp_path)
    acct = build_account(ACCOUNTS["healthy_10k"])
    first = policy.evaluate(build_intent(INTENTS["canonical_long"]), acct)
    assert isinstance(first, Approved)
    assert policy.release(first.reservation_id) is True
    assert policy.release(first.reservation_id) is False
    again = policy.evaluate(build_intent(INTENTS["canonical_long"]), acct)
    assert isinstance(again, Approved)


def test_fill_then_flat_lifecycle(tmp_path):
    policy = _ready(tmp_path)
    acct = build_account(ACCOUNTS["healthy_10k"])
    first = policy.evaluate(build_intent(INTENTS["canonical_long"]), acct)
    assert isinstance(first, Approved)
    policy.note_fill(first.reservation_id)
    blocked = policy.evaluate(build_intent(INTENTS["canonical_long"]), acct)
    assert isinstance(blocked, Rejected) and blocked.reason == "exposure:one-position"
    policy.note_flat()
    assert isinstance(policy.evaluate(build_intent(INTENTS["canonical_long"]), acct), Approved)


def test_expired_reservation_purged(tmp_path):
    policy = _ready(tmp_path)
    acct = build_account(ACCOUNTS["healthy_10k"])
    first = policy.evaluate(build_intent(INTENTS["canonical_long"]), acct)
    assert isinstance(first, Approved)
    later = NOW + timedelta(minutes=5)  # past the 12:01 entry expiry
    late_policy = make_policy(tmp_path, now=later)
    assert late_policy.state_path == policy.state_path
    fresh_spec = dict(INTENTS["canonical_long"])
    fresh_spec["evidence_ts_utc"] = (later - timedelta(seconds=5)).isoformat()
    fresh_spec["entry_expiry_utc"] = (later + timedelta(seconds=60)).isoformat()
    out = late_policy.evaluate(build_intent(fresh_spec), acct)
    assert isinstance(out, Approved)


def test_fresh_day_needs_reconciliation(tmp_path):
    policy = make_policy(tmp_path)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]), build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Rejected)
    assert out.reason == "health:day-open-needs-reconciliation"


def test_expired_intent_rejected(tmp_path):
    out = _ready(tmp_path).evaluate(
        build_intent(INTENTS["expired"]), build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Rejected) and out.reason == "stale:expired"


def test_stale_evidence_rejected(tmp_path):
    out = _ready(tmp_path).evaluate(
        build_intent(INTENTS["stale_evidence"]), build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Rejected) and out.reason == "stale:evidence-age"


def test_halt_quality_rejected(tmp_path):
    out = _ready(tmp_path).evaluate(
        build_intent(INTENTS["halt_quality"]), build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Rejected) and out.reason == "health:data-quality-halt"


def test_degraded_quality_rejected(tmp_path):
    out = _ready(tmp_path).evaluate(
        build_intent(INTENTS["degraded_quality"]), build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Rejected) and out.reason == "health:data-quality-degraded"
