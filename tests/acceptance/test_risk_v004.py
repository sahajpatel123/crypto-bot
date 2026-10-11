"""V-004 regressions: F-CEO-03/04/06/07, v0.2.0 deltas, monitor, migration."""
from __future__ import annotations

import dataclasses
import json
import shutil
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from conftest import FIXTURES, NOW, build_account, build_intent, load_fixture, make_policy
from cryptobot.coordination import DataQuality
from cryptobot.risk import (
    Approved, InstrumentFilter, Rejected, RiskConfig, SliceRisk, plan_size,
)

INTENTS = load_fixture("risk_intents.json")
ACCOUNTS = load_fixture("risk_accounts.json")
TS = "2026-10-11T12:00:00+00:00"


def _ceo_sizing_intent():
    spec = dict(INTENTS["canonical_long"])
    spec.update(entry_low=100.0, entry_high=110.0, invalidation_price=99.0)
    spec["forecast_cost"] = {"fee_bps": 1, "spread_bps": 1, "slippage_bps": 1, "funding_bps": 0}
    return build_intent(spec)


# -- F-CEO-04 worst-price sizing -------------------------------------------
def test_ceo_adverse_loss_within_budget():
    plan = plan_size(_ceo_sizing_intent(), 1000.0, RiskConfig())
    assert plan.reserved_risk == pytest.approx(2.5)
    loss = plan.qty * 11 + plan.qty * 110 * 3 / 10000 * 1.5
    assert loss <= 2.5 * (1 + 1e-9)
    assert loss == pytest.approx(2.5)
    assert plan.adverse_price == 110.0


def test_short_adverse_is_entry_low(tmp_path):
    spec = dict(INTENTS["canonical_short"])
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    out = policy.evaluate(build_intent(spec), build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Approved)
    assert out.notional_usdt == pytest.approx(out.qty * spec["entry_low"])


def test_quantity_rounded_down_never_up(tmp_path):
    policy = make_policy(tmp_path, )
    policy.reconcile_day(10000.0)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                          build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Approved)
    step = 1e-8
    assert abs(out.qty / step - round(out.qty / step)) < 1e-6


def test_instrument_filter_step_and_minimum(tmp_path):
    cfg = RiskConfig(instrument_filters={"BTCUSDT": InstrumentFilter(5.0, 0.01)},
                     filters_asof_utc=NOW)
    policy = make_policy(tmp_path, **{"instrument_filters": cfg.instrument_filters,
                                      "filters_asof_utc": cfg.filters_asof_utc})
    policy.reconcile_day(10000.0)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                          build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Approved)
    assert abs((out.qty * 100) - round(out.qty * 100)) < 1e-6


def test_unknown_instrument_blocked_when_filters_configured(tmp_path):
    cfg = {"instrument_filters": {"ETHUSDT": InstrumentFilter()}, "filters_asof_utc": NOW}
    policy = make_policy(tmp_path, **cfg)
    policy.reconcile_day(10000.0)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                          build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Rejected) and out.reason == "filters:unknown-instrument"


def test_stale_filters_blocked(tmp_path):
    cfg = {"instrument_filters": {"BTCUSDT": InstrumentFilter()},
           "filters_asof_utc": NOW - timedelta(hours=2)}
    policy = make_policy(tmp_path, **cfg)
    policy.reconcile_day(10000.0)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                          build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Rejected) and out.reason == "filters:stale-metadata"


# -- F-CEO-06 flow-adjusted references --------------------------------------
def test_deposit_does_not_pause_slice(tmp_path):
    from conftest import make_clock
    gate = SliceRisk(state_path=tmp_path / "s.json", day_start_equity=1000.0,
                     now_utc=make_clock())
    gate.ledger.record_flow(30.0, "deposit", NOW)
    assert gate.ledger.net_realised() == 0.0
    out = gate.evaluate(build_intent(INTENTS["canonical_long"]), 67005.0)
    assert out.ok is True, out.reason


