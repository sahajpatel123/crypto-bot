"""V-007 risk invariants: stop-qty ack, margin-from-sim, funding-to-floor."""
from __future__ import annotations

import dataclasses
import json
from datetime import timedelta

from conftest import NOW, build_account, build_intent, load_fixture, make_policy
from cryptobot.risk import Approved, Rejected, SliceRisk

INTENTS = load_fixture("risk_intents.json")
ACCOUNTS = load_fixture("risk_accounts.json")
TS = "2026-10-11T12:00:00+00:00"


def _approved(tmp_path, **cfg):
    policy = make_policy(tmp_path, **cfg)
    policy.reconcile_day(10000.0)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                          build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Approved)
    return policy, out


# -- B8 ack verification: required position quantity --------------------------
def test_required_stop_qty_matches_approved_live_reservation(tmp_path):
    policy, out = _approved(tmp_path)
    assert out.required_stop_qty == out.qty
    assert policy.required_stop_qty(out.reservation_id) == out.qty


def test_required_stop_qty_survives_release_with_exposure(tmp_path):
    policy, out = _approved(tmp_path)
    policy.note_fill_delta(out.reservation_id, "e1", "BTCUSDT", "BUY",
                           out.qty, 100.0, 0.0, TS)
    assert policy.release(out.reservation_id) is False  # exposure retains block
    assert out.reservation_id in policy.unresolved_ids()
    assert policy.required_stop_qty(out.reservation_id) == out.qty
    assert policy.booked_net(out.reservation_id) == out.qty


def test_required_stop_qty_unknown_id_is_none(tmp_path):
    policy, _ = _approved(tmp_path)
    assert policy.required_stop_qty("no-such-reservation") is None


def test_required_stop_qty_legacy_state_without_qty_is_none(tmp_path):
    policy, out = _approved(tmp_path)
    state_path = tmp_path / "risk_state.json"
    raw = json.loads(state_path.read_text())
    del raw["reservations"][out.reservation_id]["qty"]
    state_path.write_text(json.dumps(raw))
    reloaded = make_policy(tmp_path)
    assert reloaded.required_stop_qty(out.reservation_id) is None


def test_required_stop_qty_persists_across_reload(tmp_path):
    _, out = _approved(tmp_path)
    reloaded = make_policy(tmp_path)
    assert reloaded.required_stop_qty(out.reservation_id) == out.qty


def test_fill_delta_redelivery_is_idempotent(tmp_path):
    policy, out = _approved(tmp_path)
    for _ in range(2):
        policy.note_fill_delta(out.reservation_id, "e1", "BTCUSDT", "BUY",
                               out.qty, 100.0, 0.0, TS)
    assert policy.booked_net(out.reservation_id) == out.qty


# -- margin from sim: identical feed → identical decision ---------------------
def _binding_margin_account():
    return dataclasses.replace(build_account(ACCOUNTS["healthy_10k"]),
                               available_margin_usdt=10.0)


def test_margin_from_sim_is_deterministic_across_fresh_policies(tmp_path):
    outs = []
    for i in range(2):
        policy = make_policy(tmp_path / str(i))
        policy.reconcile_day(10000.0)
        out = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                              _binding_margin_account())
        assert isinstance(out, Approved)
        outs.append(out)
    assert outs[0].qty == outs[1].qty
    assert outs[0].notional_usdt == outs[1].notional_usdt


def test_margin_binding_decision_repeats_after_release(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    intent = build_intent(INTENTS["canonical_long"])
    first = policy.evaluate(intent, _binding_margin_account())
    assert isinstance(first, Approved)
    assert policy.release(first.reservation_id) is True
    second = policy.evaluate(intent, _binding_margin_account())
    assert isinstance(second, Approved)
    assert second.qty == first.qty


def test_margin_insufficient_rejects_deterministically(tmp_path):
    for i in range(2):
        policy = make_policy(tmp_path / str(i))
        policy.reconcile_day(10000.0)
        out = policy.evaluate(
            build_intent(INTENTS["canonical_long"]),
            dataclasses.replace(build_account(ACCOUNTS["healthy_10k"]),
                                available_margin_usdt=0.01))
        assert isinstance(out, Rejected) and out.reason == "margin:insufficient"


# -- funding moves realised → profit floor ratchets and protects --------------
def _slice(tmp_path, name):
    from conftest import make_clock
    return SliceRisk(state_path=tmp_path / name / "risk_state.json",
                     day_start_equity=10000.0, now_utc=make_clock(NOW))


def test_funding_arms_floor_and_drawdown_halts(tmp_path):
    from datetime import timezone
    sl = _slice(tmp_path, "funded")
    sl.ledger.record_funding(150.0, NOW, event_id="f1")
    healthy = sl.policy.check_health(sl.snapshot(100.0, 0.0))
    assert healthy.ok  # floor armed at 10000 + 0.70*150 = 10105, no breach
    sl.ledger.record_funding(-100.0, NOW + timedelta(seconds=1), event_id="f2")
    halted = sl.policy.check_health(sl.snapshot(100.0, 0.0))
    assert halted.ok is False
    assert "halt:profit-protection" in halted.reasons


def test_same_drawdown_without_funding_arms_no_floor(tmp_path):
    sl = _slice(tmp_path, "control")
    sl.ledger.record_funding(-50.0, NOW, event_id="f1")
    status = sl.policy.check_health(sl.snapshot(100.0, 0.0))
    assert status.ok  # realised -50 never arms the floor; no halt
    assert status.reasons == ()
