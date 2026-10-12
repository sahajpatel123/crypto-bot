"""Selector tests (manager-owned, S6)."""
from datetime import datetime, timedelta, timezone

from cryptobot.coordination import (DataQuality, ForecastCost, Intent, Side,
                                    encode_exit_rule)
from cryptobot.coordination.exits import ExitPolicy
from cryptobot.coordination.selector import (Candidate, Selector,
                                             SelectorConfig)

NOW = datetime(2026, 10, 12, 6, 0, tzinfo=timezone.utc)


def _intent(strategy="S1", instrument="BTCUSDT", side=Side.LONG,
            expiry=NOW + timedelta(seconds=60), dq=DataQuality.CLEAN,
            rule=None, cost_bps=16.0, ts=NOW):
    rule = rule or encode_exit_rule(ExitPolicy(
        stop_price=99.0, target_price=102.0,
        time_exit_utc=NOW + timedelta(seconds=120), policy_id="t"))
    low, high, inval = (100.0, 100.5, 99.0) if side == Side.LONG else (
        100.0, 100.5, 101.0)
    return Intent(strategy=strategy, version="0.1.0", instrument=instrument,
                  side=side, evidence_ts_utc=ts, entry_low=low,
                  entry_high=high, entry_expiry_utc=expiry,
                  invalidation_price=inval, exit_rule=rule,
                  holding_limit_s=120,
                  forecast_cost=ForecastCost(cost_bps / 4, cost_bps / 4,
                                             cost_bps / 4, 0.0),
                  evidence_ref=f"{strategy}:{instrument}:{side.value}",
                  data_quality=dq)


def test_admits_single_intent():
    sel = Selector()
    decision = sel.select([Candidate("S1", _intent())], now_utc=NOW,
                          position_busy=False)
    assert decision.admitted is not None
    assert decision.rejections == ()
    assert decision.scoring_label == "heuristic-v1"


def test_expired_halt_cost_rejected():
    sel = Selector()
    cands = [Candidate("S1", _intent(expiry=NOW - timedelta(seconds=1),
                                     ts=NOW - timedelta(seconds=61))),
             Candidate("S2", _intent(strategy="S2", dq=DataQuality.HALT)),
             Candidate("S3", _intent(strategy="S3", cost_bps=99.0))]
    decision = sel.select(cands, now_utc=NOW, position_busy=False)
    assert decision.admitted is None
    reasons = sorted(r for _, r in decision.rejections)
    assert reasons == ["selection:cost-infeasible", "selection:expired",
                       "selection:halt-quality"]


def test_opposing_stands_aside():
    sel = Selector()
    cands = [Candidate("S1", _intent(side=Side.LONG)),
             Candidate("S2", _intent(strategy="S2", side=Side.SHORT))]
    decision = sel.select(cands, now_utc=NOW, position_busy=False)
    assert decision.admitted is None
    assert all("opposing-stand-aside" in r for _, r in decision.rejections)


def test_dedup_and_single_owner():
    sel = Selector()
    cands = [Candidate("S1", _intent()),
             Candidate("S1", _intent(ts=NOW + timedelta(seconds=1))),
             Candidate("S2", _intent(strategy="S2", instrument="ETHUSDT"))]
    decision = sel.select(cands, now_utc=NOW, position_busy=False)
    assert decision.admitted is not None
    reasons = sorted(r for _, r in decision.rejections)
    assert "selection:dedup" in reasons and "selection:single-owner" in reasons


def test_position_busy_blocks_all():
    sel = Selector()
    decision = sel.select([Candidate("S1", _intent())], now_utc=NOW,
                          position_busy=True)
    assert decision.admitted is None
    assert decision.rejections[0][1] == "selection:position-busy"


def test_undecodable_rule_blocks_unless_legacy():
    strict = Selector()
    d = strict.select([Candidate("S1", _intent(rule="S1_EXIT_V1:take_r=1.5"))],
                      now_utc=NOW, position_busy=False)
    assert d.admitted is None
    assert d.rejections[0][1] == "selection:exit-undecodable"
    legacy = Selector(SelectorConfig(allow_legacy_exit_rules=True))
    d2 = legacy.select([Candidate("S1", _intent(rule="S1_EXIT_V1:take_r=1.5"))],
                       now_utc=NOW, position_busy=False)
    assert d2.admitted is not None and d2.legacy_exit is True


def test_cooldown_blocks_repeat():
    sel = Selector(SelectorConfig(cooldown_s=300))
    first = sel.select([Candidate("S1", _intent())], now_utc=NOW,
                       position_busy=False)
    assert first.admitted is not None
    second = sel.select([Candidate("S1", _intent())],
                        now_utc=NOW + timedelta(seconds=10),
                        position_busy=False)
    assert second.admitted is None
    assert second.rejections[0][1] == "selection:cooldown"


def test_strategy_rejects_pass_through():
    sel = Selector()
    d = sel.select([Candidate("S1:LONG", None, "strategy:no-fire:regime")],
                   now_utc=NOW, position_busy=False)
    assert d.admitted is None
    assert d.rejections == (("S1:LONG", "strategy:no-fire:regime"),)
