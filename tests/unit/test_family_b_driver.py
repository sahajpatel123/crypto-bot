"""E6.1 prep: Family B driver — grid expansion, walk-forward, gates."""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pandas")


def test_grid_expansion_counts():
    from cryptobot.research.family_b_driver import expand_grid

    counts = {h: len(expand_grid(h)) for h in
              ("B1", "B2", "B3", "B4", "B5", "B6", "B7")}
    assert counts == {"B1": 12, "B2": 6, "B3": 8, "B4": 9, "B5": 8, "B6": 8,
                      "B7": 8}
    assert sum(counts.values()) == 59


def test_promotion_gates_pass_and_fail():
    from cryptobot.research.family_b_driver import promotion_gates

    rng = np.random.default_rng(7)
    # Profitable best cell + mostly-profitable neighbors, 3 good years.
    good = list(rng.normal(0.004, 0.01, 900))
    cells = {("a", 1): {"oos": good, "turnover": 2.0, "dd": 0.10},
             ("a", 2): {"oos": list(rng.normal(0.003, 0.01, 900)),
                        "turnover": 2.0, "dd": 0.10},
             ("b", 1): {"oos": list(rng.normal(0.002, 0.01, 900)),
                        "turnover": 2.0, "dd": 0.10}}
    years = [{2021: 0.5, 2022: 0.4, 2023: 0.3}[y] for y in (2021, 2022, 2023)]
    res = promotion_gates("B1", cells, years=years, turnover_budget=6.0,
                          sharpe_2x=1.5, pbo=0.1, seed=7)
    assert res["pass"] is True, res["bullets"]
    bad = {k: dict(v, oos=list(-np.array(v["oos"]))) for k, v in cells.items()}
    res2 = promotion_gates("B1", bad, years=[-0.5, -0.4, -0.3],
                           turnover_budget=6.0, sharpe_2x=-1.0, pbo=0.9,
                           seed=7)
    assert res2["pass"] is False
    assert res2["bullets"]["oos_sharpe"] is False


def test_rebalance_calendars():
    from cryptobot.research.family_b_driver import rebalance_dates

    idx = pd.date_range("2021-01-01", "2021-03-31", freq="D", tz="UTC")
    weekly = rebalance_dates(idx, "weekly")
    assert all(d.weekday() == 0 for d in weekly)
    assert len(weekly) == 13
    monthly = rebalance_dates(idx, "monthly")
    assert [str(d.date()) for d in monthly] == ["2021-01-01", "2021-02-01",
                                                "2021-03-01"]
    daily = rebalance_dates(idx, "daily")
    assert len(daily) == len(idx)


def test_walkforward_attribution_pooled_oos():
    from cryptobot.research.family_b_driver import pooled_oos_returns

    idx = pd.date_range("2020-01-01", "2023-12-31", freq="D", tz="UTC")
    full = pd.Series(np.arange(len(idx), dtype=float), index=idx)
    oos = pooled_oos_returns(full, gap_days=35)
    # 2020 excluded; each test year starts 35d in.
    assert oos.index.min() == pd.Timestamp("2021-02-05", tz="UTC")
    assert len(oos) == 3 * (365 - 35)  # 2021-23 all non-leap
    years = sorted(set(oos.index.year))
    assert years == [2021, 2022, 2023]


def test_toml_grids_match_frozen_axes():
    from pathlib import Path

    from cryptobot.research.family_b_driver import expand_grid, load_grid_from_toml

    repo = Path(__file__).resolve().parents[2]
    total = 0
    for h in ("B1", "B2", "B3", "B4", "B5", "B6", "B7"):
        cells = load_grid_from_toml(h, repo / f"research/configs/{h}.toml")
        assert len(cells) == len(expand_grid(h))
        total += len(cells)
    assert total == 59


def test_run_holdout_screen_cold_start_and_metrics():
    import pandas as pd

    from cryptobot.research.family_b_driver import run_holdout_screen
    from cryptobot.research.slow_backtest import CostModel

    dev_idx = pd.date_range("2023-07-01", "2023-12-31", freq="D", tz="UTC")
    hold_idx = pd.date_range("2024-01-01", "2024-06-30", freq="D", tz="UTC")
    dev = {"A": pd.DataFrame({
        "open_time": dev_idx, "open": 100.0, "high": 101.0, "low": 99.0,
        "close": 100.5, "quote_volume": 1e8})}
    hold = {"A": pd.DataFrame({
        "open_time": hold_idx, "open": 100.5, "high": 101.5, "low": 99.5,
        "close": 101.0, "quote_volume": 1e8})}
    out = run_holdout_screen(
        "B1", {"lookback_d": 20, "vol_window_d": 20, "target_vol": 0.20},
        dev_frames={"daily": dev}, sealed_frames={"daily": hold},
        dev_sharpe=1.0, costs=CostModel(), equity=1000.0)
    assert set(out) >= {"point_sharpe", "dev_sharpe", "lb80", "sharpe_2x",
                        "max_dd", "n_rebalances", "turnover", "final_equity"}
    assert out["dev_sharpe"] == 1.0
    assert out["n_rebalances"] > 0
