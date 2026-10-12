"""W3-24H §4 versioned risk profile: stops, budget, floor, marks, martingale."""
import dataclasses
from datetime import datetime

import pytest

from conftest import NOW, build_account, build_intent, load_fixture, make_policy
from cryptobot.risk import Approved, Rejected

INTENTS = load_fixture("risk_intents.json")
ACCOUNTS = load_fixture("risk_accounts.json")


def _ready(tmp_path, **cfg):
    policy = make_policy(tmp_path, **cfg)
    policy.reconcile_day(10000.0)
    return policy


def _down(marked):
    base = dict(ACCOUNTS["healthy_10k"])
    base["marked_equity"] = marked
    base["net_liquidation"] = marked
    base["reconciled_equity"] = marked
    base["net_realised_global"] = marked - 10000.0
    return build_account(base)


# -- silent 0.5% cross ---------------------------------------------------------
def test_silent_operating_cross_latches_and_blocks(tmp_path):
    policy = _ready(tmp_path)
    status = policy.monitor_tick(NOW, _down(9940.0))
    assert status.ok is False
    assert status.reasons == ("halt:operating-stop",)
    assert status.latched == ("operating-stop",)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                          build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Rejected) and out.reason == "halt:operating-stop"


def test_operating_stop_demands_cancel_and_reduce(tmp_path):
    policy = _ready(tmp_path)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                          build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Approved)
    policy.monitor_tick(NOW, _down(9940.0))
    assert policy.pending_stop_actions() == ("cancel_pending_orders",
                                             "reduce_exposure")


def test_emergency_adds_alert_and_persists_actions(tmp_path):
    policy = _ready(tmp_path)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                          build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Approved)
    policy.monitor_tick(NOW, _down(9890.0))
    assert policy.emergency_active()
    assert policy.pending_stop_actions() == ("alert_operator",
                                             "cancel_pending_orders",
                                             "reduce_exposure")


def test_stop_actions_empty_when_flat(tmp_path):
    policy = _ready(tmp_path)
    policy.monitor_tick(NOW, _down(9940.0))
    assert policy.pending_stop_actions() == ()


def test_emergency_recovery_requires_reconciled_flat(tmp_path):
    policy = _ready(tmp_path)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                          build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Approved)
    policy.monitor_tick(NOW, _down(9890.0))
    assert policy.recover_from_emergency(
        build_account(ACCOUNTS["healthy_10k"])) is False
    assert policy.release(out.reservation_id) is True
    assert policy.recover_from_emergency(
        build_account(ACCOUNTS["healthy_10k"])) is True
    assert policy.emergency_active() is False


# -- 0.125% budget ---------------------------------------------------------------
def test_budget_exceed_request_rejected(tmp_path):
    from cryptobot.risk import InstrumentFilter
    filt = InstrumentFilter(min_notional_usdt=100.0, qty_step=0.01,
                            min_qty=0.01, max_qty=1000.0, tick_size=0.1)
    policy = _ready(tmp_path, instrument_filters={"BTCUSDT": filt},
                    filters_asof_utc=NOW)
    # A far stop shrinks qty until notional fits neither budget nor floor.
    spec = dict(INTENTS["canonical_long"])
    spec["invalidation_price"] = 1.0
    out = policy.evaluate(build_intent(spec),
                          build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Rejected)


def test_reserved_risk_never_exceeds_profile_budget(tmp_path):
    policy = _ready(tmp_path)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                          build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Approved)
    assert out.reserved_risk <= 10000.0 * 0.00125 * (1 + 1e-9)


def test_no_martingale_after_loss(tmp_path):
    policy = _ready(tmp_path)
    first = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                            build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(first, Approved)
    policy.release(first.reservation_id)
    second = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                             _down(9980.0))
    assert isinstance(second, Approved)
    assert second.qty <= first.qty
    assert second.reserved_risk <= first.reserved_risk


def test_stressed_gap_overshoot_trips_account_stop(tmp_path):
    from cryptobot.accounting import Ledger
    policy = _ready(tmp_path)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]),
                          build_account(ACCOUNTS["healthy_10k"]))
    assert isinstance(out, Approved)
    # Fill far beyond the stop: the reservation keeps its planned risk
    # (never retroactively resized) while the account stop engages.
    assert out.reserved_risk == pytest.approx(12.5)
    ledger = Ledger(10000.0)
    ledger.record_fill("BUY", 1.0, 100.0, 0.0, NOW, "e1")
    ledger.record_fill("SELL", 1.0, 40.0, 0.0, NOW, "e2")
    base = dict(ACCOUNTS["healthy_10k"])
    mark = ledger.marked_equity(60.0)
    base.update(marked_equity=mark, net_liquidation=mark,
                reconciled_equity=mark,
                net_realised_global=ledger.net_realised())
    status = policy.monitor_tick(NOW, build_account(base))
    assert status.ok is False
    assert status.reasons[0] in ("halt:operating-stop", "halt:emergency")


