"""F0.4b: independent break-even verification (no circular derivation)."""
from __future__ import annotations

import math

import pytest

from cryptobot.research.cost_model_v2 import (
    CostModel,
    breakeven_row,
    breakeven_table,
    required_win_rate,
)


def ev(p: float, target: float, stop: float, cost: float) -> float:
    return p * target - (1.0 - p) * stop - cost


def independent_p(target: float, stop: float, cost: float) -> float:
    return (stop + cost) / (target + stop)


def test_expectancy_definition():
    # EV = p*T - (1-p)*S - c: 50% at +50 / -25 with 18 cost = -5.5
    assert ev(0.5, 50.0, 25.0, 18.0) == pytest.approx(-5.5)
    # Break-even p for +25/-25 at 26bps round-trip cost is 102%: impossible.
    p = required_win_rate(stop_bps=25.0, target_bps=25.0, cost_bps=26.0)
    assert p == pytest.approx(1.02)
    row = breakeven_row(stop_bps=25.0, target_bps=25.0, cost_bps=26.0)
    assert row["required_win_rate_pct"] == pytest.approx(102.0)
    assert row["feasible"] is False
    assert row["verdict"] == "INFEASIBLE"
    assert ev(p, 25.0, 25.0, 26.0) == pytest.approx(0.0)


def test_every_table_row_matches_independent_derivation():
    rows = breakeven_table()
    assert len(rows) == 30
    for row in rows:
        p = independent_p(row["target_bps"], row["stop_bps"],
                          row["round_trip_bps"])
        assert p == pytest.approx(row["required_win_rate"], abs=1e-4), row
        assert ev(p, row["target_bps"], row["stop_bps"],
                  row["round_trip_bps"]) == pytest.approx(0.0, abs=1e-6)
        assert row["feasible"] is (p < 1.0)
        if p > 1.0:
            assert row["verdict"] == "INFEASIBLE"


def test_default_taker_25_25_is_86_percent_not_60_65():
    # The prior research note said ">60-65%"; the true default-model
    # number at 18bps cost is 86%. This pins the correction.
    row = next(r for r in breakeven_table()
               if r["stop_bps"] == 25.0 and r["target_bps"] == 25.0
               and r["entry"] == "taker" and r["stress"] == 1.0)
    assert row["round_trip_bps"] == pytest.approx(
        CostModel().round_trip_bps(maker_entry=False))
    assert row["required_win_rate"] == pytest.approx(
        (25.0 + row["round_trip_bps"]) / 50.0, abs=1e-4)
    assert row["required_win_rate"] > 0.85
    assert not math.isinf(row["required_win_rate"])


def test_cost_at_or_above_target_is_always_infeasible():
    for stop, target, cost in ((10.0, 10.0, 10.0),
                               (25.0, 25.0, 25.1),
                               (5.0, 50.0, 50.0)):
        row = breakeven_row(stop_bps=stop, target_bps=target,
                            cost_bps=cost)
        assert row["verdict"] == "INFEASIBLE"


def test_audit_script_passes():
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "breakeven_audit", root / "tools" / "breakeven_audit.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    result = mod.audit()
    assert result["ok"], result["problems"]
    assert result["mandated_25_25_26"]["verdict"] == "INFEASIBLE"
