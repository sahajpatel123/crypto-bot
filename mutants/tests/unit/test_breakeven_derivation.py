"""F0.4b: break-even derivation from first principles (independent check).

EV per trade (bps, symmetric): EV = p*T - (1-p)*S - c.
Set EV=0 -> p*(T+S) = S + c -> p* = (S + c) / (T + S).
When p* > 1 the geometry can NEVER break even (needs >100% wins):
the table must flag it INFEASIBLE (feasible=False).

This test recomputes every row with plain arithmetic below (it does
NOT call required_win_rate for the expected value), so a formula bug
in cost_model_v2 cannot hide behind its own helper.
"""
from __future__ import annotations

import pytest

from cryptobot.research.cost_model_v2 import (
    CostModel, breakeven_table, required_win_rate)


def _ev_bps(p: float, target: float, stop: float, cost: float) -> float:
    return p * target - (1.0 - p) * stop - cost


def test_ev_zero_at_derived_p():
    # First-principles spot checks of the closed form.
    for stop, target, cost in ((25.0, 25.0, 18.0), (25.0, 50.0, 18.0),
                              (100.0, 200.0, 36.0)):
        p_star = (stop + cost) / (target + stop)
        assert _ev_bps(p_star, target, stop, cost) == pytest.approx(0.0)
        assert required_win_rate(stop_bps=stop, target_bps=target,
                                 cost_bps=cost) == p_star


def test_25_25_at_26bps_is_infeasible():
    # The directive's canonical case: 25/25 geometry at 26bps
    # round-trip needs p = (25+26)/50 = 102% -> impossible.
    p_star = required_win_rate(stop_bps=25.0, target_bps=25.0,
                               cost_bps=26.0)
    assert p_star == 1.02
    assert _ev_bps(1.0, 25.0, 25.0, 26.0) < 0.0  # even 100% wins lose
    rows = breakeven_table()
    # The table's own 25/25 taker rows at 1.5x/2x stress exceed 100%
    # (costs 27/36bps) and MUST carry feasible=False.
    bad = [r for r in rows if r["stop_bps"] == 25.0
           and r["target_bps"] == 25.0 and r["entry"] == "taker"
           and r["stress"] >= 1.5]
    assert len(bad) == 2
    for row in bad:
        assert row["required_win_rate"] > 1.0
        assert row["feasible"] is False, row


def test_every_row_matches_first_principles():
    model = CostModel()
    rows = breakeven_table(model)
    assert len(rows) == 30  # 5 geometries x 2 entries x 3 stresses
    for row in rows:
        stop = row["stop_bps"]
        target = row["target_bps"]
        # Independent cost recomputation (fee schedule, no helpers).
        entry_fee = 2.0 if row["entry"] == "maker" else 5.0
        cost = (entry_fee + 5.0 + 2.0 + 6.0) * row["stress"]
        assert row["round_trip_bps"] == round(cost, 2), row
        p_star = (stop + cost) / (target + stop)
        assert row["required_win_rate"] == round(p_star, 4), row
        assert row["feasible"] is (p_star <= 1.0), row
        # Sanity: at p* the first-principles EV is exactly zero.
        assert _ev_bps(p_star, target, stop, cost) == pytest.approx(0.0)


def test_taker_25_25_exact_numbers():
    # Pins the corrected statement (was the vague ">60%"): 25/25
    # taker at 1x costs 18bps and needs 86% wins; stressed costs are
    # mathematically infeasible (>100%).
    rows = {(r["stress"], r["entry"]): r for r in breakeven_table()
            if r["stop_bps"] == 25.0 and r["target_bps"] == 25.0}
    r1 = rows[(1.0, "taker")]
    assert r1["round_trip_bps"] == 18.0
    assert r1["required_win_rate"] == 0.86
    assert r1["feasible"] is True
    assert rows[(1.5, "taker")]["required_win_rate"] == 1.04
    assert rows[(1.5, "taker")]["feasible"] is False
    assert rows[(2.0, "taker")]["required_win_rate"] == 1.22
    assert rows[(2.0, "taker")]["feasible"] is False
