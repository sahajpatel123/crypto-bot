"""T1.8: tiered maintenance margin, isolated liquidation, min equity."""
from __future__ import annotations

import pytest

from cryptobot.risk.margin import (
    liquidation_ok, liquidation_price_isolated, maintenance_margin,
    minimum_viable_equity)

BRACKETS = [
    {"bracket": 1, "notionalCap": 50000.0, "maintMarginRatio": 0.004,
     "cum": 0.0},
    {"bracket": 2, "notionalCap": 250000.0, "maintMarginRatio": 0.005,
     "cum": 50.0},
]


def test_maintenance_margin_tiered():
    assert maintenance_margin(40000.0, BRACKETS) == pytest.approx(160.0)
    # Tier 2: 100000*0.005 - 50 = 450
    assert maintenance_margin(100000.0, BRACKETS) == pytest.approx(450.0)


def test_liquidation_price_isolated_long_short():
    # Long 0.1 BTC @60000, isolated margin 2000, mm=24 (400bps of 6000)
    liq_long = liquidation_price_isolated(
        entry=60000.0, qty=0.1, isolated_margin=2000.0,
        maint_margin=24.0)
    assert liq_long == pytest.approx(60000.0 - (2000.0 - 24.0) / 0.1)
    liq_short = liquidation_price_isolated(
        entry=60000.0, qty=-0.1, isolated_margin=2000.0,
        maint_margin=24.0)
    assert liq_short == pytest.approx(60000.0 + (2000.0 - 24.0) / 0.1)


def test_liquidation_gate_requires_3x_and_beyond_stop():
    # entry 100, stop 99 (dist 1), liq 96: distance 4 >= 3 and beyond
    assert liquidation_ok(entry=100.0, stop=99.0, liq=96.0,
                          stressed_slippage_bps=50.0, side="LONG")
    # liq 97.5: distance 2.5 < 3x stop distance
    assert not liquidation_ok(entry=100.0, stop=99.0, liq=97.5,
                              stressed_slippage_bps=50.0, side="LONG")
    # liq 98.8 beyond stop but within stressed slippage of stop
    assert not liquidation_ok(entry=100.0, stop=99.0, liq=98.8,
                              stressed_slippage_bps=50.0, side="LONG")


def test_minimum_viable_equity():
    # min notional 100 USDT, stop 1% away, budget 0.125% of equity:
    # loss at min size = 100*0.01=1 USDT (+ costs ignored) -> equity 800
    eq = minimum_viable_equity(min_notional_usdt=100.0,
                               stop_dist_frac=0.01,
                               loss_budget_pct=0.00125)
    assert eq == pytest.approx(800.0)
    with pytest.raises(ValueError):
        minimum_viable_equity(min_notional_usdt=100.0, stop_dist_frac=0.0)