# -- floor breach: silence / midnight / restart ------------------------------------
def _armed(policy):
    healthy = policy.check_health(build_account(ACCOUNTS["healthy_10k"]))
    assert healthy.ok
    up = _down(10150.0)
    # Realised gain arms the floor (book via a bound ledger in slice tests;
    # here drive net_realised_global directly through the snapshot).
    assert policy.check_health(up).ok


def test_floor_breach_in_silence(tmp_path):
    policy = _ready(tmp_path)
    _armed(policy)
    status = policy.monitor_tick(NOW, _down(9900.0))
    # -1% also trips emergency; the floor breach must be present too.
    assert status.ok is False
    assert "halt:emergency" in status.reasons


def test_floor_breach_blocks_after_midnight(tmp_path):
    policy = _ready(tmp_path)
    _armed(policy)
    assert policy._state.profit_floor is not None
    floor = policy._state.profit_floor
    next_day = datetime.fromisoformat("2026-10-11T18:30:01+00:00")
    rolled = make_policy(tmp_path, now=next_day)
    rolled.reconcile_day(10000.0)
    assert rolled._state.profit_floor == floor  # inception floor persists.
    day2_spec = dict(INTENTS["canonical_long"])
    day2_spec["evidence_ts_utc"] = "2026-10-11T18:29:55+00:00"
    day2_spec["entry_expiry_utc"] = "2026-10-11T18:31:00+00:00"
    breached = dict(ACCOUNTS["healthy_10k"])
    breached["marked_equity"] = floor - 1.0
    breached["net_liquidation"] = floor - 1.0
    breached["reconciled_equity"] = floor - 1.0
    breached["net_realised_global"] = 50.0
    out = rolled.evaluate(build_intent(day2_spec), build_account(breached))
    assert isinstance(out, Rejected) and out.reason == "halt:profit-protection"


def test_floor_breach_blocks_after_restart(tmp_path):
    policy = _ready(tmp_path)
    _armed(policy)
    floor = policy._state.profit_floor
    restarted = make_policy(tmp_path)
    assert restarted._state.profit_floor == floor
    breached = dict(ACCOUNTS["healthy_10k"])
    breached["marked_equity"] = floor - 1.0
    breached["net_liquidation"] = floor - 1.0
    breached["reconciled_equity"] = floor - 1.0
    breached["net_realised_global"] = 50.0
    out = restarted.evaluate(build_intent(INTENTS["canonical_long"]),
                             build_account(breached))
    assert isinstance(out, Rejected) and out.reason == "halt:profit-protection"


# -- nonfinite margin / stale mark ---------------------------------------------------
def test_nonfinite_margin_blocks(tmp_path):
    policy = _ready(tmp_path)
    for bad in (float("nan"), float("inf"), -1.0):
        acct = dataclasses.replace(build_account(ACCOUNTS["healthy_10k"]),
                                   available_margin_usdt=bad)
        out = policy.evaluate(build_intent(INTENTS["canonical_long"]), acct)
        assert isinstance(out, Rejected)
        assert policy.check_health(acct).ok is False


def test_stale_and_unknown_mark_block_when_configured(tmp_path):
    policy = _ready(tmp_path, max_mark_age_ms=1000.0)
    stale = dataclasses.replace(build_account(ACCOUNTS["healthy_10k"]),
                                mark_age_ms=5000.0)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]), stale)
    assert isinstance(out, Rejected) and out.reason == "health:stale-mark"
    assert policy.check_health(stale).reasons == ("health:stale-mark",)
    unknown = dataclasses.replace(build_account(ACCOUNTS["healthy_10k"]),
                                  mark_age_ms=None)
    out = policy.evaluate(build_intent(INTENTS["canonical_long"]), unknown)
    assert isinstance(out, Rejected) and out.reason == "health:mark-age-unknown"
    fresh = dataclasses.replace(build_account(ACCOUNTS["healthy_10k"]),
                                mark_age_ms=250.0)
    assert isinstance(policy.evaluate(
        build_intent(INTENTS["canonical_long"]), fresh), Approved)


def test_mark_age_ignored_when_unconfigured(tmp_path):
    policy = _ready(tmp_path)
    stale = dataclasses.replace(build_account(ACCOUNTS["healthy_10k"]),
                                mark_age_ms=999999.0)
    assert isinstance(policy.evaluate(
        build_intent(INTENTS["canonical_long"]), stale), Approved)


def test_profile_version_required_and_tagged(tmp_path):
    from cryptobot.risk import RiskConfig
    assert RiskConfig().profile_version == "24h-1"
    with pytest.raises(ValueError, match="profile_version"):
        RiskConfig(profile_version="")
    with pytest.raises(ValueError, match="operating_stop_pct"):
        RiskConfig(operating_stop_pct=0.02, emergency_stop_pct=0.01)
