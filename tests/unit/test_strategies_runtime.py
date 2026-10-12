"""Runtime boundary tests (Worker 1, Q-005): S1 seam, adapters, gates."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.coordination import DataQuality, Side, decode_exit_rule
from cryptobot.research.synthetic import SCENARIO_LONG, generate_fixture
from cryptobot.strategies.runtime import (
    ADAPTERS,
    DepthView,
    FlowView,
    MarketView,
    StrategyOutcome,
    get_adapter,
)
from cryptobot.strategies.s1 import Bar

T0 = datetime(2026, 1, 2, tzinfo=timezone.utc)


def _bars(n=40, spread_bps=1.0, close=100.0):
    return tuple(
        Bar(ts_utc=T0 + timedelta(seconds=i), open=close, high=close + 0.5,
            low=close - 0.5, close=close, volume=10.0, trades=5,
            buy_frac=0.5, spread_bps=spread_bps)
        for i in range(n)
    )


def _s5_view():
    bars = _bars(40)
    ev = bars[-1].ts_utc
    depth = DepthView(99.9, 100.1, 5.0, 1.0, 2.0, 500.0, 100.0, 10, 0.5,
                      ev)
    flow = FlowView(700.0, 300.0, 70, 30, 100.0, 100,
                    ev - timedelta(seconds=5), ev)
    return MarketView("BTCUSDT", bars, ev, depth, flow, DataQuality.CLEAN)


def _quiet_view():
    bars = _bars(200)
    return MarketView("BTCUSDT", bars, bars[-1].ts_utc, None, None,
                      DataQuality.CLEAN)


def test_registry_covers_s1_to_s5():
    assert [a.strategy_id for a in ADAPTERS] == ["S1", "S2", "S3", "S4", "S5"]
    assert get_adapter("S3").strategy_id == "S3"
    try:
        get_adapter("S9")
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError for unknown strategy")


def test_outcome_invariant_exactly_one_set():
    bars = _bars(40)
    v = MarketView("BTCUSDT", bars, bars[-1].ts_utc, None, None,
                   DataQuality.CLEAN)
    try:
        StrategyOutcome(None, "")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for empty outcome")
    assert v.instrument == "BTCUSDT"


def test_market_view_validates_inputs():
    bars = _bars(40)
    try:
        MarketView("", bars, bars[-1].ts_utc, None, None, DataQuality.CLEAN)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for empty instrument")
    try:
        MarketView("BTCUSDT", bars, datetime(2026, 1, 2), None, None,
                   DataQuality.CLEAN)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for naive now_utc")


def test_halt_rejects_at_boundary_for_all_adapters():
    bars = _bars(200)
    v = MarketView("BTCUSDT", bars, bars[-1].ts_utc, None, None,
                   DataQuality.HALT, "halt:collector-stop")
    for adapter in ADAPTERS:
        out = adapter.evaluate(v)
        assert out.intent is None
        assert out.reject_reason == "quality:halt:collector-stop"


def test_empty_window_rejects():
    v = MarketView("BTCUSDT", (), T0, None, None, DataQuality.CLEAN)
    out = get_adapter("S1").evaluate(v)
    assert out.intent is None
    assert out.reject_reason == "quality:empty-window"


def test_bar_newer_than_now_rejects_as_stale():
    bars = _bars(200)
    v = MarketView("BTCUSDT", bars, bars[0].ts_utc, None, None,
                   DataQuality.CLEAN)
    out = get_adapter("S1").evaluate(v)
    assert out.intent is None
    assert out.reject_reason == "stale:bar-newer-than-now"


def test_degraded_still_evaluates():
    bars = _bars(200)
    v = MarketView("BTCUSDT", bars, bars[-1].ts_utc, None, None,
                   DataQuality.DEGRADED, "gap-2")
    out = get_adapter("S3").evaluate(v)
    assert out.intent is None
    assert out.reject_reason != "" and "|" in out.reject_reason


def test_double_reject_joins_both_side_reasons():
    out = get_adapter("S1").evaluate(_quiet_view())
    assert out.intent is None
    long_r, short_r = out.reject_reason.split("|")
    assert ":" in long_r and ":" in short_r


def test_each_adapter_returns_outcome_shape():
    # Every adapter returns Intent or explicit reject on a real window.
    for adapter in ADAPTERS:
        out = adapter.evaluate(_quiet_view())
        assert (out.intent is None) != (out.reject_reason == "")
        if out.intent is not None:
            assert out.exit_policy is not None


def test_s5_fire_decodes_to_typed_policy():
    out = get_adapter("S5").evaluate(_s5_view())
    assert out.intent is not None
    assert out.reject_reason == ""
    assert out.exit_policy is not None
    assert out.exit_policy == decode_exit_rule(out.intent.exit_rule)
    assert out.exit_policy.policy_id == "S5:stop+target+time"
    assert out.exit_policy.reduce_only is True


def test_s5_relay_reasons_keep_shape_end_to_end():
    bars = _bars(40)
    ev = bars[-1].ts_utc
    flow = FlowView(700.0, 300.0, 70, 30, 100.0, 100,
                    ev - timedelta(seconds=5), ev)
    v = MarketView("BTCUSDT", bars, ev, None, flow, DataQuality.DEGRADED,
                   "depth:resync-in-flight")
    out = get_adapter("S5").evaluate(v)
    assert out.intent is None
    assert out.reject_reason == "depth:resync-in-flight|depth:resync-in-flight"


def test_s1_fires_on_breakout_fixture_window():
    bars = list(generate_fixture(seed=11, scenario=SCENARIO_LONG).bars)
    window = tuple(b for b in bars[35:156] if b is not None)
    assert len(window) == 121
    v = MarketView("BTCUSDT", window, window[-1].ts_utc, None, None,
                   DataQuality.CLEAN)
    out = get_adapter("S1").evaluate(v)
    assert out.intent is not None, out.reject_reason
    assert out.intent.side == Side.LONG
    assert out.exit_policy is not None
    assert out.exit_policy.policy_id == "S1:stop+target+time"


def test_evaluate_is_pure_no_io():
    # Same view twice -> identical outcome; nothing written to disk.
    import os
    before = set(os.listdir("/tmp"))
    v = _quiet_view()
    first = get_adapter("S4").evaluate(v)
    second = get_adapter("S4").evaluate(v)
    assert (first.intent, first.reject_reason) == \
        (second.intent, second.reject_reason)
    assert set(os.listdir("/tmp")) == before


def _gappy_bars():
    bars = list(_bars(200))
    bars[150] = None
    bars[151] = None
    return tuple(bars)


def test_gappy_window_matches_direct_aligned_evaluation():
    # F1 alignment proof: interior gap inside the S1 window must surface as
    # a gap verdict (not a shifted evaluation), identical to direct
    # evaluate_bar on the same aligned slots.
    from cryptobot.strategies.s1 import evaluate_bar
    bars = _gappy_bars()
    v = MarketView("BTCUSDT", bars, bars[-1].ts_utc, None, None,
                   DataQuality.CLEAN)
    out = get_adapter("S1").evaluate(v)
    long_d, short_d = evaluate_bar(list(bars), 199, "S1", "BTCUSDT")
    assert long_d.intent is None and short_d.intent is None
    assert long_d.evaluation.reason == "gap-2"
    assert out.intent is None
    assert out.reject_reason == "gap:fail|gap:fail"


def test_trailing_nones_anchor_at_last_present():
    # Firing window + trailing Nones: same intent as direct evaluation at
    # the last present bar (stripping would shift windows and differ).
    from cryptobot.strategies.s1 import evaluate_bar
    bars = list(generate_fixture(seed=11, scenario=SCENARIO_LONG).bars)
    window = tuple(b for b in bars[35:156] if b is not None)
    assert len(window) == 121
    gappy = window + (None, None, None)
    v = MarketView("BTCUSDT", gappy, window[-1].ts_utc, None, None,
                   DataQuality.CLEAN)
    out = get_adapter("S1").evaluate(v)
    long_d, _ = evaluate_bar(list(gappy), 120, "S1", "BTCUSDT")
    assert out.intent is not None and long_d.intent is not None
    assert out.intent == long_d.intent
    assert out.intent.evidence_ts_utc == window[-1].ts_utc


def test_all_none_window_rejects_empty():
    v = MarketView("BTCUSDT", (None,) * 40, T0, None, None,
                   DataQuality.CLEAN)
    for adapter in ADAPTERS:
        out = adapter.evaluate(v)
        assert out.intent is None
        assert out.reject_reason == "quality:empty-window"


def test_staleness_uses_last_present_bar():
    bars = list(_bars(200))
    bars[198] = None
    bars[199] = None
    aligned = tuple(bars)
    last_ts = bars[197].ts_utc
    stale = MarketView("BTCUSDT", aligned, last_ts - timedelta(seconds=5),
                       None, None, DataQuality.CLEAN)
    out = get_adapter("S1").evaluate(stale)
    assert out.intent is None
    assert out.reject_reason == "stale:bar-newer-than-now"
    fresh = MarketView("BTCUSDT", aligned, last_ts, None, None,
                       DataQuality.CLEAN)
    out = get_adapter("S1").evaluate(fresh)
    assert out.reject_reason != "stale:bar-newer-than-now"
