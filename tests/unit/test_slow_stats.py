"""E5: slow statistics — bootstrap, DSR, PBO, reality check, WF, plateau."""
from __future__ import annotations

import math

import numpy as np
import pytest

pytest.importorskip("pandas")


def test_sharpe_drawdown_hand_computed():
    from cryptobot.research.slow_stats import max_drawdown, sharpe

    assert sharpe([0.01] * 100, periods=100) == 0.0  # zero vol
    # Alternating +-0.015 around mean 0.005, n=100, ddof=1, annualize x2.
    assert sharpe([0.02, -0.01] * 50, periods=4) == pytest.approx(
        (0.005 / (0.015 * math.sqrt(100 / 99))) * 2.0, rel=1e-9)
    # Equity 1 -> 1.1 -> 1.045 -> 1.254: trough depth 1-1.045/1.1.
    assert max_drawdown([0.0, 0.1, -0.05, 0.2]) == pytest.approx(0.05)


def test_stationary_bootstrap_ci_covers_and_collapses():
    from cryptobot.research.slow_stats import stationary_bootstrap_ci

    rng = np.random.default_rng(7)
    vals = list(rng.normal(0.01, 0.05, 500))
    lo, hi = stationary_bootstrap_ci(vals, np.mean, mean_block=5,
                                     rounds=500, seed=7)
    assert lo < float(np.mean(vals)) < hi  # covers the sample mean
    assert hi - lo < 0.03
    lo2, hi2 = stationary_bootstrap_ci([3.0] * 50, np.mean, mean_block=5,
                                       rounds=100, seed=7)
    assert (lo2, hi2) == (3.0, 3.0)


def test_normal_quantile_known_values():
    from cryptobot.research.slow_stats import _phi_inv

    assert _phi_inv(0.975) == pytest.approx(1.959964, rel=1e-5)
    assert _phi_inv(0.95) == pytest.approx(1.644854, rel=1e-5)
    assert _phi_inv(0.5) == pytest.approx(0.0, abs=1e-9)


def test_dsr_exact_and_monotone():
    from cryptobot.research.slow_stats import deflated_sharpe

    # K=1, zero mean -> exactly 0.5 (SR0=0 under a single draw).
    assert deflated_sharpe([0.01, -0.01] * 500, [0.0]) == pytest.approx(
        0.5, abs=1e-12)
    # Standout SR=2 with 20 trials -> near 1.
    rets = [0.001047 + 0.01, 0.001047 - 0.01] * 500
    assert deflated_sharpe(rets, [2.0] + [0.0] * 19) > 0.99
    # More trials at fixed variance -> lower DSR.
    d2 = deflated_sharpe(rets, [2.0, -2.0])
    d50 = deflated_sharpe(rets, [2.0, -2.0] * 25)
    assert d50 < d2


def test_pbo_noise_vs_skill():
    from cryptobot.research.slow_stats import pbo_cscv

    # Single-matrix noise PBO is high-variance (few trials); the mean
    # over seeds centers near 0.5 while persistent skill stays low.
    noise_means = []
    for seed in (21, 22, 23, 24, 25):
        rng = np.random.default_rng(seed)
        noise = [list(rng.normal(0, 1, 1200)) for _ in range(10)]
        noise_means.append(pbo_cscv(noise, n_partitions=8, seed=seed))
    assert 0.25 < sum(noise_means) / len(noise_means) < 0.65
    for seed in (21, 22, 23):
        rng = np.random.default_rng(seed)
        skill = [list(rng.normal(0.12 if k == 0 else 0.0, 1, 1200))
                 for k in range(10)]
        assert pbo_cscv(skill, n_partitions=8, seed=seed) < 0.25


def test_reality_check_noise_vs_skill():
    from cryptobot.research.slow_stats import reality_check_pvalue

    rng = np.random.default_rng(33)
    noise = [list(rng.normal(0, 1, 800)) for _ in range(8)]
    assert reality_check_pvalue(noise, rounds=200, seed=33) > 0.15
    skill = [list(rng.normal(0.15 if k == 0 else 0.0, 1, 800))
             for k in range(8)]
    assert reality_check_pvalue(skill, rounds=200, seed=33) < 0.05


def test_walk_forward_purge_embargo():
    import pandas as pd

    from cryptobot.research.slow_stats import walk_forward_splits

    dates = pd.date_range("2020-01-01", "2023-12-31", freq="D", tz="UTC")
    folds = walk_forward_splits(dates, test_years=(2021, 2022, 2023),
                                purge_days=30, embargo_days=5)
    assert len(folds) == 3
    for (tr0, tr1, te0, te1, eval0), year in zip(folds, (2021, 2022, 2023)):
        assert dates[te0].year == year and dates[te1].year == year
        assert (dates[te0] - dates[tr1]).days >= 35  # purge + embargo gap
        assert (dates[eval0] - dates[te0]).days >= 35  # attribution gap
        assert dates[tr0] == dates[0]  # anchored
    # Expanding: later train ends advance (still gapped before own test).
    assert folds[1][1] > folds[0][1] > 0
    # B4-30d cells: gap scales to 2x max holding (60d).
    folds60 = walk_forward_splits(dates, test_years=(2022,), max_hold_d=30)
    (tr0, tr1, te0, te1, eval0) = folds60[0]
    assert (dates[te0] - dates[tr1]).days >= 60
    assert (dates[eval0] - dates[te0]).days >= 60


def test_plateau_fraction():
    from cryptobot.research.slow_stats import plateau_fraction

    cells = {("a", 1): 0.5, ("a", 2): -0.1, ("b", 1): 0.3}
    assert plateau_fraction(cells) == pytest.approx(0.5)
    assert plateau_fraction({("a", 1): 0.5}) == 1.0  # no neighbors: vacuous


def test_year_breakdown_tail_capacity():
    import pandas as pd

    from cryptobot.research.slow_stats import (
        capacity_estimate, tail_metrics, year_breakdown)

    idx = pd.date_range("2021-01-01", periods=730, freq="D", tz="UTC")
    rets = pd.Series([0.002, 0.0] * 365, index=idx)
    yb = year_breakdown(rets)
    assert set(yb) == {2021, 2022} and yb[2021] > 0
    tail = tail_metrics([-0.05, -0.01] * 25 + [0.02] * 50)
    assert set(tail) >= {"var_95", "var_99", "cvar_95", "cvar_99", "skew",
                         "kurt", "worst_day", "worst_month"}
    assert tail["var_99"] >= tail["var_95"] >= 0  # deeper tail worse
    assert tail["worst_day"] == pytest.approx(-0.05)
    cap = capacity_estimate(median_adv=1e8, max_participation=0.01,
                            gross_turnover_per_year=6.0)
    assert cap == pytest.approx(0.01 * 1e8 * 365.0 / 6.0)
