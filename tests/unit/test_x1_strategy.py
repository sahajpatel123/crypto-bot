"""X1 leader-laggard tests (Worker 4, DEEP-W4-D4 freeze).

All inputs synthetic and labelled; no round data is touched (the
freeze precedes any outcome). Covers trigger math, gates,
causality, dual alignment, Intent construction, the runtime
adapter, the Session dual handoff, the registry/TOML allowlist
pins, and the three frozen tools on synthetic inputs.
"""
import json
import math
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.coordination import DataQuality, Side  # noqa: E402
from cryptobot.strategies import contract as C  # noqa: E402
from cryptobot.strategies.runtime import (  # noqa: E402
    ADAPTERS,
    MarketView,
    get_adapter,
)
from cryptobot.strategies.s1 import Bar  # noqa: E402
from cryptobot.strategies.x1 import (  # noqa: E402
    DUAL_LAGGARD,
    DUAL_REF_SYMBOL,
    align_leader,
    evaluate_bar,
    evaluate_side,
)

REPO = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
BETA = 1.2


def _bars(closes, spread_bps=1.0, buy_frac=0.5, t0=T0):
    out = []
    for i, close in enumerate(closes):
        ts = t0 + timedelta(seconds=i)
        out.append(Bar(ts_utc=ts, open=close, high=close * 1.0001,
                       low=close * 0.9999, close=close, volume=10.0,
                       trades=5, buy_frac=buy_frac,
                       spread_bps=spread_bps, source="synthetic"))
    return out


def _ramp(start, end, n):
    return [start + (end - start) * i / (n - 1) for i in range(n)]


def _pair(btc_move_bps=40.0, eth_move_bps=2.0, n=61, **kw):
    """Aligned BTC/ETH pair with exact 60-bar moves at index 60."""
    btc = _ramp(100.0, 100.0 * (1 + btc_move_bps / 1e4), n)
    eth = _ramp(50.0, 50.0 * (1 + eth_move_bps / 1e4), n)
    return _bars(btc, **kw), _bars(eth, **kw)


def test_long_fire_math_exact():
    btc, eth = _pair(40.0, 2.0)
    (long_d, short_d) = evaluate_bar(eth, 60, "X1", DUAL_LAGGARD,
                                     ref_bars=btc, beta=BETA)
    assert long_d.intent is not None and long_d.record is not None
    assert short_d.intent is None
    intent = long_d.intent
    assert intent.strategy == "X1" and intent.side == Side.LONG
    assert intent.instrument == "ETHUSDT"
    eth_t = eth[60].close
    assert intent.entry_low == pytest.approx(eth_t)
    assert intent.entry_high == pytest.approx(eth_t * 1.0002)
    assert intent.entry_expiry_utc == eth[60].ts_utc + timedelta(seconds=10)
    assert intent.holding_limit_s == 120
    # Stop = max(BTC-retrace leg, gap-widen leg), both adverse.
    stop_btc = eth_t * (1 + BETA * (-0.5 * 40.0) / 1e4)
    stop_gap = eth_t * (1 - 10.0 / 1e4)
    assert intent.invalidation_price == pytest.approx(max(stop_btc, stop_gap))
    assert intent.invalidation_price < intent.entry_low
    # Target = 50% gap closure: G = 38bps -> +19bps.
    assert intent.exit_rule.startswith("v1|stop=")
    log = long_d.evaluation
    assert log.regime == "leader-lag-long"
    assert log.trigger == "btc60>=35&gap>=35"
    assert log.reason == "fired"
    assert intent.forecast_cost == C.X1_FORECAST_COST
    assert intent.data_quality == DataQuality.CLEAN
    assert intent.data_quality_reason == "no-gaps-N=60x2"
    assert intent.evidence_ref == long_d.record.record_id
    assert intent.evidence_ref.startswith("X1:0.1.0:ETHUSDT:LONG:")


def test_short_fire_mirrors():
    btc, eth = _pair(-45.0, -3.0)
    (long_d, short_d) = evaluate_bar(eth, 60, "X1", DUAL_LAGGARD,
                                     ref_bars=btc, beta=BETA)
    assert long_d.intent is None
    assert short_d.intent is not None
    intent = short_d.intent
    assert intent.side == Side.SHORT
    assert intent.entry_high == pytest.approx(eth[60].close)
    assert intent.invalidation_price > intent.entry_high
    assert short_d.evaluation.regime == "leader-lag-short"
    assert short_d.evaluation.trigger == "btc60<=-35&gap<=-35"


