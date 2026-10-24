#!/usr/bin/env python3
"""Independent break-even audit (F0.4b).

Re-derives the arithmetic from first principles, deliberately NOT
calling ``required_win_rate``:

    EV(p) = p*T - (1-p)*S - c
    0     = p*(T+S) - (S+c)
    p*    = (S+c) / (T+S)

For every row of ``cryptobot.research.cost_model_v2.breakeven_table``
this script checks the published required win rate against the
independent value and asserts EV(p*) is zero (within float tolerance).
Exit code 1 on any discrepancy. No venue access, no credentials.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cryptobot.research.cost_model_v2 import (  # noqa: E402
    CostModel, breakeven_row, breakeven_table)


def ev(p: float, target_bps: float, stop_bps: float, cost_bps: float) -> float:
    return p * target_bps - (1.0 - p) * stop_bps - cost_bps


def independent_required_p(target_bps: float, stop_bps: float,
                           cost_bps: float) -> float:
    return (stop_bps + cost_bps) / (target_bps + stop_bps)


def audit() -> dict:
    problems: list[str] = []
    rows = breakeven_table()
    for row in rows:
        p = independent_required_p(row["target_bps"], row["stop_bps"],
                                   row["round_trip_bps"])
        if abs(p - row["required_win_rate"]) > 1e-4:
            problems.append(
                f"{row['entry']} S={row['stop_bps']} T={row['target_bps']} "
                f"stress={row['stress']}: table={row['required_win_rate']} "
                f"independent={p:.6f}")
        residual = ev(p, row["target_bps"], row["stop_bps"],
                      row["round_trip_bps"])
        if abs(residual) > 1e-6:
            problems.append(
                f"EV(p*)={residual:.9f} for row {row}")
        if (row["required_win_rate"] >= 1.0) != (not row["feasible"]):
            problems.append(f"infeasible flag wrong: {row}")
    # The mandated stress case: 25bps target, 25bps stop, 26bps cost.
    mandated = breakeven_row(stop_bps=25.0, target_bps=25.0,
                             cost_bps=26.0)
    if mandated["required_win_rate"] != 1.02 \
            or mandated["verdict"] != "INFEASIBLE":
        problems.append(f"mandated 25/25/26 case wrong: {mandated}")
    # Default model taker geometry at 25/25: verify against published cost.
    default = next(r for r in rows if r["stop_bps"] == 25.0
                   and r["entry"] == "taker" and r["stress"] == 1.0)
    expected_cost = CostModel().round_trip_bps(maker_entry=False)
    if abs(default["round_trip_bps"] - expected_cost) > 0.01:
        problems.append(f"default round-trip {default['round_trip_bps']} "
                        f"!= model {expected_cost}")
    return {"rows": len(rows), "problems": problems,
            "mandated_25_25_26": mandated,
            "default_taker_25_25": default,
            "ok": not problems}


def main() -> int:
    result = audit()
    print(json.dumps(result, indent=1, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
