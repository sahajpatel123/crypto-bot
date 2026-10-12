"""V-006 hardening: run-mode filters, margin sizing, ingestion, monitor tick."""
from __future__ import annotations

import dataclasses
import json
from datetime import timedelta

import pytest

from conftest import NOW, build_account, build_intent, load_fixture, make_policy
from cryptobot.accounting import Ledger
from cryptobot.risk import InstrumentFilter, Rejected, RiskConfig, SliceRisk

INTENTS = load_fixture("risk_intents.json")
ACCOUNTS = load_fixture("risk_accounts.json")
TS = "2026-10-11T12:00:00+00:00"

COMPLETE = InstrumentFilter(min_notional_usdt=5.0, qty_step=0.01,
                            max_notional_usdt=1e9, min_qty=0.01,
                            max_qty=1000.0, tick_size=0.1)


def _run_policy(tmp_path, filt=COMPLETE, asof=NOW):
    return make_policy(tmp_path, run_mode=True,
                       instrument_filters={"BTCUSDT": filt}, filters_asof_utc=asof)


# -- run-mode strict filters ------------------------------------------------
def test_run_mode_without_filters_blocks(tmp_path):
    policy = make_policy(tmp_path, run_mode=True)
    policy.reconcile_day(10000.0)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                          build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Rejected) and out.reason == "filters:required-in-run-mode"


def test_run_mode_incomplete_filter_blocks(tmp_path):
    policy = _run_policy(tmp_path, filt=InstrumentFilter())
    policy.reconcile_day(10000.0)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                          build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Rejected) and out.reason == "filters:incomplete"


def test_run_mode_complete_fresh_filters_approve(tmp_path):
    policy = _run_policy(tmp_path)
    policy.reconcile_day(10000.0)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                          build_account(ACCOUNTS["healthy_10k"]))
    from cryptobot.risk import Approved
    assert isinstance(out, Approved)
    assert out.qty == pytest.approx(round(out.qty / 0.01) * 0.01)


def test_run_mode_rejects_non_bool():
    with pytest.raises(ValueError):
        RiskConfig(run_mode="yes")


# -- V-006-F1: satisfiable completeness + MARKET_LOT -----------------------------
VENUE_ONLY = InstrumentFilter(min_notional_usdt=5.0, qty_step=0.01,
                              min_qty=0.01, max_qty=1000.0, tick_size=0.1)


def test_complete_satisfiable_without_operator_cap(tmp_path):
    assert VENUE_ONLY.complete() is True
    assert VENUE_ONLY.max_notional_usdt is None
    policy = make_policy(tmp_path, run_mode=True,
                         instrument_filters={"BTCUSDT": VENUE_ONLY},
                         filters_asof_utc=NOW)
    policy.reconcile_day(10000.0)
    from cryptobot.risk import Approved
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                          build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Approved)


def test_operator_cap_ignored_by_completeness_but_caps_size(tmp_path):
    from cryptobot.risk import Approved
    assert COMPLETE.complete() is True
    policy = _run_policy(tmp_path)
    policy.reconcile_day(10000.0)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                          build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Approved)
    assert out.notional_usdt <= 1e9


def test_market_lot_bounds_apply_where_published(tmp_path):
    from cryptobot.risk import Approved
    filt = InstrumentFilter(min_notional_usdt=5.0, qty_step=0.01,
                            min_qty=0.01, max_qty=1000.0, tick_size=0.1,
                            market_min_qty=0.01, market_max_qty=0.05)
    policy = make_policy(tmp_path, instrument_filters={"BTCUSDT": filt},
                         filters_asof_utc=NOW)
    policy.reconcile_day(10000.0)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                          build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Approved)
    assert out.qty == pytest.approx(0.05)
    strict = InstrumentFilter(min_notional_usdt=5.0, qty_step=0.01,
                              min_qty=0.01, max_qty=1000.0, tick_size=0.1,
                              market_min_qty=1000.0)
    policy2 = make_policy(tmp_path / "b", instrument_filters={"BTCUSDT": strict},
                          filters_asof_utc=NOW)
    (tmp_path / "b").mkdir(exist_ok=True)
    policy2.reconcile_day(10000.0)
    out2 = policy2.evaluate(build_intent(INTENTS["canonical_long"]),
                            build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out2, Rejected) and out2.reason == "skip:min-notional"


