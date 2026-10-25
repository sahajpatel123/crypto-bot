"""G1: synthetic-only audit of gate statistics and fail-closed legs."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.gate_calibration import (  # noqa: E402
    _comparison_suite,
    _daily_stream,
    _family_b4b_module,
    _two_x_fee_increment_bps,
    oracle_month_share,
    oracle_positive_year_count,
)


def _all_promotion_metrics(**overrides):
    from cryptobot.research.stats_edge import promotion_failures

    values = dict(oos_sharpe=1.0, adverse_sharpe=0.8, dsr=0.95, pbo=0.1,
                  positive_years=2, plateau=0.9, max_dd=0.1, turnover=2.0,
                  turnover_budget=6.0,
                  anchors={"min_positive_years": 2})
    values.update(overrides)
    return promotion_failures(**values)


def test_synthetic_two_x_fee_stress_matches_b4b_fixed_fee_schedule():
    assert _two_x_fee_increment_bps(_family_b4b_module()) == 49.0


def test_synthetic_event_assignment_preserves_chronological_dependence():
    rng = np.random.default_rng(4)
    trades = np.arange(300, dtype=float)
    _dates, _net, _day_labels, day_ix, event_values = _daily_stream(rng, trades)
    assert np.all(np.diff(day_ix) >= 0)
    assert np.array_equal(event_values, trades)


def test_independent_statistics_match_200_random_inputs_each():
    result = _comparison_suite(n=200, seed=20261025)
    assert result["counts"] == {
        "DSR": 200,
        "PBO": 200,
        "stationary_bootstrap_CI": 200,
        "day_block_bootstrap_CI": 200,
        "Sharpe_1x_and_2x_cost_series": 200,
        "expectancy_1x_and_2x_cost": 200,
        "positive_DEV_year_count": 200,
    }
    assert result["findings"] == []
    assert result["positive_month_rule"]["production_counterpart"] is None
    assert result["pbo_nonfinite_cases_rejected"] > 0


def test_mutation_dsr_guard_rejects_below_frozen_threshold():
    failures = _all_promotion_metrics(dsr=0.799)
    assert any(f.startswith("dsr ") for f in failures)


def test_mutation_pbo_guard_rejects_above_frozen_threshold():
    failures = _all_promotion_metrics(pbo=0.301)
    assert any(f.startswith("pbo ") for f in failures)


def test_pbo_rejects_nonfinite_trial_returns():
    from cryptobot.research.slow_stats import pbo_cscv

    with np.testing.assert_raises_regex(ValueError, "finite returns"):
        pbo_cscv([[0.1, float("nan")], [0.2, 0.3]])


def test_year_net_uses_compensated_sum_before_positive_classification():
    from cryptobot.research.stats_edge import calendar_year_table

    # np.nansum gives +1.73e-18 for this exactly balanced tie series;
    # math.fsum correctly classifies the written net-sum rule as zero.
    values = [-0.01, 0.01, -0.01, 0.0, -0.01, 0.01, 0.01, 0.0, 0.0,
              0.01, -0.01, -0.01, -0.01, -0.01, 0.01, 0.01, 0.0, 0.01,
              0.01, 0.0, 0.0, -0.01, -0.01, -0.01, -0.01, 0.01, 0.0,
              0.0, 0.01, -0.01, 0.01, -0.01, 0.01, 0.0, 0.01, 0.01,
              0.01, 0.0, 0.01, -0.01, -0.01, 0.01, -0.01, -0.01, 0.0,
              -0.01, 0.0, 0.0, 0.01, 0.0]
    idx = pd.date_range("2020-01-01", periods=len(values), freq="D", tz="UTC")
    series = pd.Series(values, index=idx)
    assert float(np.nansum(values)) > 0.0
    assert calendar_year_table(series)[2020]["net"] == 0.0


def test_mutation_positive_year_guard_rejects_one_of_three():
    failures = _all_promotion_metrics(positive_years=1)
    assert any(f.startswith("positive_years ") for f in failures)


def test_mutation_bootstrap_guard_rejects_lower_bound_even_when_p_passes(monkeypatch):
    from cryptobot.research import verdict

    # 3.0% of bootstrap means are non-positive (p <= .05), while the 2.5th
    # percentile is negative. Removing the CI-lower-bound leg makes this PASS.
    draws = [-1.0] * 60 + [1.0] * 1940
    monkeypatch.setattr(verdict, "_block_bootstrap", lambda *a, **k: draws)
    result = verdict.evaluate_trades(
        [1.0] * 300, adverse_bps=[1.0] * 300,
        days=[f"d{i % 3}" for i in range(300)], max_dd_bps=0,
        dd_budget_bps=3500, family_size=1)
    assert result["verdict"] == "FAIL"
    assert result["p_value"] <= 0.05
    assert result["ci95"][0] <= 0.0


def test_mutation_n300_guard_keeps_299_events_underpowered(monkeypatch):
    from cryptobot.research import verdict

    monkeypatch.setattr(verdict, "_block_bootstrap", lambda *a, **k: [1.0] * 2000)
    result = verdict.evaluate_trades(
        [1.0] * 299, adverse_bps=[1.0] * 299,
        days=[f"d{i % 3}" for i in range(299)], max_dd_bps=0,
        dd_budget_bps=3500, family_size=1)
    assert result["verdict"] == "UNDERPOWERED"
    assert result["n_trades"] == 299


def test_mutation_2x_expectancy_guard_rejects_negative_adverse_mean(monkeypatch):
    from cryptobot.research import verdict

    monkeypatch.setattr(verdict, "_block_bootstrap", lambda *a, **k: [1.0] * 2000)
    result = verdict.evaluate_trades(
        [1.0] * 300, adverse_bps=[-0.01] * 300,
        days=[f"d{i % 3}" for i in range(300)], max_dd_bps=0,
        dd_budget_bps=3500, family_size=1)
    assert result["verdict"] == "FAIL"
    assert result["expectancy_bps"] > 0
    assert result["expectancy_adverse_bps"] < 0


def test_positive_month_share_is_only_a_diagnostic_not_a_gate():
    # This helper is deliberately independent; repo search found no production
    # month-share function or frozen monthly-share threshold to compare or test.
    idx = pd.to_datetime(["2020-01-05", "2020-01-15", "2020-02-02",
                          "2020-03-10", "2021-01-01"], utc=True)
    returns = pd.Series([2.0, -1.0, -0.5, 0.0, 1.0], index=idx)
    assert math.isclose(oracle_month_share(returns), 0.5)
    assert oracle_positive_year_count(returns, [2020, 2021]) == 2