def test_gates_reject_in_order():
    btc, eth = _pair(40.0, 2.0)  # fires at baseline.
    # Weak leader move.
    weak_btc, _ = _pair(10.0, 2.0)
    d = evaluate_side(eth, 60, Side.LONG, "X1", DUAL_LAGGARD,
                      ref_bars=weak_btc, beta=BETA)
    assert d.intent is None and d.evaluation.reason == "move-gate"
    # Gap too small (ETH matched BTC).
    _, matched_eth = _pair(40.0, 38.0)
    d = evaluate_side(matched_eth, 60, Side.LONG, "X1", DUAL_LAGGARD,
                      ref_bars=btc, beta=BETA)
    assert d.intent is None and d.evaluation.reason == "gapmove-gate"
    # Wrong-sign gap (ETH overran BTC).
    _, over_eth = _pair(40.0, 60.0)
    d = evaluate_side(over_eth, 60, Side.LONG, "X1", DUAL_LAGGARD,
                      ref_bars=btc, beta=BETA)
    assert d.intent is None and d.evaluation.reason == "gapmove-gate"
    # Spread gate.
    _, wide_eth = _pair(40.0, 2.0, spread_bps=5.0)
    d = evaluate_side(wide_eth, 60, Side.LONG, "X1", DUAL_LAGGARD,
                      ref_bars=btc, beta=BETA)
    assert d.intent is None and d.evaluation.reason == "spread-gate"
    # Flow gate on X1-F (bearish flow blocks the long).
    _, bear_eth = _pair(40.0, 2.0, buy_frac=0.2)
    d = evaluate_side(bear_eth, 60, Side.LONG, "X1-F", DUAL_LAGGARD,
                      ref_bars=btc, beta=BETA)
    assert d.intent is None and d.evaluation.reason == "confirm-gate"
    d = evaluate_side(bear_eth, 60, Side.LONG, "X1", DUAL_LAGGARD,
                      ref_bars=btc, beta=BETA)
    assert d.intent is not None  # base arm has no flow gate.


def test_strict_and_timed_variants():
    btc, eth = _pair(40.0, 2.0)
    d = evaluate_side(eth, 60, Side.LONG, "X1-S", DUAL_LAGGARD,
                      ref_bars=btc, beta=BETA)
    assert d.intent is None and d.evaluation.reason == "move-gate"
    hot_btc, hot_eth = _pair(60.0, 5.0)
    d = evaluate_side(hot_eth, 60, Side.LONG, "X1-S", DUAL_LAGGARD,
                      ref_bars=hot_btc, beta=BETA)
    assert d.intent is not None
    assert d.evaluation.trigger == "btc60>=50&gap>=50"
    d = evaluate_side(eth, 60, Side.LONG, "X1-T", DUAL_LAGGARD,
                      ref_bars=btc, beta=BETA)
    assert d.intent is not None
    assert d.intent.holding_limit_s == 60
    assert d.intent.exit_rule.endswith("|id=X1-T:stop+target+time")
    d = evaluate_side(eth, 60, Side.LONG, "X1-F", DUAL_LAGGARD,
                      ref_bars=btc, beta=BETA)
    assert d.intent is None  # buy_frac 0.5 < 0.58.
    _, bull_eth = _pair(40.0, 2.0, buy_frac=0.7)
    d = evaluate_side(bull_eth, 60, Side.LONG, "X1-F", DUAL_LAGGARD,
                      ref_bars=btc, beta=BETA)
    assert d.intent is not None
    assert d.evaluation.trigger == "btc60>=35&gap>=35+flow(10)"


def test_not_laggard_and_beta_gates():
    btc, eth = _pair(40.0, 2.0)
    d = evaluate_side(btc, 60, Side.LONG, "X1", DUAL_REF_SYMBOL,
                      ref_bars=btc, beta=BETA)
    assert d.intent is None and d.evaluation.reason == "not-laggard"
    for bad in (None, 0.0, -1.5, float("nan")):
        d = evaluate_side(eth, 60, Side.LONG, "X1", DUAL_LAGGARD,
                          ref_bars=btc, beta=bad)
        assert d.intent is None, bad
        assert d.evaluation.reason == "beta-unfrozen", bad
        assert "beta=unfrozen" in d.evaluation.rejects


