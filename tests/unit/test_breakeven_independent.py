"""F0.4b: break-even table verified from first principles.

EV = p*T - (1-p)*S - c = 0  =>  p = (S + c)/(T + S).
At 25/25 geometry with 26bps round-trip, p = 102% -> INFEASIBLE.
"""
import pytest

from cryptobot.research.cost_model_v2 import (
    CostModel, breakeven_table, required_win_rate)


def test_infeasible_geometry_flagged():
    assert required_win_rate(stop_bps=25, target_bps=25,
                             cost_bps=26) == pytest.approx(1.02)
    rows = breakeven_table(CostModel(taker_bps=10.0, maker_bps=10.0,
                                     spread_bps=2.0, slippage_bps=4.0))
    row = next(r for r in rows if r["stop_bps"] == 25.0
               and r["target_bps"] == 25.0 and r["entry"] == "taker"
               and r["stress"] == 1.0)
    # round trip = 10+10+2+4 = 26 -> p = 51/50 = 1.02 INFEASIBLE
    assert row["round_trip_bps"] == pytest.approx(26.0)
    assert row["required_win_rate"] == pytest.approx(1.02)
    assert row["feasible"] is False


def test_every_row_matches_first_principles():
    for row in breakeven_table():
        expect = (row["stop_bps"] + row["round_trip_bps"]) / (
            row["target_bps"] + row["stop_bps"])
        assert row["required_win_rate"] == pytest.approx(round(expect, 4))
        assert row["feasible"] == (expect <= 1.0)
