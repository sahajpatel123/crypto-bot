"""S4 baseline tests (Worker 1, Q-004): reclaims, ablation, causality."""
import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.coordination import Coordinator, DataQuality, Side
from cryptobot.research.synthetic import (
    SCENARIO_CHOPPY,
    SCENARIO_FLAT,
    SCENARIO_GAP,
    Fixture,
    generate_fixture,
)
from cryptobot.strategies.contract import S4_BASE, S4_FORECAST_COST, S4_SIMPLE
from cryptobot.strategies.s4 import Bar, evaluate_bar, evaluate_side

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
FIRE_BARS = [199, 200, 201]


def _persisted(name):
    d = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return list(Fixture.from_dict(d).bars)


def _fires(bars, arm, side, lo=120, hi=240):
    return [t for t in range(lo, hi)
            if evaluate_side(bars, t, side, arm, "BTCUSDT").intent is not None]


def test_short_reclaim_fires_verified_bars_both_arms():
    bars = _persisted("synth_s4_short.json")
    assert _fires(bars, S4_BASE, Side.SHORT) == FIRE_BARS
    assert _fires(bars, S4_SIMPLE, Side.SHORT) == FIRE_BARS


def test_long_reclaim_mirrors_short():
    bars = _persisted("synth_s4_long.json")
    assert _fires(bars, S4_BASE, Side.LONG) == FIRE_BARS
    assert _fires(bars, S4_SIMPLE, Side.LONG) == FIRE_BARS


def test_quiet_scenarios_never_fire():
    for scenario in (SCENARIO_FLAT, SCENARIO_CHOPPY):
        bars = list(generate_fixture(seed=71, scenario=scenario).bars)
        for arm in (S4_BASE, S4_SIMPLE):
            assert _fires(bars, arm, Side.LONG) == []
            assert _fires(bars, arm, Side.SHORT) == []


def test_pierce_ablation_separation():
    bars = _persisted("synth_s4_short.json")
    level = bars[194]
    assert level is not None
    # Flatten 195..198 (pierce + first decline bar, whose open still pokes
    # above the level) so no pierce exists anywhere near the reclaim.
    flat = [Bar(ts_utc=b.ts_utc, open=level.close, high=level.close,
                low=level.close, close=level.close, volume=b.volume,
                trades=b.trades, buy_frac=b.buy_frac,
                spread_bps=b.spread_bps) if (b is not None and 195 <= i <= 198)
            else b for i, b in enumerate(bars)]
    assert _fires(flat, S4_BASE, Side.SHORT) == []  # no pierce, no signal
    assert _fires(flat, S4_SIMPLE, Side.SHORT) == FIRE_BARS


def test_short_intent_fields_exact():
    bars = _persisted("synth_s4_short.json")
    d = evaluate_side(bars, 199, Side.SHORT, S4_BASE, "BTCUSDT")
    assert d.intent is not None and d.record is not None
    intent, record, log = d.intent, d.record, d.evaluation
    bar = bars[199]
    assert bar is not None
    assert intent.strategy == "S4" and intent.version == "0.1.0"
    assert intent.side == Side.SHORT
    assert intent.evidence_ts_utc == bar.ts_utc
    assert intent.entry_high == bar.close
    assert intent.entry_low == bar.close * 0.9998
    assert intent.entry_expiry_utc == bar.ts_utc + timedelta(seconds=15)
    assert intent.holding_limit_s == 120
    from cryptobot.coordination import decode_exit_rule
    xp = decode_exit_rule(intent.exit_rule)
    assert xp.stop_price == intent.invalidation_price
    assert xp.target_price == bar.close - 1.5 * (intent.invalidation_price - bar.close)
    assert xp.time_exit_utc == bar.ts_utc + timedelta(seconds=120)
    assert xp.policy_id == "S4:stop+target+time"
    assert intent.forecast_cost == S4_FORECAST_COST
    assert intent.data_quality == DataQuality.CLEAN
    assert intent.evidence_ref == record.record_id
    assert intent.invalidation_price > intent.entry_high
    assert log.regime == "failed-breakout-short"
    assert log.trigger == "pierce(6)+reclaim(5)+momentum(10)"


def test_simple_arm_trigger_omits_pierce():
    bars = _persisted("synth_s4_short.json")
    d = evaluate_side(bars, 199, Side.SHORT, S4_SIMPLE, "BTCUSDT")
    assert d.intent is not None
    assert d.evaluation.trigger == "reclaim(5)+momentum(10)"
    assert "pierce=na(S4-S)" in d.evaluation.rejects


def test_long_invalidation_below_entry():
    bars = _persisted("synth_s4_long.json")
    d = evaluate_side(bars, 199, Side.LONG, S4_BASE, "BTCUSDT")
    assert d.intent is not None
    assert d.intent.invalidation_price < d.intent.entry_low
    assert d.evaluation.regime == "failed-breakout-long"


def test_sides_evaluated_separately():
    bars = _persisted("synth_s4_short.json")
    long_d, short_d = evaluate_bar(bars, 199, S4_BASE, "BTCUSDT")
    assert long_d.intent is None and short_d.intent is not None
    assert "reclaim=fail" in long_d.evaluation.rejects


def test_gap_degraded_and_halt_paths():
    bars = list(generate_fixture(seed=71, scenario=SCENARIO_GAP).bars)
    deg = evaluate_side(bars, 165, Side.LONG, S4_BASE, "BTCUSDT")
    assert deg.intent is None
    assert deg.evaluation.data_quality == DataQuality.DEGRADED
    halt = evaluate_side(bars, 210, Side.LONG, S4_BASE, "BTCUSDT")
    assert halt.intent is None
    assert halt.evaluation.data_quality == DataQuality.HALT


def test_insufficient_history():
    bars = _persisted("synth_s4_short.json")
    d = evaluate_side(bars, 119, Side.LONG, S4_BASE, "BTCUSDT")
    assert d.intent is None
    assert d.evaluation.rejects == ("history=fail",)


def test_deterministic_repeat_evaluation():
    bars = _persisted("synth_s4_short.json")
    first = evaluate_bar(bars, 199, S4_SIMPLE, "BTCUSDT")
    second = evaluate_bar(bars, 199, S4_SIMPLE, "BTCUSDT")
    assert first == second


def test_causal_future_mutation_invariant():
    bars = _persisted("synth_s4_short.json")
    before = evaluate_bar(bars, 199, S4_BASE, "BTCUSDT")
    mutated = list(bars)
    for i in range(200, len(mutated)):
        b = mutated[i]
        assert b is not None
        mutated[i] = Bar(ts_utc=b.ts_utc, open=1.0, high=2e9, low=0.5,
                         close=1e9, volume=1e12, trades=1, buy_frac=1.0,
                         spread_bps=0.0)
    assert evaluate_bar(mutated, 199, S4_BASE, "BTCUSDT") == before


def test_intent_flows_through_manager_coordinator():
    bars = _persisted("synth_s4_short.json")
    d = evaluate_side(bars, 199, Side.SHORT, S4_BASE, "BTCUSDT")
    assert d.intent is not None
    decision = Coordinator().select(
        [d.intent], d.intent.evidence_ts_utc + timedelta(seconds=5))
    assert decision.accepted is d.intent
