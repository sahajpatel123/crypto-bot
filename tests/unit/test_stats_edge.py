"""E5: statistics module — formulas, CSCV, SPA, folds, gates."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pandas")


def test_sharpe_known_scale():
    from cryptobot.research.stats_edge import period_sharpe, sharpe_ratio

    # Deterministic two-point series: mean 0.01, sample std known.
    r = np.array([0.02, 0.0] * 50)
    # mean = 0.01, sample std of alternating 0.02/0.0:
    sd = float(r.std(ddof=1))
    assert period_sharpe(r) == pytest.approx(0.01 / sd)
    assert sharpe_ratio(r) == pytest.approx((0.01 / sd) * math.sqrt(365))


def test_deflated_sharpe_hand_moments_and_trial_penalty():
    from cryptobot.research.stats_edge import deflated_sharpe_ratio, expected_maximum_sharpe

    # Strong signal, single trial: DSR against a zero benchmark is ~1.
    rng = np.random.default_rng(1)
    good = rng.normal(0.01, 0.02, 400)
    dsr_one = deflated_sharpe_ratio(good, [0.5])
    assert dsr_one > 0.99
    # Same returns, many high competing Sharpes: the hurdle rises.
    dsr_many = deflated_sharpe_ratio(good, [0.5] * 50)
    # Identical trial Sharpes have variance 0, so the hurdle stays 0.
    assert dsr_many == pytest.approx(dsr_one)
    spread = [0.0, 0.2, 0.4, 0.5, 0.8, 1.0]
    dsr_spread = deflated_sharpe_ratio(good, spread)
    assert expected_maximum_sharpe(len(spread), float(np.std(spread, ddof=1))) > 0
    assert dsr_spread < dsr_one


def test_drawdown_and_capacity():
    from cryptobot.research.stats_edge import capacity_notional, max_drawdown

    # +10%, then -50% from the peak: equity 1 -> 1.1 -> 0.55, dd = 0.5.
    assert max_drawdown([0.10, -0.50]) == pytest.approx(0.5)
    adv = 1e8
    q = capacity_notional(adv, sigma_daily=0.02, slip_budget_bps=5.0)
    # ratio = 5 / (0.5 * 0.02 * 10000) = 0.05; q = ADV * 0.0025 = 2.5e5
    assert q == pytest.approx(2.5e5)
    assert capacity_notional(0.0, 0.02) == 0.0


def test_pbo_detects_pure_overfit_and_stable_winner():
    from cryptobot.research.stats_edge import probability_backtest_overfitting

    rng = np.random.default_rng(4)
    noise = rng.normal(0.0, 0.002, 80)
    # Two slices. A wins slice 0 and loses slice 1; B is the mirror.
    a = np.concatenate([np.full(40, 0.02), np.full(40, -0.02)]) + noise
    b = -a
    pbo = probability_backtest_overfitting(np.column_stack([a, b]), n_splits=2)
    assert pbo == pytest.approx(1.0)
    # A dominates both halves (noise is small relative to the gap).
    stable = np.column_stack([
        np.full(80, 0.02) + noise,
        np.full(80, -0.02) + noise,
    ])
    assert probability_backtest_overfitting(stable, n_splits=2) == pytest.approx(0.0)


def test_spa_rejects_noise_and_flags_a_real_column():
    from cryptobot.research.stats_edge import hansen_spa

    rng = np.random.default_rng(2)
    noise = rng.normal(0.0, 0.01, size=(300, 6))
    quiet = hansen_spa(noise, n_boot=80, block=10, seed=2)
    assert quiet["spa_pvalue"] > 0.05
    signal = noise.copy()
    signal[:, 0] += 0.01
    loud = hansen_spa(signal, n_boot=80, block=10, seed=2)
    assert loud["spa_pvalue"] < quiet["spa_pvalue"]
    assert loud["white_pvalue"] < 0.05


def test_plateau_and_folds():
    from cryptobot.research.stats_edge import (
        anchored_yearly_folds,
        hamming_neighbors,
        plateau_fraction,
    )

    cells = [
        {"id": "a", "L": 20, "V": 20},
        {"id": "b", "L": 60, "V": 20},
        {"id": "c", "L": 20, "V": 60},
        {"id": "d", "L": 60, "V": 60},
    ]
    neigh = hamming_neighbors(cells)
    assert set(neigh["a"]) == {"b", "c"}
    assert plateau_fraction({"a": 1, "b": 0.2, "c": -0.1, "d": 0.3}, neigh, "a") == 0.5
    idx = pd.date_range("2020-01-01", "2023-12-31", freq="D", tz="UTC")
    folds = anchored_yearly_folds(idx, [2021, 2022, 2023], purge_days=30,
                                  embargo_days=5)
    assert [f.year for f in folds] == [2021, 2022, 2023]
    # First scored day of 2021 is Jan 31 (30 days after Jan 1).
    assert folds[0].test.min() == pd.Timestamp("2021-01-31", tz="UTC")
    # Train ends 5 days before 2021-01-01.
    assert folds[0].train.max() == pd.Timestamp("2020-12-26", tz="UTC")
    assert folds[1].train.max() == pd.Timestamp("2021-12-26", tz="UTC")


def test_promotion_and_screen_gates():
    from cryptobot.research.stats_edge import holdout_screen_failures, promotion_failures

    ok = dict(oos_sharpe=0.8, adverse_sharpe=0.4, dsr=0.9, pbo=0.2,
              positive_years=3, plateau=0.8, max_dd=0.2, turnover=2.0,
              turnover_budget=6.0)
    assert promotion_failures(**ok) == []
    bad = dict(ok, oos_sharpe=0.2, pbo=0.9)
    fails = promotion_failures(**bad)
    assert any("oos_sharpe" in f for f in fails)
    assert any("pbo" in f for f in fails)
    # B1's prereg adjustment: 2 of 3 OOS years, not 3 of 4.
    assert promotion_failures(**dict(ok, positive_years=2),
                              anchors={"min_positive_years": 2}) == []
    screen_ok = dict(point_sharpe=0.5, dev_oos_sharpe=0.8, lb80=-0.1,
                     adverse_sharpe=0.1, max_dd=0.2)
    assert holdout_screen_failures(**screen_ok) == []
    # 0.2 is not >= 50% of dev 0.8.
    screen_bad = dict(screen_ok, point_sharpe=0.35)
    assert holdout_screen_failures(**screen_bad)


def test_bootstrap_lb_orders_with_drift():
    from cryptobot.research.stats_edge import bootstrap_sharpe_bounds

    rng = np.random.default_rng(3)
    flat = rng.normal(0.0, 0.01, 400)
    up = rng.normal(0.004, 0.01, 400)
    a = bootstrap_sharpe_bounds(flat, n_boot=60, block=10, seed=3)
    b = bootstrap_sharpe_bounds(up, n_boot=60, block=10, seed=3)
    assert b["low"] > a["low"]
    assert a["low"] <= a["point"] <= a["high"]