def test_withdrawal_does_not_trip_protection_slice(tmp_path):
    from conftest import make_clock
    gate = SliceRisk(state_path=tmp_path / "s.json", day_start_equity=10000.0,
                     now_utc=make_clock())
    gate.ledger.record_fill("BUY", 1.0, 100.0, 0.0, NOW, exec_id="w1")
    gate.ledger.record_fill("SELL", 1.0, 220.0, 0.0, NOW, exec_id="w2")
    assert gate.ledger.net_realised() == 120.0
    gate.ledger.record_flow(-500.0, "transfer-out", NOW)
    out = gate.evaluate(build_intent(INTENTS["canonical_long"]), 220.0)
    assert out.ok is True, out.reason


def test_real_loss_still_halts_after_deposit(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(1000.0, 0.0)
    base = dict(ACCOUNTS["healthy_10k"])
    acct = dataclasses.replace(build_account(base), reconciled_equity=1485.0,
                               marked_equity=1485.0, net_liquidation=1484.0,
                               net_realised_global=-15.0, flows_cumulative=500.0)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]), acct)
    assert isinstance(out, Rejected) and out.reason == "halt:daily-loss"


# -- F-CEO-03 / v0.2.0 exposure books ---------------------------------------
def test_release_with_booked_exposure_retains_block(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    acct = build_account(ACCOUNTS["healthy_10k"])
    first = policy.evaluate(build_intent(INTENTS["canonical_long"]), acct)
    assert isinstance(first, Approved)
    policy.note_fill_delta(first.reservation_id, "x1", "BTCUSDT", "BUY", 0.05, 67000.0, 0.0, TS)
    assert policy.booked_net(first.reservation_id) == pytest.approx(0.05)
    assert policy.release(first.reservation_id) is False
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]), acct)
    assert isinstance(out, Rejected) and out.reason == "exposure:unresolved"


def test_flat_booking_plus_release_lifts_block(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    acct = build_account(ACCOUNTS["healthy_10k"])
    first = policy.evaluate(build_intent(INTENTS["canonical_long"]), acct)
    rid = first.reservation_id
    policy.note_fill_delta(rid, "x1", "BTCUSDT", "BUY", 0.05, 67000.0, 0.0, TS)
    policy.note_fill_delta(rid, "x2", "BTCUSDT", "SELL", 0.05, 67100.0, 0.0, TS)
    assert policy.booked_net(rid) == 0.0
    assert policy.release(rid) is True  # live + zero booked: actually freed
    assert isinstance(policy.evaluate(build_intent(INTENTS["canonical_long"]), acct), Approved)


def test_note_flat_gated_on_net_zero(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    acct = build_account(ACCOUNTS["healthy_10k"])
    first = policy.evaluate(build_intent(INTENTS["canonical_long"]), acct)
    policy.note_fill_delta(first.reservation_id, "x1", "BTCUSDT", "BUY", 0.05, 67000.0, 0.0, TS)
    policy.note_fill(first.reservation_id)
    policy.note_flat()
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]), acct)
    assert isinstance(out, Rejected)  # exposure nonzero: flat ignored
    policy.note_fill_delta(first.reservation_id, "x2", "BTCUSDT", "SELL", 0.05, 67100.0, 0.0, TS)
    policy.note_flat()
    assert isinstance(policy.evaluate(build_intent(INTENTS["canonical_long"]), acct), Approved)


