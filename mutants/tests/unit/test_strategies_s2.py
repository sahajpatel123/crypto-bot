"""S2 baseline tests (Worker 1, Q-002): triggers, gates, causality, interop."""
import dataclasses
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.coordination import Coordinator, DataQuality, Side
from cryptobot.research.synthetic import (
    SCENARIO_CHOPPY,
    SCENARIO_FLAT,
    SCENARIO_GAP,
    SCENARIO_LONG,
    SCENARIO_S2_LONG,
    SCENARIO_S2_SHORT,
    generate_fixture,
)
from cryptobot.strategies.contract import (
    S2_BASE,
    S2_FLOW,
    S2_VOLUME,
    S2_FORECAST_COST,
)
from cryptobot.strategies.s2 import Bar, evaluate_bar, evaluate_side

FIRE_BARS = [211, 212]
SEED = 31


def _bars(scenario, seed=SEED, **kw):
    return list(generate_fixture(seed=seed, scenario=scenario, **kw).bars)


def _fires(bars, arm, side, lo=120, hi=240):
    return [t for t in range(lo, hi)
            if evaluate_side(bars, t, side, arm, "BTCUSDT").intent is not None]


def test_long_pullback_fires_exact_constructed_bars():
    bars = _bars(SCENARIO_S2_LONG)
    assert _fires(bars, S2_BASE, Side.LONG) == FIRE_BARS


def test_all_arms_fire_on_fully_confirmed_pullback():
    bars = _bars(SCENARIO_S2_LONG)
    assert _fires(bars, S2_VOLUME, Side.LONG) == FIRE_BARS
    assert _fires(bars, S2_FLOW, Side.LONG) == FIRE_BARS


def test_short_pullback_mirrors_long():
    bars = _bars(SCENARIO_S2_SHORT)
    assert _fires(bars, S2_BASE, Side.SHORT) == FIRE_BARS
    assert _fires(bars, S2_VOLUME, Side.SHORT) == FIRE_BARS
    assert _fires(bars, S2_FLOW, Side.SHORT) == FIRE_BARS


def test_quiet_and_breakout_scenarios_never_fire_s2():
    for scenario in (SCENARIO_FLAT, SCENARIO_CHOPPY, SCENARIO_LONG):
        bars = _bars(scenario)
        for arm in (S2_BASE, S2_VOLUME, S2_FLOW):
            assert _fires(bars, arm, Side.LONG) == []
            assert _fires(bars, arm, Side.SHORT) == []


def test_arm_separation_volume_gate():
    bars = _bars(SCENARIO_S2_LONG)
    const_vol = [dataclasses.replace(b, volume=100.0, trades=100) if b else None
                 for b in bars]
    assert _fires(const_vol, S2_BASE, Side.LONG) == FIRE_BARS
    assert _fires(const_vol, S2_VOLUME, Side.LONG) == []


def test_arm_separation_flow_gate():
    bars = _bars(SCENARIO_S2_LONG)
    neutral = [dataclasses.replace(b, buy_frac=0.5) if b else None for b in bars]
    assert _fires(neutral, S2_BASE, Side.LONG) == FIRE_BARS
    assert _fires(neutral, S2_FLOW, Side.LONG) == []


