"""D-052: the two repairs that stop results overstating their own confidence.

(a) deflated_sharpe used the raw daily count as its sample size on a series
    that is mostly exact zeros with strong positive autocorrelation, which
    is why B4 recorded DSR 0.9999998 while its Newey-West t(30) is 2.20.
(b) slow_backtest's "leak-investigate" warning was discarded by the runner
    before the gate document was written.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pandas")

REPO = Path(__file__).resolve().parents[2]


def _ar1(n: int = 2000, phi: float = 0.6, *, mean: float = 0.0001,
         sd: float = 0.001, seed: int = 11):
    rng = np.random.default_rng(seed)
    eps = rng.normal(0.0, sd * np.sqrt(1 - phi ** 2), n)
    x = np.empty(n)
    x[0] = eps[0]
    for i in range(1, n):
        x[i] = phi * x[i - 1] + eps[i]
    return x + mean


# -- (a) effective sample size ----------------------------------------------
def test_effective_n_shrinks_on_persistent_series():
    from cryptobot.research.slow_stats import autocorr_adjusted_n

    x = _ar1(2000, 0.6)
    n_eff = autocorr_adjusted_n(x, max_lag=30)
    # 1 + 2*sum(w_k phi^k) ~ (1+phi)/(1-phi) = 4, so n_eff ~ n/4.
    assert n_eff < 2000 / 3
    assert n_eff == pytest.approx(2000 * (1 - 0.6) / (1 + 0.6), rel=0.35)


def test_effective_n_never_exceeds_days():
    from cryptobot.research.slow_stats import autocorr_adjusted_n

    # Perfectly mean-reverting: no credit for more bets than there are days.
    alternating = [0.01, -0.01] * 500
    assert autocorr_adjusted_n(alternating, max_lag=30) == pytest.approx(1000.0)
    white = list(np.random.default_rng(3).normal(0, 1, 800))
    assert autocorr_adjusted_n(white, max_lag=30) <= 800.0


def test_effective_n_hold_days_cap():
    from cryptobot.research.slow_stats import autocorr_adjusted_n

    white = list(np.random.default_rng(5).normal(0, 1, 900))
    capped = autocorr_adjusted_n(white, max_lag=30, hold_days=30)
    assert capped == pytest.approx(30.0, rel=0.05)
    # A 30-day hold can never be more than 30 draws from 900 days.
    assert autocorr_adjusted_n(white, max_lag=30) > capped


def test_effective_n_floor_and_degenerate_inputs():
    from cryptobot.research.slow_stats import autocorr_adjusted_n

    assert autocorr_adjusted_n([], max_lag=30) == 0.0
    assert autocorr_adjusted_n([0.01], max_lag=30) == 1.0
    assert autocorr_adjusted_n([0.0] * 100, max_lag=30) == 100.0
    # Two observations are the floor, never something smaller.
    assert autocorr_adjusted_n(_ar1(12, 0.9), max_lag=30) >= 2.0


def test_newey_west_t_below_iid_t_on_persistent_series():
    from cryptobot.research.slow_stats import newey_west_tstat

    x = _ar1(2000, 0.6)
    iid = x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))
    nw = newey_west_tstat(x, max_lag=30)
    assert 0 < nw < iid
    assert nw == pytest.approx(iid / 2.0, rel=0.4)


def test_dsr_uses_effective_n_and_never_rises():
    from cryptobot.research.slow_stats import deflated_sharpe, dsr_detail

    # 75% exact zeros with carried-over P&L: the shape that fooled B4.
    rng = np.random.default_rng(17)
    base = np.zeros(900)
    idx = rng.choice(900, size=225, replace=False)
    base[idx] = rng.normal(0.0009, 0.0012, 225)
    trials = [4.4, 4.3, 3.0, 2.8, 2.8, 2.5, 1.4, 1.3, 1.2]
    naive = deflated_sharpe(base, trials, adjust_n=False)
    adjusted = deflated_sharpe(base, trials)
    detail = dsr_detail(base, trials)
    assert detail["n"] == 900
    assert detail["n_eff"] < 900
    assert adjusted <= naive
    assert adjusted < naive


def test_dsr_naive_matches_the_recorded_b4_number():
    """The old code path is reproducible, so nothing is hidden by the fix."""
    from cryptobot.research.slow_stats import deflated_sharpe, dsr_detail

    dev = json.loads((REPO / "research/autopilot_b/dev/B4.json").read_text())
    oos = dev["gates"]["best_oos"]
    trials = list(dev["cell_sharpes"].values())
    assert deflated_sharpe(oos, trials, adjust_n=False) == pytest.approx(
        0.9999998, abs=1e-6)
    assert deflated_sharpe(oos, trials, adjust_n=False) == pytest.approx(
        dev["gates"]["dsr"], abs=1e-9)
    adj = dsr_detail(oos, trials)
    assert adj["acf1"] == pytest.approx(0.464, abs=0.01)
    assert adj["n_eff"] < 200
    assert adj["dsr"] < 0.96            # was 0.9999998 under the naive count
    capped = dsr_detail(oos, trials, hold_days=30)
    assert capped["n_eff"] == pytest.approx(915 / 30, rel=0.01)
    assert capped["dsr"] < adj["dsr"]


# -- (b) backtest flags reach the gate document -----------------------------
def test_promotion_gates_blocks_and_records_leak_flag():
    from cryptobot.research.family_b_driver import promotion_gates

    rng = np.random.default_rng(7)
    # Real cell keys are tuples so plateau_fraction can walk Hamming-1
    # neighbours; two neighbours that differ in one axis are enough here.
    cells = {("a", 1): {"oos": list(rng.normal(0.004, 0.01, 900)),
                        "turnover": 2.0, "dd": 0.10},
             ("a", 2): {"oos": list(rng.normal(0.003, 0.01, 900)),
                        "turnover": 2.0, "dd": 0.10}}
    years = [0.4, 0.5, 0.3]
    clean = promotion_gates("B1", cells, years=years, turnover_budget=6.0,
                            sharpe_2x=1.5, pbo=0.1)
    assert clean["pass"] is True
    assert clean["flags"] == []
    assert clean["bullets"]["flags_clean"] is True

    flagged = promotion_gates("B1", cells, years=years, turnover_budget=6.0,
                              sharpe_2x=1.5, pbo=0.1,
                              flags=["leak-investigate"])
    assert flagged["pass"] is False
    assert flagged["bullets"]["flags_clean"] is False
    assert flagged["flags"] == ["leak-investigate"]
    assert flagged["blocking_flags"] == ["leak-investigate"]

    # An unknown, non-blocking flag is recorded but does not block.
    other = promotion_gates("B1", cells, years=years, turnover_budget=6.0,
                            sharpe_2x=1.5, pbo=0.1, flags=["note"])
    assert other["pass"] is True
    assert other["flags"] == ["note"]


def _run_family_b():
    spec = importlib.util.spec_from_file_location(
        "run_family_b", REPO / "tools" / "run_family_b.py")
    mod = importlib.util.module_from_spec(spec)
    import sys
    sys.modules["run_family_b"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_runner_carries_cell_flags_into_gates_and_artifact(tmp_path,
                                                           monkeypatch):
    """End to end: a backtest flag must survive into dev/B4.json."""
    mod = _run_family_b()
    rng = np.random.default_rng(5)
    oos = list(rng.normal(0.004, 0.01, 900))

    class _Res:
        flags = ["leak-investigate"]
        turnover_oneway = 3.0
        equity = pd.Series([1000.0, 1010.0],
                           index=pd.DatetimeIndex(["2021-01-01", "2021-01-02"],
                                                  tz="UTC"))

    cell = {"result": _Res(), "targets": {},
            "oos": oos, "years": {2021: 0.4, 2022: 0.3, 2023: 0.2},
            "n_rebalances": 3}
    cfg = {"costs": {"perp_taker_bps": 7.5, "spot_taker_bps": 15.0,
                     "spread_bps_per_side": 1.0, "slip_floor_bps": 0.0,
                     "slip_k": 0.5},
           "grid": {"turnover_budget": 12.0},
           "universe": {}}
    monkeypatch.setattr(mod, "load_config", lambda h: (cfg, "sha256"))
    monkeypatch.setattr(mod, "build_market_data",
                        lambda lake, need_hourly=False: {})
    monkeypatch.setattr(mod, "load_grid_from_toml",
                        lambda h: [{"k": 1.5}, {"k": 2.0}])
    monkeypatch.setattr(mod, "evaluate_cell", lambda *a, **k: cell)

    res = mod.evaluate_hypothesis("B4", tmp_path, equity=1000.0)
    assert "leak-investigate" in res["gates"]["flags"]
    assert res["gates"]["pass"] is False
    assert res["gates"]["bullets"]["flags_clean"] is False
    assert res["gates"]["cell_flags"]

    path = mod.write_dev_artifact(tmp_path / "auto_b", res)
    doc = json.loads(path.read_text())
    assert doc["flags"] == ["leak-investigate"]
    assert doc["promotes"] is False
    assert "dsr_naive_unadjusted" in doc["gates"]   # both DSRs are visible
    assert doc["gates"]["dsr"] <= doc["gates"]["dsr_naive_unadjusted"]