# -- margin-aware sizing ------------------------------------------------------
def _with_margin(acct, available, fee=0.0, inflight=0.0):
    return dataclasses.replace(acct, available_margin_usdt=available,
                               fee_buffer_usdt=fee, inflight_exposure_usdt=inflight)


def test_margin_sufficient_matches_unmargined(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    from cryptobot.risk import Approved
    plain = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                            build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(plain, Approved)
    policy.release(plain.reservation_id)
    margined = policy.evaluate(
        build_intent(INTENTS["canonical_long"]),
        _with_margin(build_account(ACCOUNTS["healthy_10k"]), 1e9))
    assert isinstance(margined, Approved)
    assert margined.notional_usdt == pytest.approx(plain.notional_usdt)


def test_margin_shortfall_caps_down_within_budget(tmp_path):
    from cryptobot.risk import Approved
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    plain = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                            build_account(ACCOUNTS["healthy_10k"]))
    policy.release(plain.reservation_id)
    available = plain.notional_usdt * 0.5 / 3.0
    capped = policy.evaluate(
        build_intent(INTENTS["canonical_long"]),
        _with_margin(build_account(ACCOUNTS["healthy_10k"]), available))
    assert isinstance(capped, Approved)
    assert capped.notional_usdt < plain.notional_usdt
    assert capped.notional_usdt <= plain.notional_usdt * 0.5 * (1 + 1e-9)
    adverse = 67010.0
    planned = capped.qty * 160.0 + capped.qty * adverse * 0.00225
    assert planned <= 25.0 * (1 + 1e-9)


def test_margin_insufficient_rejects_and_buffers_count(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    acct = build_account(ACCOUNTS["healthy_10k"])
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]), _with_margin(acct, 1.0))
    assert isinstance(out, Rejected) and out.reason == "margin:insufficient"
    out2 = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                           _with_margin(acct, 1e9, fee=1e9))
    assert isinstance(out2, Rejected) and out2.reason == "margin:insufficient"
    out3 = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                           _with_margin(acct, 1e9, inflight=1e12))
    assert isinstance(out3, Rejected) and out3.reason == "margin:insufficient"


def test_bad_margin_inputs_rejected(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    acct = build_account(ACCOUNTS["healthy_10k"])
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                          _with_margin(acct, float("nan")))
    assert isinstance(out, Rejected) and out.reason == "health:nonfinite-account"
    out2 = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                           _with_margin(acct, 100.0, fee=-1.0))
    assert isinstance(out2, Rejected) and out2.reason == "health:nonfinite-account"


# -- qty / notional bounds ------------------------------------------------------
def test_min_qty_skips_and_max_qty_caps(tmp_path):
    from cryptobot.risk import Approved
    filt = InstrumentFilter(min_notional_usdt=5.0, qty_step=0.01, min_qty=1000.0)
    policy = make_policy(tmp_path, instrument_filters={"BTCUSDT": filt},
                         filters_asof_utc=NOW)
    policy.reconcile_day(10000.0)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                          build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Rejected) and out.reason == "skip:min-notional"
    filt2 = InstrumentFilter(min_notional_usdt=5.0, qty_step=0.01, max_qty=0.05)
    policy2 = make_policy(tmp_path / "b", instrument_filters={"BTCUSDT": filt2},
                          filters_asof_utc=NOW)
    (tmp_path / "b").mkdir(exist_ok=True)
    policy2.reconcile_day(10000.0)
    out2 = policy2.evaluate(build_intent(INTENTS["canonical_long"]),
                            build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out2, Approved)
    assert out2.qty == pytest.approx(0.05)


def test_max_notional_caps_and_unfittable_rejects(tmp_path):
    from cryptobot.risk import Approved
    filt = InstrumentFilter(min_notional_usdt=5.0, max_notional_usdt=1000.0)
    policy = make_policy(tmp_path, instrument_filters={"BTCUSDT": filt},
                         filters_asof_utc=NOW)
    policy.reconcile_day(10000.0)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                          build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Approved)
    assert out.notional_usdt <= 1000.0 * (1 + 1e-9)
    tiny = InstrumentFilter(min_notional_usdt=1e-6, max_notional_usdt=1e-6)
    policy2 = make_policy(tmp_path / "b", instrument_filters={"BTCUSDT": tiny},
                          filters_asof_utc=NOW)
    (tmp_path / "b").mkdir(exist_ok=True)
    policy2.reconcile_day(10000.0)
    out2 = policy2.evaluate(build_intent(INTENTS["canonical_long"]),
                            build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out2, Rejected) and out2.reason == "filters:notional-cap"


