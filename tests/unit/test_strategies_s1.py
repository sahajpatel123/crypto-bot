"""S1 baseline tests (Worker 1, Q-001): triggers, gates, causality, interop."""
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
    SCENARIO_SHORT,
    SCENARIO_WIDE_SPREAD,
    generate_fixture,
)
from cryptobot.strategies.contract import (
    ARM_BASE,
    ARM_FLOW,
    ARM_VOLUME,
    S1_FORECAST_COST,
)
from cryptobot.strategies.s1 import Bar, evaluate_bar, evaluate_side

FIRE_BARS = [154, 155, 156, 157, 158, 159]


def _bars(scenario, seed=11, **kw):
    return list(generate_fixture(seed=seed, scenario=scenario, **kw).bars)


def _fires(bars, arm, side, lo=120, hi=240):
    return [t for t in range(lo, hi)
            if evaluate_side(bars, t, side, arm, "BTCUSDT").intent is not None]


def test_long_breakout_fires_exact_constructed_bars():
    bars = _bars(SCENARIO_LONG)
    assert _fires(bars, ARM_BASE, Side.LONG) == FIRE_BARS


def test_all_arms_fire_on_fully_confirmed_breakout():
    bars = _bars(SCENARIO_LONG)
    assert _fires(bars, ARM_VOLUME, Side.LONG) == FIRE_BARS
    assert _fires(bars, ARM_FLOW, Side.LONG) == FIRE_BARS


def test_short_breakout_mirrors_long():
    bars = _bars(SCENARIO_SHORT)
    assert _fires(bars, ARM_BASE, Side.SHORT) == FIRE_BARS
    assert _fires(bars, ARM_VOLUME, Side.SHORT) == FIRE_BARS
    assert _fires(bars, ARM_FLOW, Side.SHORT) == FIRE_BARS


def test_quiet_scenarios_never_fire():
    for scenario in (SCENARIO_FLAT, SCENARIO_CHOPPY, SCENARIO_WIDE_SPREAD):
        bars = _bars(scenario)
        for arm in (ARM_BASE, ARM_VOLUME, ARM_FLOW):
            assert _fires(bars, arm, Side.LONG) == []
            assert _fires(bars, arm, Side.SHORT) == []


def test_arm_separation_volume_gate():
    bars = _bars(SCENARIO_LONG)
    const_vol = [dataclasses.replace(b, volume=100.0, trades=100) if b else None
                 for b in bars]
    assert _fires(const_vol, ARM_BASE, Side.LONG) == FIRE_BARS
    assert _fires(const_vol, ARM_VOLUME, Side.LONG) == []  # z = 0 on flat tape


def test_arm_separation_flow_gate():
    bars = _bars(SCENARIO_LONG)
    neutral = [dataclasses.replace(b, buy_frac=0.5) if b else None for b in bars]
    assert _fires(neutral, ARM_BASE, Side.LONG) == FIRE_BARS
    assert _fires(neutral, ARM_FLOW, Side.LONG) == []  # mean 0.5 < 0.58


def test_long_intent_fields_exact():
    bars = _bars(SCENARIO_LONG)
    d = evaluate_side(bars, 154, Side.LONG, ARM_BASE, "BTCUSDT")
    assert d.intent is not None and d.record is not None
    intent, record, log = d.intent, d.record, d.evaluation
    bar = bars[154]
    assert bar is not None
    assert intent.strategy == "S1" and intent.version == "0.1.0"
    assert intent.instrument == "BTCUSDT" and intent.side == Side.LONG
    assert intent.evidence_ts_utc == bar.ts_utc
    assert intent.entry_low == bar.close
    assert intent.entry_high == bar.close * 1.0002
    assert intent.entry_expiry_utc == bar.ts_utc + timedelta(seconds=15)
    assert intent.holding_limit_s == 120
    assert intent.exit_rule == "S1_EXIT_V1:take_r=1.5,stop_r=1.0"
    assert intent.forecast_cost == S1_FORECAST_COST
    assert intent.data_quality == DataQuality.CLEAN
    assert intent.data_quality_reason == "no-gaps-N=120"
    assert intent.evidence_ref == record.record_id
    assert intent.evidence_ref.startswith("S1:0.1.0:BTCUSDT:LONG:")
    assert intent.invalidation_price < intent.entry_low
    assert log.regime == "breakout-long"
    assert "donchian_high" in log.trigger
    assert "confirm=na(S1)" in log.rejects
    assert record.trigger == log.trigger