def test_duplicate_delta_ignored(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    policy.note_fill_delta("r-x", "dup1", "BTCUSDT", "BUY", 1.0, 100.0, 0.0, TS)
    policy.note_fill_delta("r-x", "dup1", "BTCUSDT", "BUY", 1.0, 100.0, 0.0, TS)
    assert policy.booked_net("r-x") == 1.0


def test_late_delta_for_unknown_id_blocks(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    policy.note_fill_delta("r-stranger", "s1", "BTCUSDT", "BUY", 1.0, 100.0, 0.0, TS)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                          build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Rejected) and out.reason == "exposure:booked"


@pytest.mark.parametrize("kwargs", [
    {"venue_side": "HOLD"}, {"qty": 0.0}, {"qty": float("nan")},
    {"price": -1.0}, {"fee": -0.5}, {"exec_id": ""}, {"ts_utc": "not-a-time"},
    {"ts_utc": "2026-10-11T12:00:00"},  # naive
    {"ts_utc": "2026-10-11T17:30:00+05:30"},  # non-UTC offset
])
def test_fill_delta_validation_rejects(tmp_path, kwargs):
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    base = {"reservation_id": "r-1", "exec_id": "e-1", "symbol": "BTCUSDT",
            "venue_side": "BUY", "qty": 1.0, "price": 100.0, "fee": 0.0, "ts_utc": TS}
    base.update(kwargs)
    with pytest.raises(ValueError):
        policy.note_fill_delta(**base)


# -- F-CEO-07 validation ----------------------------------------------------
def test_nan_forecast_rejected(tmp_path):
    from cryptobot.coordination import ForecastCost
    spec = dict(INTENTS["canonical_long"])
    intent = build_intent(spec)
    bad = dataclasses.replace(intent, forecast_cost=ForecastCost(float("nan"), 1, 1, 0))
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    out = policy.evaluate(bad, build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Rejected) and out.reason == "health:nonfinite-cost"


def test_nan_price_and_account_rejected(tmp_path):
    spec = dict(INTENTS["canonical_long"])
    intent = dataclasses.replace(build_intent(spec), entry_high=float("nan"))
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    out = policy.evaluate(intent, build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Rejected) and out.reason == "health:nonfinite-price"
    acct = dataclasses.replace(build_account(ACCOUNTS["healthy_10k"]),
                               marked_equity=float("inf"))
    out2 = policy.evaluate(build_intent(spec), acct)
    assert isinstance(out2, Rejected) and out2.reason == "health:nonfinite-account"


def test_invalid_enum_and_timestamps_rejected(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    acct = build_account(ACCOUNTS["healthy_10k"])
    raw_side = dataclasses.replace(build_intent(INTENTS["canonical_long"]), side="LONG")
    assert policy.evaluate(raw_side, acct).reason == "health:invalid-enum"
    # Naive datetimes cannot be built via Intent (its ctor raises first), so
    # the policy-level guard is probed with a structural faux intent.
    real = build_intent(INTENTS["canonical_long"])
    naive = SimpleNamespace(
        side=real.side, data_quality=real.data_quality, entry_low=real.entry_low,
        entry_high=real.entry_high, invalidation_price=real.invalidation_price,
        forecast_cost=real.forecast_cost, holding_limit_s=real.holding_limit_s,
        evidence_ts_utc=datetime(2026, 10, 11, 11, 59, 55),
        entry_expiry_utc=real.entry_expiry_utc, instrument=real.instrument,
        evidence_ref=real.evidence_ref)
    assert policy.evaluate(naive, acct).reason == "stale:naive-timestamp"


def test_boundary_expiry_rejected_and_future_evidence_rejected(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    acct = build_account(ACCOUNTS["healthy_10k"])
    at_edge = dict(INTENTS["canonical_long"])
    at_edge["entry_expiry_utc"] = NOW.isoformat()
    assert policy.evaluate(build_intent(at_edge), acct).reason == "stale:expired"
    future = dict(INTENTS["canonical_long"])
    future["evidence_ts_utc"] = (NOW + timedelta(seconds=30)).isoformat()
    future["entry_expiry_utc"] = (NOW + timedelta(seconds=90)).isoformat()
    assert policy.evaluate(build_intent(future), acct).reason == "stale:future-evidence"
    skewed = dict(INTENTS["canonical_long"])
    skewed["evidence_ts_utc"] = (NOW + timedelta(seconds=3)).isoformat()
    skewed["entry_expiry_utc"] = (NOW + timedelta(seconds=90)).isoformat()
    assert isinstance(policy.evaluate(build_intent(skewed), acct), Approved)


def test_nonpositive_price_rejected(tmp_path):
    spec = dict(INTENTS["canonical_long"])
    spec.update(entry_low=-1.0, entry_high=0.0, invalidation_price=-2.0)
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    out = policy.evaluate(build_intent(spec), build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Rejected) and out.reason == "health:nonpositive-price"


@pytest.mark.parametrize("kwargs", [
    {"leverage_cap": -1.0}, {"stress_multiplier": 0.0}, {"daily_loss_halt_pct": 2.0},
    {"max_loss_budget_pct": float("nan")}, {"max_evidence_age_s": -5.0},
    {"profit_retain_pct": 1.5},
])
def test_bad_config_raises(kwargs):
    with pytest.raises(ValueError):
        RiskConfig(**kwargs)


# -- intent-free monitoring -------------------------------------------------
def test_monitor_latches_halt_without_intent(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    healthy = policy.check_health(build_account(ACCOUNTS["healthy_10k"]))
    assert healthy.ok is True and healthy.latched == ()
    status = policy.check_health(build_account(ACCOUNTS["halt_trigger"]))
    assert status.ok is False and status.reasons == ("halt:daily-loss",)
    assert status.latched == ("halt",)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                          build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Rejected) and out.reason == "halt:daily-loss"


def test_monitor_needs_reconciliation_after_rollover(tmp_path):
    from datetime import datetime
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    rolled = make_policy(tmp_path, now=datetime.fromisoformat("2026-10-11T18:30:01+00:00"))
    status = rolled.check_health(build_account(ACCOUNTS["healthy_10k"]))
    assert status.ok is False
    assert "health:day-open-needs-reconciliation" in status.reasons


# -- state migration --------------------------------------------------------
def test_v1_state_migrates_with_forced_reconcile(tmp_path):
    from cryptobot.risk.state import load_state, save_state
    from cryptobot.risk import RiskPolicy
    state_path = tmp_path / "risk_state.json"
    shutil.copy(FIXTURES / "risk_state_v1.json", state_path)
    state = load_state(state_path)
    assert state.needs_reconciliation is True
    assert state.unresolved == {} and state.booked == {}
    assert state.flow_baseline_day is None
    assert state.halt_days == {"2026-10-11": "daily-loss"}  # v1 content preserved
    policy = make_policy(tmp_path)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                          build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Rejected) and out.reason == "health:day-open-needs-reconciliation"
    policy.reconcile_day(10000.0, 250.0)
    saved = json.loads(state_path.read_text())
    assert saved["version"] == 2
    assert saved["flow_baseline_day"] == 250.0
    assert saved["flow_baseline_inception"] == 250.0
    assert saved["needs_reconciliation"] is False


def test_unknown_state_version_raises(tmp_path):
    from cryptobot.risk.state import RiskState
    with pytest.raises(ValueError, match="unsupported risk-state version"):
        RiskState.from_dict({"version": 99})


# -- V-004 fixup: ledger binding propagation --------------------------------
def test_sink_deltas_reach_paired_ledger(tmp_path):
    from conftest import make_clock
    gate = SliceRisk(state_path=tmp_path / "s.json", day_start_equity=1000.0,
                     now_utc=make_clock())
    # Execution calls the POLICY sink directly (as wired in OrderManager).
    gate.policy.note_fill_delta("r-1", "d1", "BTCUSDT", "BUY", 0.5, 100.0, 1.0, TS)
    assert gate.policy.booked_net("r-1") == pytest.approx(0.5)
    assert gate.ledger.position_qty() == pytest.approx(0.5)
    assert gate.ledger.paid_costs() == pytest.approx(1.0)
    gate.policy.note_fill_delta("r-1", "d1", "BTCUSDT", "BUY", 0.5, 100.0, 1.0, TS)
    assert gate.ledger.position_qty() == pytest.approx(0.5)
    assert gate.ledger.paid_costs() == pytest.approx(1.0)
    assert gate.snapshot(100.0, 15.0).open_position is True


def test_bare_policy_books_state_only(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    policy.note_fill_delta("r-1", "d1", "BTCUSDT", "BUY", 1.0, 100.0, 0.0, TS)
    assert policy.booked_net("r-1") == 1.0


def test_rejected_delta_leaves_ledger_untouched(tmp_path):
    from conftest import make_clock
    gate = SliceRisk(state_path=tmp_path / "s.json", day_start_equity=1000.0,
                     now_utc=make_clock())
    before = gate.ledger.to_dict()
    with pytest.raises(ValueError):
        gate.policy.note_fill_delta("r-1", "bad", "BTCUSDT", "BUY", -1.0, 100.0, 0.0, TS)
    assert gate.ledger.to_dict() == before
