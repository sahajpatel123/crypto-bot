"""S5 microstructure baseline tests (Worker 1, Q-005)."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.coordination import DataQuality, Side, decode_exit_rule
from cryptobot.strategies.contract import S5_BASE, S5_FORECAST_COST
from cryptobot.strategies.runtime import DepthView, FlowView, MarketView
from cryptobot.strategies.s1 import Bar
from cryptobot.strategies.s5 import S5Params, evaluate_side, evaluate_view

T0 = datetime(2026, 1, 2, tzinfo=timezone.utc)


def _bars(n=40, spread_bps=1.0, close=100.0):
    return tuple(
        Bar(ts_utc=T0 + timedelta(seconds=i), open=close, high=close + 0.5,
            low=close - 0.5, close=close, volume=10.0, trades=5,
            buy_frac=0.5, spread_bps=spread_bps)
        for i in range(n)
    )


def _depth(ev, imb=0.5, spread_bps=2.0):
    return DepthView(99.9, 100.1, 5.0, 1.0, spread_bps, 500.0, 100.0, 10,
                     imb, ev)


def _flow(ev, buy=700.0, sell=300.0, count=100, age_s=0):
    end = ev - timedelta(seconds=age_s)
    return FlowView(buy, sell, 70, 30, 100.0, count,
                    end - timedelta(seconds=5), end)


def _view(bars=None, depth=None, flow=None, quality=DataQuality.CLEAN,
          reason="", now=None, imb=0.5, buy=700.0, sell=300.0):
    bars = bars if bars is not None else _bars()
    ev = bars[-1].ts_utc
    if depth is None and "depth:" not in reason:
        depth = _depth(ev, imb)
    if flow is None and "flow:" not in reason:
        flow = _flow(ev, buy, sell)
    return MarketView("BTCUSDT", bars, ev if now is None else now, depth,
                      flow, quality, reason)


def test_params_frozen_match_spec():
    p = S5Params()
    assert (p.imb_min, p.flow_min, p.flow_min_trades, p.sync_max_age_s) == \
        (0.20, 0.58, 10, 2)
    assert (p.spread_max_bps, p.depth_spread_max_bps) == (3.0, 5.0)
    assert (p.inval_m, p.inval_buf_bps, p.entry_tol_bps, p.entry_expiry_s,
            p.holding_limit_s, p.take_r) == (30, 1.0, 2.0, 15, 120, 1.5)


def test_long_fires_on_agreement():
    d = evaluate_side(_view(), Side.LONG, S5_BASE, "BTCUSDT")
    assert d.intent is not None and d.record is not None
    assert d.evaluation.reason == "fired"
    assert d.intent.side == Side.LONG
    assert d.intent.forecast_cost == S5_FORECAST_COST


def test_short_fires_on_mirrored_agreement():
    d = evaluate_side(_view(imb=-0.5, buy=300.0, sell=700.0), Side.SHORT,
                      S5_BASE, "BTCUSDT")
    assert d.intent is not None
    assert d.intent.side == Side.SHORT


def test_disagreement_rejects_both_legs():
    # Bid book but sell flow: neither side fires.
    v = _view(imb=0.5, buy=300.0, sell=700.0)
    assert evaluate_side(v, Side.LONG, S5_BASE, "BTCUSDT").intent is None
    assert evaluate_side(v, Side.SHORT, S5_BASE, "BTCUSDT").intent is None
    v2 = _view(imb=-0.5, buy=700.0, sell=300.0)
    assert evaluate_side(v2, Side.LONG, S5_BASE, "BTCUSDT").intent is None
    assert evaluate_side(v2, Side.SHORT, S5_BASE, "BTCUSDT").intent is None


def test_weak_signals_reject():
    v = _view(imb=0.10, buy=520.0, sell=480.0)
    assert evaluate_side(v, Side.LONG, S5_BASE, "BTCUSDT").intent is None
    assert evaluate_side(v, Side.SHORT, S5_BASE, "BTCUSDT").intent is None


def test_depth_none_relays_e007_reason():
    v = _view(reason="depth:unsynced-no-snapshot",
              quality=DataQuality.DEGRADED)
    assert v.depth is None
    d = evaluate_side(v, Side.LONG, S5_BASE, "BTCUSDT")
    assert d.intent is None
    assert d.evaluation.reason == "depth:unsynced-no-snapshot"


def test_flow_none_relays_e007_reason():
    v = _view(reason="flow:trade-id-gap", quality=DataQuality.DEGRADED)
    assert v.flow is None
    d = evaluate_side(v, Side.SHORT, S5_BASE, "BTCUSDT")
    assert d.intent is None
    assert d.evaluation.reason == "flow:trade-id-gap"


def test_missing_reason_token_falls_back_without_fabrication():
    bars = _bars()
    ev = bars[-1].ts_utc
    v = MarketView("BTCUSDT", bars, ev, None, _flow(ev),
                   DataQuality.DEGRADED, "")
    d = evaluate_side(v, Side.LONG, S5_BASE, "BTCUSDT")
    assert d.intent is None
    assert d.evaluation.reason == "depth:unavailable"


def test_halt_rejects():
    v = _view(quality=DataQuality.HALT, reason="halt:collector-stop")
    d = evaluate_side(v, Side.LONG, S5_BASE, "BTCUSDT")
    assert d.intent is None
    assert d.evaluation.reason == "halt:collector-stop"


def test_stale_depth_rejects():
    bars = _bars()
    ev = bars[-1].ts_utc
    v = MarketView("BTCUSDT", bars, ev, _depth(ev - timedelta(seconds=30)),
                   _flow(ev), DataQuality.CLEAN, "")
    d = evaluate_side(v, Side.LONG, S5_BASE, "BTCUSDT")
    assert d.intent is None
    assert d.evaluation.reason == "sync:depth-stale"


def test_future_flow_rejects_as_peeking():
    bars = _bars()
    ev = bars[-1].ts_utc
    v = MarketView("BTCUSDT", bars, ev, _depth(ev),
                   _flow(ev + timedelta(seconds=10)), DataQuality.CLEAN, "")
    d = evaluate_side(v, Side.LONG, S5_BASE, "BTCUSDT")
    assert d.intent is None
    assert d.evaluation.reason == "sync:flow-from-future"


def test_short_window_rejects_without_partial_evaluation():
    v = _view(bars=_bars(20))
    d = evaluate_side(v, Side.LONG, S5_BASE, "BTCUSDT")
    assert d.intent is None
    assert d.evaluation.reason == "insufficient-history"


def test_low_trade_count_rejects():
    bars = _bars()
    ev = bars[-1].ts_utc
    v = MarketView("BTCUSDT", bars, ev, _depth(ev),
                   _flow(ev, count=4), DataQuality.CLEAN, "")
    d = evaluate_side(v, Side.LONG, S5_BASE, "BTCUSDT")
    assert d.intent is None
    assert d.evaluation.reason == "flowcount-gate"


def test_wide_spreads_reject():
    assert evaluate_side(_view(bars=_bars(spread_bps=9.0)), Side.LONG,
                         S5_BASE, "BTCUSDT").intent is None
    bars = _bars()
    ev = bars[-1].ts_utc
    v = MarketView("BTCUSDT", bars, ev, _depth(ev, spread_bps=9.0),
                   _flow(ev), DataQuality.CLEAN, "")
    assert evaluate_side(v, Side.LONG, S5_BASE, "BTCUSDT").intent is None


def test_zero_flow_total_is_neutral_not_fire():
    bars = _bars()
    ev = bars[-1].ts_utc
    v = MarketView("BTCUSDT", bars, ev, _depth(ev),
                   _flow(ev, buy=0.0, sell=0.0), DataQuality.CLEAN, "")
    assert evaluate_side(v, Side.LONG, S5_BASE, "BTCUSDT").intent is None
    assert evaluate_side(v, Side.SHORT, S5_BASE, "BTCUSDT").intent is None


def test_long_intent_fields_exact():
    bars = _bars()
    ev = bars[-1].ts_utc
    d = evaluate_side(_view(bars=bars), Side.LONG, S5_BASE, "BTCUSDT")
    assert d.intent is not None
    intent = d.intent
    assert intent.strategy == "S5" and intent.version == "0.1.0"
    assert intent.instrument == "BTCUSDT" and intent.side == Side.LONG
    assert intent.evidence_ts_utc == ev
    assert intent.entry_low == 100.0
    assert intent.entry_high == 100.0 * 1.0002
    assert intent.entry_expiry_utc == ev + timedelta(seconds=15)
    assert intent.holding_limit_s == 120
    assert intent.invalidation_price == 99.5 * 0.9999
    xp = decode_exit_rule(intent.exit_rule)
    assert xp.stop_price == intent.invalidation_price
    assert xp.target_price == 100.0 + 1.5 * (100.0 - intent.invalidation_price)
    assert xp.time_exit_utc == ev + timedelta(seconds=120)
    assert xp.policy_id == "S5:stop+target+time"


def test_evaluate_view_returns_both_sides():
    long_d, short_d = evaluate_view(_view(), S5_BASE, "BTCUSDT")
    assert long_d.intent is not None and short_d.intent is None
    assert long_d.evaluation.side == Side.LONG
    assert short_d.evaluation.side == Side.SHORT


def test_unknown_arm_raises():
    try:
        evaluate_side(_view(), Side.LONG, "S5-X", "BTCUSDT")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for unknown arm")