def test_leader_alignment_exact_ts_only():
    btc, eth = _pair(40.0, 2.0)
    # Stale leader (plenty of history, latest bar behind evidence).
    stale = _bars(_ramp(100.0, 104.0, 70),
                  t0=T0 - timedelta(seconds=10))
    assert align_leader(stale, eth[60].ts_utc) == 69
    d = evaluate_side(eth, 60, Side.LONG, "X1", DUAL_LAGGARD,
                      ref_bars=stale, beta=BETA)
    assert d.intent is None
    assert d.evaluation.reason == "leader-missing-bar"
    # Leader bars AHEAD of evidence are never used (causality).
    future = _bars(_ramp(200.0, 210.0, 5),
                   t0=T0 + timedelta(seconds=61))
    mixed = btc + future
    assert align_leader(mixed, eth[60].ts_utc) == 60
    d = evaluate_side(eth, 60, Side.LONG, "X1", DUAL_LAGGARD,
                      ref_bars=mixed, beta=BETA)
    assert d.intent is not None  # identical to the no-future case.
    # No leader at all.
    d = evaluate_side(eth, 60, Side.LONG, "X1", DUAL_LAGGARD,
                      ref_bars=None, beta=BETA)
    assert d.intent is None
    assert d.evaluation.reason == "insufficient-history"


def test_causality_future_bars_ignored():
    btc, eth = _pair(40.0, 2.0)
    eth_long = eth + _bars([1000.0, 0.01, 500.0],
                           t0=T0 + timedelta(seconds=61))
    btc_long = btc + _bars([1e6, 1.0, 5e5],
                           t0=T0 + timedelta(seconds=61))
    d0 = evaluate_side(eth, 60, Side.LONG, "X1", DUAL_LAGGARD,
                       ref_bars=btc, beta=BETA)
    d1 = evaluate_side(eth_long, 60, Side.LONG, "X1", DUAL_LAGGARD,
                       ref_bars=btc_long, beta=BETA)
    assert (d0.intent is not None) == (d1.intent is not None)
    assert d0.evaluation.reason == d1.evaluation.reason
    assert d0.evaluation.rejects == d1.evaluation.rejects
    if d0.intent is not None:
        assert d1.intent is not None
        assert d0.intent.entry_low == d1.intent.entry_low
        assert d0.intent.exit_rule == d1.intent.exit_rule


def test_gap_and_halt_either_side():
    btc, eth = _pair(40.0, 2.0)
    gapped = list(eth)
    gapped[30] = None
    d = evaluate_side(gapped, 60, Side.LONG, "X1", DUAL_LAGGARD,
                      ref_bars=btc, beta=BETA)
    assert d.intent is None and d.evaluation.reason == "gap-1"
    assert d.evaluation.data_quality == DataQuality.DEGRADED
    gapped_ref = list(btc)
    gapped_ref[45] = None
    d = evaluate_side(eth, 60, Side.LONG, "X1", DUAL_LAGGARD,
                      ref_bars=gapped_ref, beta=BETA)
    assert d.intent is None and d.evaluation.reason == "gap-1"
    # >5 consecutive on EITHER side halts.
    halted = list(eth)
    for i in range(10, 17):
        halted[i] = None
    d = evaluate_side(halted, 60, Side.LONG, "X1", DUAL_LAGGARD,
                      ref_bars=btc, beta=BETA)
    assert d.evaluation.data_quality == DataQuality.HALT
    halted_ref = list(btc)
    for i in range(20, 27):
        halted_ref[i] = None
    d = evaluate_side(eth, 60, Side.LONG, "X1", DUAL_LAGGARD,
                      ref_bars=halted_ref, beta=BETA)
    assert d.evaluation.data_quality == DataQuality.HALT
    # Timestamp disorder halts.
    broken = list(eth)
    moved = Bar(ts_utc=broken[40].ts_utc + timedelta(seconds=5),
                open=50.0, high=50.1, low=49.9, close=50.0, volume=1.0,
                trades=1, buy_frac=0.5, spread_bps=1.0,
                source="synthetic")
    broken[40] = moved
    d = evaluate_side(broken, 60, Side.LONG, "X1", DUAL_LAGGARD,
                      ref_bars=btc, beta=BETA)
    assert d.intent is None and d.evaluation.reason == "ts-disorder"


