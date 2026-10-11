"""R-012 determinism: identical inputs => identical decisions and state bytes."""
from __future__ import annotations

from conftest import build_account, build_intent, load_fixture, make_policy
from cryptobot.risk import Approved, Rejected

INTENTS = load_fixture("risk_intents.json")
ACCOUNTS = load_fixture("risk_accounts.json")


def _run(tmp_path, tag):
    sub = tmp_path / tag
    sub.mkdir()
    policy = make_policy(sub)
    policy.reconcile_day(10000.0)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]), build_account(ACCOUNTS["healthy_10k"]))
    state_bytes = (sub / "risk_state.json").read_bytes()
    return out, state_bytes


def test_identical_inputs_identical_approval_and_state(tmp_path):
    first, bytes_first = _run(tmp_path, "a")
    second, bytes_second = _run(tmp_path, "b")
    assert isinstance(first, Approved) and isinstance(second, Approved)
    assert first == second
    assert bytes_first == bytes_second


def test_identical_inputs_identical_rejection(tmp_path):
    outs = []
    for tag in ("a", "b"):
        sub = tmp_path / tag
        sub.mkdir()
        policy = make_policy(sub)
        policy.reconcile_day(10000.0)
        outs.append(policy.evaluate(
            build_intent(INTENTS["tiny_stop"]), build_account(ACCOUNTS["healthy_10k"])))
    assert all(isinstance(o, Rejected) for o in outs)
    assert outs[0] == outs[1]
