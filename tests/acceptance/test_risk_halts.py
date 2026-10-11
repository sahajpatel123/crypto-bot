"""R-005 reservation persistence, R-006 daily halt, R-007 target pause."""
from __future__ import annotations

import json
import shutil
from datetime import datetime

from conftest import FIXTURES, NOW, build_account, build_intent, load_fixture, make_policy
from cryptobot.risk import Approved, Rejected

INTENTS = load_fixture("risk_intents.json")
ACCOUNTS = load_fixture("risk_accounts.json")


def _ready(tmp_path, day_start=10000.0):
    policy = make_policy(tmp_path)
    policy.reconcile_day(day_start)
    return policy


def test_halt_trigger_blocks_and_survives_restart(tmp_path):
    policy = _ready(tmp_path)
    acct = build_account(ACCOUNTS["halt_trigger"])
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]), acct)
    assert isinstance(out, Rejected) and out.reason == "halt:daily-loss"
    restarted = make_policy(tmp_path)  # same state file: crash/restart
    out2 = restarted.evaluate(
        build_intent(INTENTS["canonical_long"]), build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out2, Rejected) and out2.reason == "halt:daily-loss"


def test_just_above_halt_passes(tmp_path):
    out = _ready(tmp_path).evaluate(
        build_intent(INTENTS["canonical_long"]), build_account(ACCOUNTS["just_above_halt"]))
    assert isinstance(out, Approved)


def test_halt_boundary_inclusive(tmp_path):
    policy = _ready(tmp_path, day_start=10000.0)
    threshold = 10000.0 * (1 - 0.01)
    base = dict(ACCOUNTS["healthy_10k"])
    base["marked_equity"] = threshold
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]), build_account(base))
    assert isinstance(out, Rejected) and out.reason == "halt:daily-loss"


def test_halt_does_not_carry_past_day_rollover(tmp_path):
    policy = _ready(tmp_path)
    policy.evaluate(build_intent(INTENTS["canonical_long"]), build_account(ACCOUNTS["halt_trigger"]))
    next_day = datetime.fromisoformat("2026-10-11T18:30:01+00:00")  # 2026-10-12 IST
    day2_spec = dict(INTENTS["canonical_long"])
    day2_spec["evidence_ts_utc"] = "2026-10-11T18:29:55+00:00"
    day2_spec["entry_expiry_utc"] = "2026-10-11T18:31:00+00:00"
    rolled = make_policy(tmp_path, now=next_day)
    out = rolled.evaluate(build_intent(day2_spec), build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Rejected) and out.reason == "health:day-open-needs-reconciliation"
    rolled.reconcile_day(10000.0)
    assert isinstance(rolled.evaluate(
        build_intent(day2_spec), build_account(ACCOUNTS["healthy_10k"])), Approved)


def test_crash_snapshot_restores_halt_and_reservation(tmp_path):
    state_path = tmp_path / "risk_state.json"
    shutil.copy(FIXTURES / "risk_state_crash.json", state_path)
    policy = make_policy(tmp_path)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]), build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Rejected) and out.reason == "halt:daily-loss"
    # Reservation restored too: with the halt lifted for the probe, it still blocks.
    # (Probe account sits above the snapshot's armed 10084 profit floor.)
    snap = json.loads(state_path.read_text())
    snap["halt_days"] = {}
    state_path.write_text(json.dumps(snap))
    policy2 = make_policy(tmp_path)
    out2 = policy2.evaluate(
        build_intent(INTENTS["canonical_long"]),
        build_account(ACCOUNTS["profit_armed_above_floor"]))
    assert isinstance(out2, Rejected) and out2.reason == "exposure:one-position"


def test_target_pause_blocks_entries_and_persists(tmp_path):
    policy = _ready(tmp_path)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]), build_account(ACCOUNTS["target_hit"]))
    assert isinstance(out, Rejected) and out.reason == "pause:daily-target"
    restarted = make_policy(tmp_path)
    out2 = restarted.evaluate(
        build_intent(INTENTS["canonical_long"]), build_account(ACCOUNTS["just_below_target"]))
    assert isinstance(out2, Rejected) and out2.reason == "pause:daily-target"


def test_just_below_target_passes(tmp_path):
    out = _ready(tmp_path).evaluate(
        build_intent(INTENTS["canonical_long"]), build_account(ACCOUNTS["just_below_target"]))
    assert isinstance(out, Approved)