def test_adapter_paths():
    adapter = get_adapter("X1")
    assert adapter.strategy_id == "X1"
    assert "X1" in [a.strategy_id for a in ADAPTERS]
    btc, eth = _pair(40.0, 2.0)
    now = eth[-1].ts_utc
    view = MarketView(DUAL_LAGGARD, tuple(eth), now, None, None,
                      DataQuality.CLEAN, "",
                      ref_bars=tuple(btc), ref_instrument=DUAL_REF_SYMBOL,
                      ref_beta=BETA)
    out = adapter.evaluate(view)
    assert out.intent is not None and out.exit_policy is not None
    assert out.intent.strategy == "X1"
    # No reference leg: recorded no-fire, never an error.
    bare = MarketView(DUAL_LAGGARD, tuple(eth), now, None, None,
                      DataQuality.CLEAN)
    out = adapter.evaluate(bare)
    assert out.intent is None
    assert out.reject_reason == "history:fail|history:fail"
    # Leader symbol: not-laggard attribution on both sides.
    btc_view = MarketView(DUAL_REF_SYMBOL, tuple(btc), now, None, None,
                          DataQuality.CLEAN, "",
                          ref_bars=tuple(btc),
                          ref_instrument=DUAL_REF_SYMBOL, ref_beta=BETA)
    out = adapter.evaluate(btc_view)
    assert out.intent is None
    assert out.reject_reason == "symbol:not-laggard|symbol:not-laggard"


def test_session_dual_handoff(tmp_path):
    import dataclasses
    from collections import deque

    from cryptobot.app.config import load_config
    from cryptobot.app.session import Session, _SymbolFeed
    from cryptobot.app.store import RunStore

    cfg = load_config(REPO / "configs" / "paper.toml")
    cfg = dataclasses.replace(cfg, strategies_enabled=("X1",),
                              x1_beta=BETA,
                              storage_dir=str(tmp_path / "runs"))
    store = RunStore(tmp_path / "runs" / "s.db")
    session = Session(cfg, store, tmp_path / "runs" / "x1", "x1",
                      engine=None)
    btc, eth = _pair(40.0, 2.0)
    session.clock.set_ms(int(eth[-1].ts_utc.timestamp() * 1000))
    for symbol, bars in ((DUAL_REF_SYMBOL, btc), (DUAL_LAGGARD, eth)):
        feed = _SymbolFeed(symbol, 130)
        feed.bars = deque(bars, maxlen=135)
        feed.missing_cause = deque([None] * len(bars), maxlen=135)
        session._feeds[symbol] = feed
    adapters, modules = session._strategy_adapters()
    assert set(adapters) == {"X1"} and set(modules) == {"X1"}
    cands = session._evaluate_symbol(DUAL_LAGGARD, adapters, modules)
    intents = [c for c in cands if c.intent is not None]
    assert len(intents) == 1  # long fires, short no-fires.
    assert intents[0].intent.strategy == "X1"
    assert intents[0].intent.instrument == "ETHUSDT"
    cands = session._evaluate_symbol(DUAL_REF_SYMBOL, adapters, modules)
    assert all(c.intent is None for c in cands)
    assert any("not-laggard" in c.reject_reason for c in cands)
    store.close()


def test_allowlist_registry_pins():
    from cryptobot.research.allowlist import (
        config_arms,
        resolve_config_arms,
        verify,
    )

    assert resolve_config_arms(["X1"], "base") == ["X1"]
    assert resolve_config_arms(["X1"], "all") == ["X1", "X1-S", "X1-T",
                                                  "X1-F"]
    registry = REPO / "trials" / "x1-round-01.json"
    params = REPO / "trials" / "x1-round-01.params.json"
    assert config_arms(json.loads(registry.read_text()),
                       "X1-R1-F") == ["X1-F"]
    pairs = [("x1-r1", "X1-R1"), ("x1-r1-s", "X1-R1-S"),
             ("x1-r1-t", "X1-R1-T"), ("x1-r1-f", "X1-R1-F"),
             ("x1-r1-s1", "X1-R1-S1"), ("x1-r1-cash", "X1-R1-CASH")]
    for name, config_id in pairs:
        report = verify(REPO / "configs" / f"{name}.toml", registry,
                        params, only_config=config_id)
        assert report["ok"] is True, (name, report)
    frozen = json.loads(params.read_text())
    assert set(frozen["families"]) == {"X1", "S1"}
    assert frozen["families"]["X1"]["params"]["move_n"] == 60


