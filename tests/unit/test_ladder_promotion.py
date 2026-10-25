"""Operational ladder promotion rule: conservative, and refuses on missing evidence.

These are sizing rules, not research gates; no test here asserts an edge.
"""
from __future__ import annotations

import pytest

from cryptobot.risk.ladder import (
    PROMOTION_COST_MULTIPLE,
    PROMOTION_DRAWDOWN_MULTIPLE,
    PROMOTION_MIN_LIVE_DAYS,
    PROMOTION_MIN_LIVE_ROUND_TRIPS,
    PROMOTION_SHARPE_FRACTION,
    BacktestReference,
    LiveStatistics,
    Promotion,
    next_rung,
    promotion_decision,
)


def _good_live(**overrides: object) -> LiveStatistics:
    values: dict[str, object] = {
        "round_trips": PROMOTION_MIN_LIVE_ROUND_TRIPS + 20,
        "days": PROMOTION_MIN_LIVE_DAYS + 1,
        "sharpe": 0.50,
        "cost_bps": 4.0,
        "max_drawdown_frac": 0.02,
        "halted": False,
    }
    values.update(overrides)
    return LiveStatistics(**values)


def _good_backtest(**overrides: object) -> BacktestReference:
    values: dict[str, object] = {"sharpe": 0.80, "cost_bps": 3.5,
                                 "max_drawdown_frac": 0.015}
    values.update(overrides)
    return BacktestReference(**values)


def test_good_evidence_promotes_exactly_one_rung() -> None:
    decision = promotion_decision(
        current_rung="canary", live=_good_live(), backtest=_good_backtest())
    assert isinstance(decision, Promotion)
    assert decision.allowed is True
    assert decision.rung == "armed"
    assert decision.reasons == ()
    assert next_rung("canary") == "armed"


def test_missing_evidence_refuses_with_every_reason() -> None:
    decision = promotion_decision(
        current_rung="canary",
        live=LiveStatistics(round_trips=0, days=0.0),
        backtest=BacktestReference())
    assert decision.allowed is False
    assert decision.rung == "canary"
    assert decision.reasons == (
        f"live-round-trips<{PROMOTION_MIN_LIVE_ROUND_TRIPS}",
        f"live-days<{PROMOTION_MIN_LIVE_DAYS:g}",
        "live-sharpe-missing",
        "backtest-sharpe-missing",
        "live-cost-missing",
        "backtest-cost-missing",
        "live-drawdown-missing",
        "backtest-drawdown-missing",
    )


def test_minimum_round_trips_and_days_are_enforced() -> None:
    short_trips = promotion_decision(
        current_rung="canary",
        live=_good_live(round_trips=PROMOTION_MIN_LIVE_ROUND_TRIPS - 1),
        backtest=_good_backtest())
    assert short_trips.allowed is False
    assert f"live-round-trips<{PROMOTION_MIN_LIVE_ROUND_TRIPS}" in \
        short_trips.reasons
    short_days = promotion_decision(
        current_rung="canary",
        live=_good_live(days=PROMOTION_MIN_LIVE_DAYS - 0.5),
        backtest=_good_backtest())
    assert short_days.allowed is False
    assert f"live-days<{PROMOTION_MIN_LIVE_DAYS:g}" in short_days.reasons


def test_live_sharpe_must_reach_the_documented_fraction() -> None:
    threshold = PROMOTION_SHARPE_FRACTION * 0.80
    passing = promotion_decision(
        current_rung="canary", live=_good_live(sharpe=threshold),
        backtest=_good_backtest())
    assert passing.allowed is True
    failing = promotion_decision(
        current_rung="canary", live=_good_live(sharpe=threshold - 0.001),
        backtest=_good_backtest())
    assert failing.allowed is False
    assert "live-sharpe<0.5x-backtest" in failing.reasons


def test_backtest_sharpe_must_be_above_zero() -> None:
    decision = promotion_decision(
        current_rung="canary", live=_good_live(),
        backtest=_good_backtest(sharpe=0.0))
    assert decision.allowed is False
    assert "backtest-sharpe<=0" in decision.reasons


def test_realised_cost_must_stay_within_the_documented_multiple() -> None:
    limit = PROMOTION_COST_MULTIPLE * 3.5
    assert promotion_decision(
        current_rung="canary", live=_good_live(cost_bps=limit),
        backtest=_good_backtest()).allowed is True
    over = promotion_decision(
        current_rung="canary", live=_good_live(cost_bps=limit + 0.01),
        backtest=_good_backtest())
    assert over.allowed is False
    assert "live-cost>1.5x-backtest" in over.reasons


def test_drawdown_must_stay_within_the_documented_multiple() -> None:
    limit = PROMOTION_DRAWDOWN_MULTIPLE * 0.015
    assert promotion_decision(
        current_rung="canary", live=_good_live(max_drawdown_frac=limit),
        backtest=_good_backtest()).allowed is True
    over = promotion_decision(
        current_rung="canary", live=_good_live(max_drawdown_frac=limit + 1e-9),
        backtest=_good_backtest())
    assert over.allowed is False
    assert "live-drawdown>1.5x-backtest" in over.reasons


def test_zero_backtest_drawdown_or_cost_is_not_a_reference() -> None:
    decision = promotion_decision(
        current_rung="canary", live=_good_live(),
        backtest=_good_backtest(max_drawdown_frac=0.0, cost_bps=0.0))
    assert decision.allowed is False
    assert "backtest-drawdown<=0" in decision.reasons
    assert "backtest-cost<=0" in decision.reasons


def test_a_halted_risk_state_refuses_promotion() -> None:
    decision = promotion_decision(
        current_rung="canary", live=_good_live(halted=True),
        backtest=_good_backtest())
    assert decision.allowed is False
    assert "risk-halted" in decision.reasons


def test_never_promotes_out_of_halted_or_skips_a_rung() -> None:
    halted = promotion_decision(
        current_rung="halted", live=_good_live(), backtest=_good_backtest())
    assert halted.allowed is False
    assert halted.rung == "halted"
    assert halted.reasons == ("rung-halted",)
    armed = promotion_decision(
        current_rung="armed", live=_good_live(), backtest=_good_backtest())
    assert armed.allowed is False
    assert armed.rung == "armed"
    assert armed.reasons == ("rung-already-armed",)


def test_unknown_rung_is_refused() -> None:
    decision = promotion_decision(
        current_rung="turbo", live=_good_live(), backtest=_good_backtest())
    assert decision.allowed is False
    assert decision.reasons[0].startswith("unknown-rung:")


@pytest.mark.parametrize("field,reason", [
    ("sharpe", "live-sharpe-missing"),
    ("cost_bps", "live-cost-missing"),
    ("max_drawdown_frac", "live-drawdown-missing"),
])
def test_non_finite_live_statistics_are_treated_as_missing(
        field: str, reason: str) -> None:
    decision = promotion_decision(
        current_rung="canary", live=_good_live(**{field: float("nan")}),
        backtest=_good_backtest())
    assert decision.allowed is False
    assert reason in decision.reasons