def test_short_invalidation_above_entry():
    bars = _bars(SCENARIO_SHORT)
    d = evaluate_side(bars, 154, Side.SHORT, ARM_BASE, "BTCUSDT")
    assert d.intent is not None
    assert d.intent.invalidation_price > d.intent.entry_high
    assert d.evaluation.regime == "breakout-short"


def test_sides_evaluated_separately():
    bars = _bars(SCENARIO_LONG)
    long_d, short_d = evaluate_bar(bars, 154, ARM_BASE, "BTCUSDT")
    assert long_d.intent is not None and short_d.intent is None
    assert "breakout=fail" in short_d.evaluation.rejects
    bars = _bars(SCENARIO_SHORT)
    long_d, short_d = evaluate_bar(bars, 154, ARM_BASE, "BTCUSDT")
    assert long_d.intent is None and short_d.intent is not None


def test_spread_reject_recorded():
    bars = _bars(SCENARIO_WIDE_SPREAD)
    d = evaluate_side(bars, 154, Side.LONG, ARM_BASE, "BTCUSDT")
    assert d.intent is None and d.record is None
    assert "spread=fail" in d.evaluation.rejects
    assert d.evaluation.reason == "spread-gate"


def test_gap_degraded_and_halt_paths():
    bars = _bars(SCENARIO_GAP)
    deg = evaluate_side(bars, 165, Side.LONG, ARM_BASE, "BTCUSDT")
    assert deg.intent is None
    assert deg.evaluation.data_quality == DataQuality.DEGRADED
    assert deg.evaluation.reason == "gap-3"
    halt = evaluate_side(bars, 210, Side.LONG, ARM_BASE, "BTCUSDT")
    assert halt.intent is None
    assert halt.evaluation.data_quality == DataQuality.HALT


def test_insufficient_history():
    bars = _bars(SCENARIO_LONG)
    d = evaluate_side(bars, 119, Side.LONG, ARM_BASE, "BTCUSDT")
    assert d.intent is None
    assert d.evaluation.rejects == ("history=fail",)


def test_deterministic_repeat_evaluation():
    bars = _bars(SCENARIO_LONG)
    first = evaluate_bar(bars, 154, ARM_FLOW, "BTCUSDT")
    second = evaluate_bar(bars, 154, ARM_FLOW, "BTCUSDT")
    assert first == second


def test_causal_future_mutation_invariant():
    bars = _bars(SCENARIO_LONG)
    before = evaluate_bar(bars, 154, ARM_VOLUME, "BTCUSDT")
    mutated = list(bars)
    for i in range(155, len(mutated)):
        b = mutated[i]
        assert b is not None
        mutated[i] = Bar(ts_utc=b.ts_utc, open=1.0, high=2e9, low=0.5,
                         close=1e9, volume=1e12, trades=1, buy_frac=1.0,
                         spread_bps=0.0)
    assert evaluate_bar(mutated, 154, ARM_VOLUME, "BTCUSDT") == before


def test_intent_flows_through_manager_coordinator():
    bars = _bars(SCENARIO_LONG)
    d = evaluate_side(bars, 154, Side.LONG, ARM_BASE, "BTCUSDT")
    assert d.intent is not None
    decision = Coordinator().select(
        [d.intent], d.intent.evidence_ts_utc + timedelta(seconds=5))
    assert decision.accepted is d.intent
