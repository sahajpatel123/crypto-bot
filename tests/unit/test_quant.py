import math
import random

import pytest

from cryptobot.research import quant


def _normal(n, mu, sd, seed):
    rng = random.Random(seed)
    return [rng.gauss(mu, sd) for _ in range(n)]


def test_moments_and_psr_on_symmetric_sample():
    m = quant.moments(_normal(5000, 0.0, 1.0, 1))
    assert abs(m.skew) < 0.15 and abs(m.kurt - 3) < 0.3
    assert quant.probabilistic_sharpe(quant.Moments(500, 0.0, 1.0, 0.0, 3.0)) == 0.5


def test_deflation_penalises_many_trials():
    m = quant.Moments(1000, 0.05, 1.0, 0.0, 3.0)
    psr = quant.probabilistic_sharpe(m)
    assert quant.deflated_sharpe(m, 1) == pytest.approx(psr)
    assert quant.deflated_sharpe(m, 50) < quant.deflated_sharpe(m, 5) < psr


def test_fat_tails_need_longer_records():
    thin = quant.Moments(1000, 0.05, 1.0, 0.0, 3.0)
    fat = quant.Moments(1000, 0.05, 1.0, -1.0, 12.0)
    assert quant.min_track_record(fat) > quant.min_track_record(thin)
    assert quant.min_track_record(quant.Moments(10, -1.0, 1.0, 0, 3)) == math.inf


def test_power_and_required_periods_agree():
    n = quant.required_periods(1.0)  # annual Sharpe 1, daily data
    assert 2200 < n < 2300  # ~6 years: the core budget fact
    assert quant.power_at(1.0, round(n)) == pytest.approx(0.8, abs=0.01)
    assert quant.power_at(1.0, 180) < 0.2  # 180 days is badly underpowered


def test_stouffer_combines_evidence():
    assert quant.stouffer([0.05, 0.05]) < 0.05
    assert quant.stouffer([0.5]) == pytest.approx(0.5)


def test_kelly_shrinks_with_estimation_error():
    assert quant.kelly_leverage(0.01, 0.1) == pytest.approx(1.0)
    assert quant.kelly_leverage(0.01, 0.1, n=100, z=1.0) == 0.0  # edge not defensible
    assert 0 < quant.kelly_leverage(0.01, 0.1, n=10_000, z=1.0) < 1.0
    best = quant.log_growth(1.0, 0.01, 0.1)
    assert best > quant.log_growth(0.5, 0.01, 0.1) and best > quant.log_growth(2.0, 0.01, 0.1)
    assert quant.log_growth(2.0, 0.01, 0.1) == pytest.approx(0.0)  # 2x Kelly: zero growth


def test_vol_target_and_drawdown():
    calm = quant.vol_target_leverage([0.005] * 50, target_sd=0.01, cap=3.0)
    wild = quant.vol_target_leverage([0.04] * 50, target_sd=0.01, cap=3.0)
    assert calm == pytest.approx(2.0) and wild == pytest.approx(0.25)
    assert quant.prob_drawdown(-0.001, 0.01, 0.2) == 1.0
    assert quant.prob_drawdown(0.001, 0.01, 0.4) < quant.prob_drawdown(0.001, 0.01, 0.2)


def test_breakeven_cost():
    assert quant.breakeven_cost(10.0, 0.5) == 20.0


def test_e_process_controls_false_positives_under_null():
    rejections = sum(
        quant.e_process(_normal(400, 0.0, 1.0, seed), bound=4.0).rejected()
        for seed in range(300))
    assert rejections / 300 <= 0.05 + 0.03  # Ville: <= alpha (MC slack)


def test_e_process_finds_a_real_edge():
    ep = quant.e_process(_normal(1500, 0.25, 1.0, 7), bound=4.0)
    assert ep.rejected() and ep.wealth > 20


def test_e_process_bets_nothing_on_losers():
    ep = quant.e_process(_normal(500, -0.2, 1.0, 3), bound=4.0)
    assert ep.wealth <= 1.0 and not ep.rejected()


def test_sequential_design_keeps_nearly_all_fixed_power():
    bounds = quant.obf_bounds(3, sims=20_000)
    assert bounds[0] > bounds[1] > bounds[2] > 1.645  # strict early, ~fixed at end
    seq = quant.sequential_power(1.0, [365, 730, 1095], bounds, sims=20_000)
    assert abs(seq - quant.power_at(1.0, 1095)) < 0.05


def test_drawdown_capped_leverage_hits_the_target_probability():
    lev = quant.drawdown_capped_leverage(0.001, 0.02, depth=0.2, prob=0.05)
    assert quant.prob_drawdown(lev * 0.001, lev * 0.02, 0.2) == pytest.approx(0.05)
    assert quant.drawdown_capped_leverage(-0.001, 0.02, 0.2, 0.05) == 0.0
