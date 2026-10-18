"""E4: slow backtester — differential, realism, sweep, leak detectors."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pandas")


def _panel(symbols=("A", "B", "C"), days=60, seed=7, drift=0.0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-01", periods=days, freq="D", tz="UTC")
    daily = {}
    for s in symbols:
        rets = rng.normal(drift, 0.02, days)
        closes = 100.0 * np.exp(np.cumsum(rets))
        closes = np.concatenate([[100.0], closes])[:days]
        daily[s] = pd.DataFrame({"open_time": idx, "open": closes,
                                 "high": closes * 1.01, "low": closes * 0.99,
                                 "close": closes,
                                 "quote_volume": [1e7] * days})
    return daily, idx


def _funding(symbols, idx, rate=0.0):
    out = {}
    for s in symbols:
        calcs = []
        for d in idx:
            for h in (0, 8, 16):
                calcs.append(d + pd.Timedelta(hours=h))
        out[s] = pd.DataFrame({"calc_time": pd.DatetimeIndex(calcs),
                               "last_funding_rate": rate})
    return out


def test_differential_vectorized_vs_event():
    from cryptobot.research.slow_backtest import (
        CostModel, SimConfig, simulate_event, simulate_vectorized)

    daily, idx = _panel()
    funding = _funding(daily, idx, rate=0.0001)
    rng = np.random.default_rng(11)
    targets = {}
    for d in idx[5::7]:
        targets[d] = {s: float(rng.uniform(-0.3, 0.3)) for s in daily}
    costs = CostModel()
    cfg = SimConfig(initial_equity=10000.0)
    a = simulate_vectorized(targets, daily, funding, costs=costs, config=cfg)
    b = simulate_event(targets, daily, funding, costs=costs, config=cfg)
    assert a.final_equity == pytest.approx(b.final_equity, rel=1e-9)
    assert a.total_costs == pytest.approx(b.total_costs, rel=1e-9)
    assert a.turnover_oneway == pytest.approx(b.turnover_oneway, rel=1e-9)
    assert len(a.equity) == len(b.equity) == len(idx)
    assert (a.equity.values == pytest.approx(b.equity.values, rel=1e-9))


def test_hand_computed_costs_and_funding():
    from cryptobot.research.slow_backtest import (
        CostModel, SimConfig, simulate_vectorized)

    daily, idx = _panel(symbols=("A",), days=12, seed=1, drift=0.0)
    daily["A"]["quote_volume"] = 1e12  # impact -> 0, slip floor binds
    # Pin prices: 100 until the last-day open at 110.
    for col in ("open", "high", "low", "close"):
        daily["A"][col] = 100.0
    for col in ("open", "high", "low", "close"):
        daily["A"].loc[11:, col] = 110.0
    funding = _funding(("A",), idx, rate=0.0001)  # +1bp/8h
    d0, d1 = idx[10], idx[11]
    targets = {d0: {"A": 0.1}, d1: {"A": 0.0}}  # $1000 in, flat out
    r = simulate_vectorized(targets, daily, funding, costs=CostModel(),
                            config=SimConfig(initial_equity=10000.0))
    # Buy 1000 @100 (10 units, cost 9.5bps of 1000 = 0.95);
    # sell 10 @110 = 1100 (cost 9.5bps = 1.045); gross +100.
    # Funding: 2 settlements x 1000 x 1bp + 1 x 1100 x 1bp = 0.31.
    assert r.final_equity == pytest.approx(10000 + 100 - 0.95 - 1.045 - 0.31,
                                           abs=0.05)
    assert r.costs["funding"] == pytest.approx(0.31, abs=0.02)


def test_min_notional_drops_dust_loudly():
    from cryptobot.research.slow_backtest import (
        SimConfig, simulate_vectorized)

    daily, idx = _panel(symbols=("A",), days=10)
    r = simulate_vectorized({idx[0]: {"A": 0.003}}, daily,
                            _funding(("A",), idx),
                            config=SimConfig(initial_equity=1000.0))
    assert r.drops == 1
    assert r.final_equity == pytest.approx(1000.0)


def test_step_flooring_and_leverage_cap():
    from cryptobot.research.slow_backtest import (
        SimConfig, simulate_vectorized)

    daily, idx = _panel(symbols=("A", "B"), days=10)
    daily["A"]["close"] = 60000.0
    daily["A"]["open"] = 60000.0
    r = simulate_vectorized({idx[0]: {"A": 2.0, "B": 2.0}}, daily,
                            _funding(("A", "B"), idx),
                            config=SimConfig(initial_equity=10000.0))
    assert r.gross_breaches >= 1  # 4x desired -> rescaled to 2x at trade
    day0_gross = (abs(r.final_positions.get("A", 0.0)) * 60000.0
                  + abs(r.final_positions.get("B", 0.0)) * 100.0) / 10000.0
    assert day0_gross == pytest.approx(2.0, abs=0.02)
    assert r.final_positions["B"] == pytest.approx(100.0)  # no float dust


def test_delisting_exits_at_last_close():
    from cryptobot.research.slow_backtest import (
        SimConfig, simulate_vectorized)

    daily, idx = _panel(symbols=("A", "B"), days=40)
    daily["B"] = daily["B"].iloc[:30].reset_index(drop=True)  # delists day 30
    targets = {idx[0]: {"B": 0.5}}
    r = simulate_vectorized(targets, daily, _funding(("A", "B"), idx),
                            config=SimConfig(initial_equity=10000.0))
    assert "delisted-exit:B" in r.flags
    assert r.final_positions == {}


def test_liq_proxy_force_closes():
    from cryptobot.research.slow_backtest import (
        SimConfig, simulate_vectorized)

    daily, idx = _panel(symbols=("A",), days=10)
    daily["A"].loc[:, "close"] = 100.0
    daily["A"].loc[5:, "close"] = 55.0  # -45% crash vs entry
    daily["A"].loc[5:, "open"] = 55.0
    r = simulate_vectorized({idx[0]: {"A": 0.5}}, daily,
                            _funding(("A",), idx),
                            config=SimConfig(initial_equity=10000.0))
    assert "liquidation:A" in r.flags
    assert r.final_positions == {}


def test_capital_sweep_reports_feasibility():
    from cryptobot.research.slow_backtest import capital_sweep

    daily, idx = _panel(symbols=("A", "B", "C"), days=30)
    targets = {d: {"A": 0.1, "B": -0.1, "C": 0.05} for d in idx[::7]}
    rep = capital_sweep(targets, daily, _funding(daily, idx),
                        equities=(120.0, 1000.0, 10000.0))
    assert set(rep) == {120.0, 1000.0, 10000.0}
    assert rep[120.0]["drops"] >= rep[10000.0]["drops"]
    assert "feasible" in rep[120.0]


def test_shift_earlier_improves_later_degrades():
    from cryptobot.research.slow_backtest import (
        SimConfig, shift_targets, simulate_vectorized)

    idx = pd.date_range("2023-01-01", periods=60, freq="D", tz="UTC")
    closes = 100.0 * (1.002 ** np.arange(60))  # pure drift, zero noise
    daily = {"A": pd.DataFrame({"open_time": idx, "open": closes,
                                "high": closes, "low": closes, "close": closes,
                                "quote_volume": [1e7] * 60})}
    targets = {idx[28]: {"A": 0.5}}  # single mid-panel entry, held out
    cfg = SimConfig(initial_equity=10000.0)
    fund = _funding(("A",), idx, rate=0.0)
    base = simulate_vectorized(targets, daily, fund, config=cfg).final_equity
    early = simulate_vectorized(shift_targets(targets, idx, -1), daily, fund,
                                config=cfg).final_equity
    late = simulate_vectorized(shift_targets(targets, idx, 1), daily, fund,
                               config=cfg).final_equity
    assert early > base > late  # pure drift makes timing strictly monotone


def test_label_shuffle_kills_timing_edge():
    from cryptobot.research.slow_backtest import (
        SimConfig, shuffle_labels, simulate_vectorized)

    # Planted regime: days 100-130 drift +2%/day, else flat + noise.
    rng = np.random.default_rng(5)
    idx = pd.date_range("2023-01-01", periods=200, freq="D", tz="UTC")
    rets = rng.normal(0.0, 0.01, 200)
    rets[100:130] += 0.02
    closes = 100.0 * np.exp(np.cumsum(rets))
    daily = {"A": pd.DataFrame({"open_time": idx, "open": closes,
                                "high": closes, "low": closes, "close": closes,
                                "quote_volume": [1e7] * 200})}
    # "Discovered" timing: long only across the hot window (fitted!).
    targets = {idx[100]: {"A": 0.5}, idx[130]: {"A": 0.0}}
    cfg = SimConfig(initial_equity=10000.0)
    fund = _funding(("A",), idx, rate=0.0)
    s_base = simulate_vectorized(targets, daily, fund, config=cfg).sharpe
    assert s_base > 3.0  # fitted window looks amazing
    shuf = shuffle_labels(daily, seed=99)
    s_shuf = simulate_vectorized(targets, shuf, fund, config=cfg).sharpe
    # Same window, shuffled labels: timing edge collapses (residual is
    # scattered drift, not timing).
    assert abs(s_shuf) < 0.4 * s_base


def test_sharpe3_autoflag():
    from cryptobot.research.slow_backtest import (
        SimConfig, simulate_vectorized)

    daily, idx = _panel(symbols=("A",), days=60, seed=9, drift=0.05)
    targets = {d: {"A": 1.0} for d in idx}
    r = simulate_vectorized(targets, daily, _funding(("A",), idx),
                            config=SimConfig(initial_equity=10000.0))
    assert r.sharpe > 3.0
    assert "leak-investigate" in r.flags
