"""Synthetic benchmark tests (Worker 1, Q-007)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.research.synth_benchmark import (
    BASE_PRICE,
    BENCHMARK_ID,
    DAY_TABLE,
    INPUT_CLASS,
    N_DAYS,
    SYMBOL,
    SynthBenchmark,
    day_closes,
)


def test_day_table_covers_30_days_all_scenarios_per_split():
    assert N_DAYS == 30 and len(DAY_TABLE) == 30
    dev = {DAY_TABLE[d][0] for d in range(1, 16)}
    val = {DAY_TABLE[d][0] for d in range(16, 23)}
    test = {DAY_TABLE[d][0] for d in range(23, 31)}
    for split in (dev, val, test):
        assert {"impulse", "pullback", "range", "reclaim", "flat",
                "choppy"} <= split


def test_day_closes_deterministic_and_shaped():
    assert day_closes(1) == day_closes(1)
    assert len(day_closes(1)) == 600
    impulse = day_closes(1)  # impulse-long: +30bps ramp at 150..159
    assert impulse[149] == BASE_PRICE
    assert abs((impulse[159] - impulse[149]) / BASE_PRICE * 1e4 - 30.0) < 1e-9
    assert abs(impulse[599] / BASE_PRICE - 1.0030) < 1e-12
    flat = day_closes(5)
    assert all(px == BASE_PRICE for px in flat)


def test_events_schema_and_channels():
    bench = SynthBenchmark()
    evs = list(bench.events(SYMBOL, 1))
    assert len(evs) == 1200  # 600 trade + 600 BBO
    trades = [e for e in evs if e["channel"] == "aggTrade"]
    tickers = [e for e in evs if e["channel"] == "bookTicker"]
    assert len(trades) == 600 and len(tickers) == 600
    assert all(e["input_class"] == INPUT_CLASS for e in evs)
    p = tickers[0]["payload"]
    assert p["bid_qty"] > 0 and p["ask_qty"] > 0 and p["ask"] > p["bid"]
    q = trades[0]["payload"]
    assert {"agg_id", "price", "qty", "buyer_is_maker"} <= set(q)
    ts = [e["exchange_ts_ms"] for e in evs]
    assert ts == sorted(ts)
    agg_ids = [e["payload"]["agg_id"] for e in trades]
    assert agg_ids == sorted(agg_ids) and len(set(agg_ids)) == 600


def test_noquotes_dataset_has_trades_only():
    bench = SynthBenchmark(dataset_id="synth_noquotes")
    evs = list(bench.events(SYMBOL, 1))
    assert len(evs) == 600
    assert all(e["channel"] == "aggTrade" for e in evs)


def test_coverage_and_manifest_sha():
    bench = SynthBenchmark()
    cov = bench.coverage()
    assert cov["benchmark_id"] == BENCHMARK_ID
    assert len(cov["days"]) == 30
    assert all(d["quotes_observed"] for d in cov["days"])
    noq = SynthBenchmark(dataset_id="synth_noquotes")
    assert not any(d["quotes_observed"] for d in noq.coverage()["days"])
    assert bench.manifest_sha() == bench.manifest_sha()
    assert bench.manifest_sha() != noq.manifest_sha()


def test_bad_dataset_symbol_day_rejected():
    bench = SynthBenchmark()
    for fn in (lambda: SynthBenchmark(dataset_id="nope"),
               lambda: list(bench.events("ETHUSDT", 1)),
               lambda: list(bench.events(SYMBOL, 31))):
        try:
            fn()
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError")
