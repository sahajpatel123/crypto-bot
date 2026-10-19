"""Independent break-even verification (F0.4b, run: python tools/verify_breakeven.py).

Re-derives p* = (S + c) / (T + S) from EV = p*T - (1-p)*S - c = 0 using
only stdlib arithmetic, then cross-checks every row of
cost_model_v2.breakeven_table(). Exit 0 when all rows match and every
p* > 1 row carries feasible=False; exit 1 otherwise.

F0.4d: --out writes the machine-readable cost-model JSON cited by
RESEARCH_VERDICTS.md (tool, formula, rows_checked, infeasible rows).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cryptobot.research.cost_model_v2 import breakeven_table


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify break-even table")
    parser.add_argument("--out", default=None,
                        help="Write machine cost-model JSON here (F0.4d)")
    args = parser.parse_args()
    rows = breakeven_table()
    failures: list[str] = []
    for row in rows:
        stop = row["stop_bps"]
        target = row["target_bps"]
        entry_fee = 2.0 if row["entry"] == "maker" else 5.0
        cost = (entry_fee + 5.0 + 2.0 + 6.0) * row["stress"]
        p_star = (stop + cost) / (target + stop)
        ev = p_star * target - (1.0 - p_star) * stop - cost
        if abs(ev) > 1e-9:
            failures.append(f"EV!=0: {row}")
        if row["round_trip_bps"] != round(cost, 2):
            failures.append(f"cost mismatch: {row} vs {cost}")
        if row["required_win_rate"] != round(p_star, 4):
            failures.append(f"p* mismatch: {row} vs {p_star}")
        if row["feasible"] is not (p_star <= 1.0):
            failures.append(f"feasible flag wrong: {row}")
    # Canonical directive case.
    p26 = (25.0 + 26.0) / 50.0
    print(f"25/25 @26bps needs p={p26:.2%} -> "
          f"{'INFEASIBLE' if p26 > 1 else 'feasible'}")
    infeasible = sum(1 for r in rows if r["feasible"] is False)
    print(f"checked {len(rows)} rows, {infeasible} infeasible")
    infeasible_rows = [r for r in rows if r["feasible"] is False]
    for row in infeasible_rows:
        print(f"  INFEASIBLE stop={row['stop_bps']} target={row['target_bps']} "
              f"{row['entry']} {row['stress']}x p={row['required_win_rate']}")
    if args.out:
        doc = {"tool": "verify_breakeven", "formula": "p*=(S+c)/(T+S)",
               "ev": "EV=p*T-(1-p)*S-c", "rows_checked": len(rows),
               "mismatches": failures,
               "infeasible": infeasible_rows,
               "canonical_25_25_at_26bps": {"p_star": p26,
                                            "verdict": "INFEASIBLE"}}
        doc["document_sha256"] = hashlib.sha256(
            json.dumps(doc, sort_keys=True).encode()).hexdigest()
        Path(args.out).write_text(json.dumps(doc, indent=1, sort_keys=True)
                                  + "\n", encoding="utf-8")
        print(f"wrote {args.out}")
    if failures:
        print(f"{len(failures)} MISMATCHES:")
        for failure in failures[:10]:
            print(f"  {failure}")
        return 1
    print("OK: every row matches first principles.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