def test_long_intent_fields_exact():
    bars = _bars(SCENARIO_S2_LONG)
    d = evaluate_side(bars, 211, Side.LONG, S2_BASE, "BTCUSDT")
    assert d.intent is not None and d.record is not None
    intent, record, log = d.intent, d.record, d.evaluation
    bar = bars[211]
    assert bar is not None
    assert intent.strategy == "S2" and intent.version == "0.1.0"
    assert intent.instrument == "BTCUSDT" and intent.side == Side.LONG
    assert intent.evidence_ts_utc == bar.ts_utc
    assert intent.entry_low == bar.close
    assert intent.entry_high == bar.close * 1.0002
    assert intent.entry_expiry_utc == bar.ts_utc + timedelta(seconds=15)
    assert intent.holding_limit_s == 120
    from cryptobot.coordination import decode_exit_rule
    xp = decode_exit_rule(intent.exit_rule)
    assert xp.stop_price == intent.invalidation_price
    assert xp.target_price == bar.close + 1.5 * (bar.close - intent.invalidation_price)
    assert xp.time_exit_utc == bar.ts_utc + timedelta(seconds=120)
    assert xp.policy_id == "S2:stop+target+time"
    assert intent.forecast_cost == S2_FORECAST_COST
    assert intent.data_quality == DataQuality.CLEAN
    assert intent.data_quality_reason == "no-gaps-N=120"
    assert intent.evidence_ref == record.record_id
    assert intent.evidence_ref.startswith("S2:0.1.0:BTCUSDT:LONG:")
    assert intent.invalidation_price < intent.entry_low
    assert log.regime == "pullback-long"
    assert "trend(60)+pullback(10)+resume(5)" in log.trigger
    assert "confirm=na(S2)" in log.rejects
    assert record.trigger == log.trigger


def test_short_invalidation_above_entry():
    bars = _bars(SCENARIO_S2_SHORT)
    d = evaluate_side(bars, 211, Side.SHORT, S2_BASE, "BTCUSDT")
    assert d.intent is not None
    assert d.intent.invalidation_price > d.intent.entry_high
    assert d.evaluation.regime == "pullback-short"


def test_sides_evaluated_separately():
    bars = _bars(SCENARIO_S2_LONG)
    long_d, short_d = evaluate_bar(bars, 211, S2_BASE, "BTCUSDT")
    assert long_d.intent is not None and short_d.intent is None
    assert "trend=fail" in short_d.evaluation.rejects
    bars = _bars(SCENARIO_S2_SHORT)
    long_d, short_d = evaluate_bar(bars, 211, S2_BASE, "BTCUSDT")
    assert long_d.intent is None and short_d.intent is not None


def test_gap_degraded_and_halt_paths():
    bars = _bars(SCENARIO_GAP)
    deg = evaluate_side(bars, 165, Side.LONG, S2_BASE, "BTCUSDT")
    assert deg.intent is None
    assert deg.evaluation.data_quality == DataQuality.DEGRADED
    halt = evaluate_side(bars, 210, Side.LONG, S2_BASE, "BTCUSDT")
    assert halt.intent is None
    assert halt.evaluation.data_quality == DataQuality.HALT


def test_insufficient_history():
    bars = _bars(SCENARIO_S2_LONG)
    d = evaluate_side(bars, 119, Side.LONG, S2_BASE, "BTCUSDT")
    assert d.intent is None
    assert d.evaluation.rejects == ("history=fail",)


def test_deterministic_repeat_evaluation():
    bars = _bars(SCENARIO_S2_LONG)
    first = evaluate_bar(bars, 211, S2_FLOW, "BTCUSDT")
    second = evaluate_bar(bars, 211, S2_FLOW, "BTCUSDT")
    assert first == second


def test_causal_future_mutation_invariant():
    bars = _bars(SCENARIO_S2_LONG)
    before = evaluate_bar(bars, 211, S2_VOLUME, "BTCUSDT")
    mutated = list(bars)
    for i in range(212, len(mutated)):
        b = mutated[i]
        assert b is not None
        mutated[i] = Bar(ts_utc=b.ts_utc, open=1.0, high=2e9, low=0.5,
                         close=1e9, volume=1e12, trades=1, buy_frac=1.0,
                         spread_bps=0.0)
    assert evaluate_bar(mutated, 211, S2_VOLUME, "BTCUSDT") == before


def test_intent_flows_through_manager_coordinator():
    bars = _bars(SCENARIO_S2_LONG)
    d = evaluate_side(bars, 211, Side.LONG, S2_BASE, "BTCUSDT")
    assert d.intent is not None
    decision = Coordinator().select(
        [d.intent], d.intent.evidence_ts_utc + timedelta(seconds=5))
    assert decision.accepted is d.intent
