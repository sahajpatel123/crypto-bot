"""X1 frozen economics report assembler (X1.md section 11).

Reads single-cell comparison.json files plus each cell's run dir
(report.json, fills.jsonl) and assembles one economics.json with
ledger-reconciled nets, costs, and the 100-pos/10d screen math.
No scoring in parallel: every net is the Session ledger's own
closing-opening; this tool only aggregates and counts.

Closed positions (frozen definition): number of times the
cumulative signed base qty from fills.jsonl (in file order) returns
to flat (|residual| < 1e-9) after being non-flat. The open tail
residual is reported alongside; max flat-residual is recorded.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

FLAT_TOL = 1e-9


def closed_positions(fills_path: Path) -> dict:
    """Count round-trips from fills.jsonl (frozen definition)."""
    rows = [json.loads(line) for line in
            fills_path.read_text(encoding="utf-8").splitlines()
            if line.strip()] if fills_path.exists() else []
    cum = 0.0
    closed = 0
    was_flat = True
    max_residual = 0.0
    for row in rows:
        side = str(row.get("side", "")).upper()
        qty = float(row.get("qty", 0.0))
        signed = qty if side in ("LONG", "BUY") else -qty
        cum += signed
        if abs(cum) < FLAT_TOL:
            max_residual = max(max_residual, abs(cum))
            if not was_flat:
                closed += 1
            was_flat = True
            cum = 0.0
        else:
            was_flat = False
    return {"closed_positions": closed, "n_fills": len(rows),
            "open_tail_qty": cum, "max_flat_residual": max_residual}


def assemble(comparison_files: list[str], registry_path: str,
             tag: str) -> dict:
    from cryptobot.research.backtest import SPLITS

    registry = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    arm_to_config = {c["arm"]: c["config_id"]
                     for c in registry["configs"]}
    cells = []
    for path in comparison_files:
        comparison = json.loads(Path(path).read_text(encoding="utf-8"))
        if len(comparison.get("cells", {})) != 1:
            raise ValueError(f"{path}: expected exactly 1 cell")
        (key, metrics), = comparison["cells"].items()
        armset, _, split = key.partition("|")
        run_dir = Path(metrics["run_dir"])
        report = json.loads(
            (run_dir / "report.json").read_text(encoding="utf-8"))
        positions = closed_positions(run_dir / "fills.jsonl")
        net = float(report["closing_equity"]) - float(
            report["opening_equity"])
        cells.append({
            "comparison": path, "armset": armset, "split": split,
            "config_id": arm_to_config.get(armset),
            "dataset_manifest_sha": comparison.get(
                "dataset_manifest_sha"),
            "config_fingerprint": report.get("config_fingerprint"),
            "fee_schedule": report.get("fee_schedule"),
            "opening_equity": report["opening_equity"],
            "closing_equity": report["closing_equity"],
            "ledger_net": net,
            "net_return_pct": report["net_return_pct"],
            "paid_costs": report["paid_costs"],
            "funding_net": report["funding_net"],
            "realised": report["realised"],
            "intents_admitted": report["intents_admitted"],
            "reject_counts": report["reject_counts"],
            **positions,
        })
    # Screen math per config over dev+val (frozen split lengths).
    by_config: dict[str, dict] = {}
    for cell in cells:
        by_config.setdefault(cell["config_id"], []).append(cell)
    screens = {}
    for config_id, group in sorted(by_config.items()):
        days = sum(len(SPLITS[c["split"]]) for c in group
                   if c["split"] in SPLITS)
        closed = sum(c["closed_positions"] for c in group)
        per_10d = closed * 10 / days if days else 0.0
        screens[config_id] = {
            "closed_positions": closed, "split_days": days,
            "positions_per_10d": per_10d,
            "screen_100pos_10d": "PASS" if per_10d >= 100 else "BELOW",
        }
    return {"tag": tag, "rule": "X1.md section 11",
            "cells": sorted(cells, key=lambda c: (c["config_id"] or "",
                                                 c["split"])),
            "screens": screens}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--comparisons", nargs="+", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--tag", required=True,
                        choices=["realistic", "adverse"])
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        result = assemble(args.comparisons, args.registry, args.tag)
    except ValueError as exc:
        print(f"BLOCKED: {exc}")
        return 3
    result["inputs"] = {"comparisons": args.comparisons,
                        "registry": args.registry}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    for config_id, screen in sorted(result["screens"].items()):
        print(f"{config_id}: closed={screen['closed_positions']} "
              f"per10d={screen['positions_per_10d']:.1f} "
              f"{screen['screen_100pos_10d']}")
    print(f"economics[{args.tag}]: {len(result['cells'])} cells -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