def _load_tool(name):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        name, REPO / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_beta_tool_pure_functions():
    beta_tool = _load_tool("x1_beta")
    # Synthetic trend pair with known slope ~1.5 (unit-free check).
    xs = [i * 0.001 for i in range(1200)]
    ys = [1.5 * x + 0.0001 for x in xs]
    fit = beta_tool.ols_beta(xs, ys)
    assert fit["n"] == 1200
    assert fit["beta"] == pytest.approx(1.5)
    with pytest.raises(ValueError, match="paired returns"):
        beta_tool.ols_beta([0.1] * 10, [0.2] * 10)
    with pytest.raises(ValueError, match="zero BTC variance"):
        beta_tool.ols_beta([0.0] * 1200, [0.1] * 1200)
    # Close building: last price per second, heartbeats skipped.
    events = [None,
              {"channel": "aggTrade", "exchange_ts_ms": 5_000,
               "payload": {"price": 10.0}},
              {"channel": "aggTrade", "exchange_ts_ms": 5_500,
               "payload": {"price": 11.0}},
              {"channel": "markPrice", "exchange_ts_ms": 5_700,
               "payload": {"mark": 99.0}},
              {"channel": "aggTrade", "exchange_ts_ms": 65_000,
               "payload": {"price": 12.0}}]
    closes = beta_tool.closes_from_events(events)
    assert closes == {5: 11.0, 65: 12.0}
    xs, ys, paired = beta_tool.paired_returns(
        {0: 100.0, 60: 101.0}, {0: 50.0, 60: 50.5})
    assert paired == [60]
    assert xs[0] == pytest.approx(math.log(1.01))
    assert ys[0] == pytest.approx(math.log(1.01))


def test_beta_tool_ist_windowing_matches_harness(tmp_path):

    from cryptobot.research.backtest import _ist_window_ms

    beta_tool = _load_tool("x1_beta")
    lo, hi = _ist_window_ms("2026-09-12")

    def trade(ts_ms, price):
        return {"channel": "aggTrade", "exchange_ts_ms": ts_ms,
                "payload": {"price": price}}

    # UTC-day streams straddling the IST window edges (IST 09-12
    # spans UTC 09-11/09-12).
    utc11 = [trade(lo - 1000, 1.0), trade(lo, 100.0),
             trade(lo + 60_000, 101.0)]
    utc12 = [trade(hi - 60_000, 102.0), trade(hi - 1000, 103.0),
             trade(hi, 999.0)]

    class StubDataset:
        def manifest_sha(self):
            return "stub"

        def events(self, symbol, day):
            if day == "2026-09-11":
                return iter(utc11)
            if day == "2026-09-12":
                return iter(utc12)
            return iter([])

    got = list(beta_tool.ist_day_events(StubDataset(), "BTCUSDT",
                                       "2026-09-12"))
    # Boundary-exact: lo included, hi excluded, outside dropped.
    assert [e["exchange_ts_ms"] for e in got] == [
        lo, lo + 60_000, hi - 60_000, hi - 1000]


def _comparison_cell(tmp_path, name, armset, split, opening, closing,
                     fills=(), n_fills=None):
    run_dir = tmp_path / name
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.json").write_text(json.dumps({
        "opening_equity": opening, "closing_equity": closing,
        "net_return_pct": (closing / opening - 1) * 100,
        "paid_costs": 1.0, "funding_net": 0.0, "realised": closing - opening,
        "intents_admitted": 3, "reject_counts": {"strategy:move:fail": 5},
        "fee_schedule": {"taker_bps": 5.0}, "config_fingerprint": "fp",
    }), encoding="utf-8")
    (run_dir / "fills.jsonl").write_text(
        "".join(json.dumps(f) + "\n" for f in fills), encoding="utf-8")
    comp_path = tmp_path / f"{name}.comparison.json"
    comp_path.write_text(json.dumps({
        "dataset_manifest_sha": "abc123", "splits": [split],
        "cells": {f"{armset}|{split}": {
            "closing_equity": closing, "run_dir": str(run_dir)}},
    }), encoding="utf-8")
    return str(comp_path)


