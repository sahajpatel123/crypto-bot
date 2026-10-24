"""E7: slow path plans risk and paper attribution, and sends no orders."""
from __future__ import annotations

from cryptobot.research.slow_path import (
    PortfolioLimits, apply_risk, fractional_kelly, no_trade, paper_attribute,
    twap_slices)


def test_daily_loss_flattens():
    decision = apply_risk({"BTCUSDT": 0.4, "SPOT:BTCUSDT": 0.4},
                          equity=10_000, day_pnl=-250, week_pnl=0)
    assert decision.ok is False
    assert decision.targets == {}
    assert "daily loss stop" in decision.reasons


def test_gross_and_per_symbol_caps():
    decision = apply_risk({f"S{i}": 0.9 for i in range(5)},
                          equity=1000, day_pnl=0, week_pnl=0,
                          limits=PortfolioLimits(net_cap=10))
    assert decision.ok
    assert abs(sum(abs(v) for v in decision.targets.values()) - 2.0) < 1e-9
    assert max(abs(v) for v in decision.targets.values()) <= 0.5 + 1e-12


def test_twap_and_no_trade_band():
    assert twap_slices(90.0, 3) == [30.0, 30.0, 30.0]
    assert twap_slices(0.0, 4) == []
    kept = no_trade({"A": 0.10}, {"A": 0.12}, band=0.05)
    assert kept["A"] == 0.10
    moved = no_trade({"A": 0.10}, {"A": 0.20}, band=0.05)
    assert moved["A"] == 0.20


def test_kelly_uses_lower_bound_not_a_point_estimate():
    assert fractional_kelly(-0.01, 0.02) == 0.0
    # lower mean 0.02, variance 0.04 -> full kelly 0.5, quarter-kelly 0.125
    assert fractional_kelly(0.02, 0.04, fraction=0.25) == 0.125
    assert fractional_kelly(1.0, 0.1, fraction=1.0, hard_cap=0.5) == 0.5


def test_paper_attribute_sends_nothing():
    row = paper_attribute(predicted_pnl=1.0, realized_pnl=0.4,
                          predicted_cost=0.2, realized_cost=0.5)
    assert row["orders_sent"] == 0
    assert row["pnl_error"] == -0.6
    assert row["cost_error"] == 0.3