# -- engine ingestion API -------------------------------------------------------
def test_ledger_note_fill_and_funding():
    ledger = Ledger(1000.0)
    assert ledger.note_fill("e1", "BTCUSDT", "BUY", 1.0, 100.0, 2.0, TS) is True
    assert ledger.note_fill("e1", "BTCUSDT", "BUY", 1.0, 100.0, 2.0, TS) is False
    assert ledger.note_funding("f1", -0.5, TS) is True
    assert ledger.note_funding("f1", -0.5, TS) is False
    assert ledger.position_qty() == 1.0
    assert ledger.paid_costs() == 2.0
    assert ledger.funding_net() == -0.5
    journal = ledger.to_dict()["journal"]
    assert journal[0]["symbol"] == "BTCUSDT"


def test_ledger_note_validation():
    ledger = Ledger(1000.0)
    with pytest.raises(ValueError):
        ledger.note_fill("", "BTCUSDT", "BUY", 1.0, 100.0, 1.0, TS)
    with pytest.raises(ValueError):
        ledger.note_fill("e1", "", "BUY", 1.0, 100.0, 1.0, TS)
    with pytest.raises(ValueError):
        ledger.note_fill("e1", "BTCUSDT", "HOLD", 1.0, 100.0, 1.0, TS)
    with pytest.raises(ValueError):
        ledger.note_fill("e1", "BTCUSDT", "BUY", 1.0, 100.0, 1.0, "2026-10-11T12:00:00")
    with pytest.raises(ValueError):
        ledger.note_funding("", 1.0, TS)


def test_policy_note_funding_routes_and_fail_closed(tmp_path):
    from conftest import make_clock
    gate = SliceRisk(state_path=tmp_path / "s.json", day_start_equity=1000.0,
                     now_utc=make_clock())
    gate.policy.note_funding("f1", -3.0, TS)
    assert gate.ledger.funding_net() == -3.0
    assert gate.ledger.net_realised() == -3.0
    bare = make_policy(tmp_path / "b")
    (tmp_path / "b").mkdir(exist_ok=True)
    bare.reconcile_day(10000.0)
    with pytest.raises(ValueError, match="bound ledger"):
        bare.note_funding("f1", -3.0, TS)


def test_run_mode_rejects_zero_fee_and_zero_funding(tmp_path):
    policy = _run_policy(tmp_path)
    policy.reconcile_day(10000.0)
    with pytest.raises(ValueError, match="fee must be > 0 in run mode"):
        policy.note_fill_delta("r-1", "e0", "BTCUSDT", "BUY", 1.0, 100.0, 0.0, TS)
    policy.note_fill_delta("r-1", "e1", "BTCUSDT", "BUY", 1.0, 100.0, 0.5, TS)
    assert policy.booked_net("r-1") == 1.0


# -- timer-driven monitor tick ----------------------------------------------------
def test_monitor_tick_without_account_rolls_and_reports(tmp_path):
    from datetime import datetime
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    status = policy.monitor_tick(NOW)
    assert status.ok is True and status.reasons == ()
    saved = json.loads((tmp_path / "risk_state.json").read_text())
    assert saved["last_tick_utc"] == NOW.isoformat()
    later = datetime.fromisoformat("2026-10-11T18:30:01+00:00")
    rolled = make_policy(tmp_path, now=later)
    status2 = rolled.monitor_tick()
    assert status2.ok is False
    assert "health:day-open-needs-reconciliation" in status2.reasons
    assert "day-rolled" in status2.latched


def test_monitor_tick_settles_expiry_without_intent(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    from cryptobot.risk import Approved
    first = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                            build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(first, Approved)
    late = make_policy(tmp_path, now=NOW + timedelta(minutes=5))
    status = late.monitor_tick()
    assert "expiry-settled" in status.latched
    assert late.unresolved_ids() == (first.reservation_id,)


def test_monitor_tick_invalid_account_fails_closed(tmp_path):
    policy = make_policy(tmp_path)
    policy.reconcile_day(10000.0)
    bad = dataclasses.replace(build_account(ACCOUNTS["healthy_10k"]),
                              marked_equity=float("nan"))
    status = policy.monitor_tick(NOW, bad)
    assert status.ok is False and status.reasons == ("health:nonfinite-account",)
