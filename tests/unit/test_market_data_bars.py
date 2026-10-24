"""1s-bar causality tests (Worker 2, E-006). Synthetic trade streams only."""
from cryptobot.market_data.bars import (
    Bar1s,
    BarAggregator,
    BarMissing,
    bar_from_dict,
    bar_to_dict,
    to_s1_bar,
)


def _trade(ts_ms, trade_id, price=100.0, qty=1.0, maker=False):
    return {"exchange_ts_ms": ts_ms,
            "payload": {"agg_id": trade_id, "price": price, "qty": qty,
                        "buyer_is_maker": maker}}


def test_bars_close_only_past_watermark_and_stay_causal():
    agg = BarAggregator("BTCUSDT", lateness_ms=500)
    assert agg.on_trade(_trade(1000, 1, 100.0)) == []  # watermark 500: nothing closes.
    out = agg.on_trade(_trade(2600, 2, 101.0))
    assert len(out) == 1 and isinstance(out[0], Bar1s)  # window [1000,2000) closed.
    assert (out[0].symbol, out[0].window_start_ms) == ("BTCUSDT", 1000)
    assert (out[0].open, out[0].close, out[0].volume) == (100.0, 100.0, 1.0)
    first = out[0]
    agg.on_trade(_trade(2601, 3, 500.0))  # far-future price cannot revise the closed bar.
    assert first.close == 100.0
    assert agg.on_trade(_trade(1500, 4, 50.0)) == []  # late: dropped, counted.
    assert agg.stats()["late_dropped"] == 1


def test_empty_windows_are_missing_and_ids_flag_gaps():
    agg = BarAggregator("BTCUSDT", lateness_ms=0)
    agg.on_trade(_trade(0, 1))
    out = agg.on_trade(_trade(3100, 2))  # IDs continuous; seconds 1-2 had no trades.
    assert isinstance(out[0], Bar1s)
    assert isinstance(out[1], BarMissing) and out[1].window_start_ms == 1000
    assert isinstance(out[2], BarMissing) and out[2].window_start_ms == 2000
    assert out[1].symbol == "BTCUSDT" and out[1].gap_before is False
    assert to_s1_bar(out[1]) is None
    assert agg.stats()["empty_windows"] == 2
    agg2 = BarAggregator("BTCUSDT", lateness_ms=0)
    agg2.on_trade(_trade(0, 1))
    out2 = agg2.on_trade(_trade(1100, 5))  # ID jump 1 -> 5.
    assert agg2.stats()["gap_jumps"] == 1
    assert isinstance(out2[-1], Bar1s) and out2[-1].gap_before is True


def test_spread_attaches_only_from_observed_bbo():
    agg = BarAggregator("BTCUSDT", lateness_ms=0)
    agg.on_bbo(99.0, 101.0, 500)
    agg.on_trade(_trade(100, 1))
    (bar,) = agg.on_trade(_trade(1200, 2))
    assert isinstance(bar, Bar1s) and bar.spread_bps is not None
    assert abs(bar.spread_bps - 200.0) < 1.0  # (2/100)*1e4.
    assert bar.buy_frac == 1.0  # buyer-is-maker False on both trades.
    assert to_s1_bar(bar) is not None
    assert to_s1_bar(bar).source == "observed-public"
    assert to_s1_bar(None) is None


def test_bar_without_spread_converts_to_missing():
    agg = BarAggregator("BTCUSDT", lateness_ms=0)
    agg.on_trade(_trade(100, 1))
    (bar,) = agg.on_trade(_trade(1200, 2))
    assert isinstance(bar, Bar1s) and bar.spread_bps is None
    assert to_s1_bar(bar) is None  # spread never invented or carried forward.


def test_gap_bar_converts_to_none_then_recovers():
    agg = BarAggregator("BTCUSDT", lateness_ms=0)
    agg.on_bbo(99.0, 101.0, 0)  # spread observed: only the gap fails the bar.
    agg.on_trade(_trade(0, 1))
    out = agg.on_trade(_trade(1100, 3))  # ID jump 1 -> 3.
    (bar,) = [b for b in out if isinstance(b, Bar1s)]
    assert bar.gap_before is True
    assert to_s1_bar(bar) is None  # hidden trades possible: fail safe, not clean.
    good = 0
    for sec in range(2, 34):  # window [1000] also flagged; then 31 fresh.
        agg.on_bbo(99.0, 101.0, sec * 1000)  # spread observed in each window.
        for closed in agg.on_trade(_trade(sec * 1000 + 100, sec + 2)):
            if not isinstance(closed, Bar1s):
                continue
            if closed.window_start_ms == 1000:
                assert closed.gap_before is True  # jump span covers both sides.
                assert to_s1_bar(closed) is None
                continue
            assert closed.gap_before is False
            assert to_s1_bar(closed) is not None
            good += 1
    assert good == 31


def test_flush_drains_and_duplicate_ids_drop():
    agg = BarAggregator("BTCUSDT", lateness_ms=10_000)
    agg.on_trade(_trade(100, 1))
    assert agg.on_trade(_trade(100, 1)) == []  # duplicate ID.
    assert agg.stats()["late_dropped"] == 1
    agg.on_trade(_trade(2100, 2))
    out = agg.flush()  # drains through max observed time: bar + trailing empty.
    assert len(out) == 2 and isinstance(out[0], Bar1s) and isinstance(out[1], BarMissing)
    assert (out[1].symbol, out[1].window_start_ms) == ("BTCUSDT", 1000)


def test_bar_dict_round_trip():
    import json

    bar = Bar1s("BTCUSDT", 1000, 1.0, 2.0, 0.5, 1.5, 3.0, 2, 1.0, 7, 8, 2.5, False)
    raw = json.loads(json.dumps(bar_to_dict(bar)))  # strict-JSON safe.
    assert bar_from_dict(raw) == bar
    missing = BarMissing("BTCUSDT", 2000, True)
    assert bar_from_dict(json.loads(json.dumps(bar_to_dict(missing)))) == missing


def test_aggregator_dict_round_trip_preserves_watermark_and_seq():
    import json

    agg = BarAggregator("BTCUSDT", lateness_ms=500)
    agg.on_trade(_trade(100, 1, 100.0))
    agg.on_trade(_trade(700, 2, 101.0))
    agg.on_bbo(100.9, 101.1, 700)
    raw = json.loads(json.dumps(agg.to_dict()))
    restored = BarAggregator.from_dict(raw)
    assert restored.to_dict() == raw
    assert restored.stats() == agg.stats()
    # Identical continuation: same outputs for the same next trades.
    nxt = [_trade(1600, 3, 102.0), _trade(2600, 4, 103.0)]
    assert [restored.on_trade(t) for t in nxt] == [agg.on_trade(t) for t in nxt]