def _fill(side, qty):
    return {"execution_id": f"e-{side}-{qty}", "side": side, "qty": qty,
            "price": 100.0, "fee": 0.01}


def test_select_tool_mechanical_rule(tmp_path):
    select_tool = _load_tool("x1_select")
    registry = str(REPO / "trials" / "x1-round-01.json")
    devs = [
        _comparison_cell(tmp_path, "d-x1", "X1", "dev", 120.0, 125.0),
        _comparison_cell(tmp_path, "d-xs", "X1-S", "dev", 120.0, 130.0),
        _comparison_cell(tmp_path, "d-xt", "X1-T", "dev", 120.0, 119.0),
        _comparison_cell(tmp_path, "d-xf", "X1-F", "dev", 120.0, 121.0),
    ]
    vals = [
        _comparison_cell(tmp_path, "v-x1", "X1", "validation", 120.0, 124.0),
        _comparison_cell(tmp_path, "v-xs", "X1-S", "validation", 120.0, 122.0),
        _comparison_cell(tmp_path, "v-xt", "X1-T", "validation", 120.0, 140.0),
        _comparison_cell(tmp_path, "v-xf", "X1-F", "validation", 120.0, 124.0),
    ]
    out = select_tool.select(devs, vals, registry)
    # X1-T has the best val but dev<0 -> disqualified. X1 and X1-F
    # tie on val; X1 wins on dev.
    assert out["qualified"] == ["X1-R1", "X1-R1-F", "X1-R1-S"]
    assert out["winner"] == "X1-R1"
    assert out["verdict"].startswith("ADVANCE")
    # All-negative -> NONE.
    neg_vals = [
        _comparison_cell(tmp_path, f"n{i}", arm, "validation", 120.0, 119.0)
        for i, arm in enumerate(["X1", "X1-S", "X1-T", "X1-F"])]
    out = select_tool.select(devs, neg_vals, registry)
    assert out["winner"] is None
    assert out["verdict"].startswith("NONE")
    # Mixed openings invalidate the comparison.
    mixed = list(devs)
    mixed[0] = _comparison_cell(tmp_path, "d-x1b", "X1", "dev", 100.0, 105.0)
    with pytest.raises(ValueError, match="mixed opening"):
        select_tool.select(mixed, vals, registry)


def test_economics_tool_positions_and_screen(tmp_path):
    econ_tool = _load_tool("x1_economics")
    fills = [_fill("LONG", 1.0), _fill("SHORT", 1.0),
             _fill("LONG", 2.0), _fill("SHORT", 1.0),
             _fill("SHORT", 1.0)]
    assert econ_tool.closed_positions(tmp_path / "missing.jsonl") == {
        "closed_positions": 0, "n_fills": 0, "open_tail_qty": 0.0,
        "max_flat_residual": 0.0}
    dev = _comparison_cell(tmp_path, "e-x1", "X1", "dev", 120.0, 125.0,
                           fills=fills)
    val = _comparison_cell(tmp_path, "e-x1v", "X1", "validation", 120.0,
                           124.0, fills=[_fill("LONG", 1.0)])
    out = econ_tool.assemble(
        [dev, val], str(REPO / "trials" / "x1-round-01.json"), "realistic")
    assert out["tag"] == "realistic"
    assert [c["ledger_net"] for c in out["cells"]] == [5.0, 4.0]
    assert [c["closed_positions"] for c in out["cells"]] == [2, 0]
    assert out["cells"][1]["open_tail_qty"] == pytest.approx(1.0)
    screen = out["screens"]["X1-R1"]
    assert screen["closed_positions"] == 2
    assert screen["split_days"] == 22  # dev 15 + val 7.
    assert screen["positions_per_10d"] == pytest.approx(20 / 22)
    assert screen["screen_100pos_10d"] == "BELOW"
