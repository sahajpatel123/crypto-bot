"""S3 baseline tests (Worker 1, Q-004): fades, filters, causality, interop."""
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
    SCENARIO_S3_LONG,
    Fixture,
    generate_fixture,
)
from cryptobot.strategies.contract import (
    S3_BASE,
    S3_COST,
    S3_FORECAST_COST,
    S3_REGIME,
)
from cryptobot.strategies.s3 import Bar, evaluate_bar, evaluate_side

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
FIRE_BARS = list(range(169, 180)) + list(range(199, 215))


def _persisted(name):
    d = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return list(Fixture.from_dict(d).bars)


def _fires(bars, arm, side, lo=120, hi=240):
    return [t for t in range(lo, hi)
            if evaluate_side(bars, t, side, arm, "BTCUSDT").intent is not None]


def test_long_fade_fires_verified_bars_all_arms():
    bars = _persisted("synth_s3_long.json")
    for arm in (S3_BASE, S3_REGIME, S3_COST):
        assert _fires(bars, arm, Side.LONG) == FIRE_BARS


def test_short_fade_mirrors_long():
    bars = _persisted("synth_s3_short.json")
    for arm in (S3_BASE, S3_REGIME, S3_COST):
        assert _fires(bars, arm, Side.SHORT) == FIRE_BARS


def test_quiet_scenarios_never_fire():
    for scenario in (SCENARIO_FLAT, SCENARIO_CHOPPY):
        bars = list(generate_fixture(seed=51, scenario=scenario).bars)
        for arm in (S3_BASE, S3_REGIME, S3_COST):
            assert _fires(bars, arm, Side.LONG) == []
            assert _fires(bars, arm, Side.SHORT) == []


def test_cost_filter_blocks_narrow_range():
    bars = list(generate_fixture(seed=51, scenario=SCENARIO_S3_LONG,
                                 s3_range_bps=20.0).bars)
    base = _fires(bars, S3_BASE, Side.LONG)
    assert base != []
    assert _fires(bars, S3_COST, Side.LONG) == []
    assert _fires(bars, S3_REGIME, Side.LONG) == base


def test_regime_filter_blocks_wide_range():
    bars = list(generate_fixture(seed=51, scenario=SCENARIO_S3_LONG,
                                 s3_range_bps=150.0).bars)
    base = _fires(bars, S3_BASE, Side.LONG)
    assert base != []
    assert _fires(bars, S3_REGIME, Side.LONG) == []
    assert _fires(bars, S3_COST, Side.LONG) == base


def test_long_intent_fields_exact():
    bars = _persisted("synth_s3_long.json")
    d = evaluate_side(bars, 210, Side.LONG, S3_BASE, "BTCUSDT")
    assert d.intent is not None and d.record is not None
    intent, record, log = d.intent, d.record, d.evaluation
    bar = bars[210]
    assert bar is not None
    assert intent.strategy == "S3" and intent.version == "0.1.0"
    assert intent.instrument == "BTCUSDT" and intent.side == Side.LONG
    assert intent.evidence_ts_utc == bar.ts_utc
    assert intent.entry_high == bar.close
    assert intent.entry_low == bar.close * 0.9998
    assert intent.entry_expiry_utc == bar.ts_utc + timedelta(seconds=15)
    assert intent.holding_limit_s == 120
    from cryptobot.coordination import decode_exit_rule
    xp = decode_exit_rule(intent.exit_rule)
    win = [b for b in bars[210 - 64 + 1:211] if b is not None]
    mid = (max(b.high for b in win) + min(b.low for b in win)) / 2
    assert xp.stop_price == intent.invalidation_price
    assert xp.target_price == mid
    assert xp.time_exit_utc == bar.ts_utc + timedelta(seconds=120)
    assert xp.policy_id == "S3:stop+target+time"
    assert intent.forecast_cost == S3_FORECAST_COST
    assert intent.data_quality == DataQuality.CLEAN
    assert intent.evidence_ref == record.record_id
    assert intent.evidence_ref.startswith("S3:0.1.0:BTCUSDT:LONG:")
    assert intent.invalidation_price < intent.entry_low
    assert log.regime == "range-long"
    assert "range(120)+stall(30)+vwap(60)" in log.trigger
    assert "regime=na(S3)" in log.rejects
    assert "cost=na(S3)" in log.rejects


def test_short_invalidation_above_entry():
    bars = _persisted("synth_s3_short.json")
    d = evaluate_side(bars, 210, Side.SHORT, S3_BASE, "BTCUSDT")
    assert d.intent is not None
    assert d.intent.invalidation_price > d.intent.entry_high
    assert d.evaluation.regime == "range-short"


def test_sides_evaluated_separately():
    bars = _persisted("synth_s3_long.json")
    long_d, short_d = evaluate_bar(bars, 210, S3_BASE, "BTCUSDT")
    assert long_d.intent is not None and short_d.intent is None
    assert "position=fail" in short_d.evaluation.rejects


def test_gap_degraded_and_halt_paths():
    bars = list(generate_fixture(seed=51, scenario=SCENARIO_GAP).bars)
    deg = evaluate_side(bars, 165, Side.LONG, S3_BASE, "BTCUSDT")
    assert deg.intent is None
    assert deg.evaluation.data_quality == DataQuality.DEGRADED
    halt = evaluate_side(bars, 210, Side.LONG, S3_BASE, "BTCUSDT")
    assert halt.intent is None
    assert halt.evaluation.data_quality == DataQuality.HALT


def test_insufficient_history():
    bars = _persisted("synth_s3_long.json")
    d = evaluate_side(bars, 119, Side.LONG, S3_BASE, "BTCUSDT")
    assert d.intent is None
    assert d.evaluation.rejects == ("history=fail",)


def test_deterministic_repeat_evaluation():
    bars = _persisted("synth_s3_long.json")
    first = evaluate_bar(bars, 210, S3_COST, "BTCUSDT")
    second = evaluate_bar(bars, 210, S3_COST, "BTCUSDT")
    assert first == second


def test_causal_future_mutation_invariant():
    bars = _persisted("synth_s3_long.json")
    before = evaluate_bar(bars, 210, S3_REGIME, "BTCUSDT")
    mutated = list(bars)
    for i in range(211, len(mutated)):
        b = mutated[i]
        assert b is not None
        mutated[i] = Bar(ts_utc=b.ts_utc, open=1.0, high=2e9, low=0.5,
                         close=1e9, volume=1e12, trades=1, buy_frac=1.0,
                         spread_bps=0.0)
    assert evaluate_bar(mutated, 210, S3_REGIME, "BTCUSDT") == before


def test_intent_flows_through_manager_coordinator():
    bars = _persisted("synth_s3_long.json")
    d = evaluate_side(bars, 210, Side.LONG, S3_BASE, "BTCUSDT")
    assert d.intent is not None
    decision = Coordinator().select(
        [d.intent], d.intent.evidence_ts_utc + timedelta(seconds=5))
    assert decision.accepted is d.intent
