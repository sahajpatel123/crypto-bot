"""X1 frozen selection rule (X1.md section 10).

At most ONE X1 config advances: highest validation REALISTIC ledger
net among configs with dev net > 0 AND val net > 0; ties break by
higher dev net, then lexical config_id; else NONE. S1/CASH never
advance (recorded as reference only). Ledger nets come from each
cell's full report.json (closing_equity - opening_equity); all
openings must agree or the comparison is BLOCKED (exit 3).

Inputs: one single-cell comparison.json per (config, split); each
file's lone cell key is "<armset>|<split>".
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_cell(path: str) -> tuple[str, dict, dict]:
    """Return (armset, cell-metrics, full-run-report) for one file."""
    comparison = json.loads(Path(path).read_text(encoding="utf-8"))
    cells = comparison.get("cells", {})
    if len(cells) != 1:
        raise ValueError(f"{path}: expected exactly 1 cell, "
                         f"found {len(cells)}")
    (key, metrics), = cells.items()
    armset, _, _split = key.partition("|")
    report_path = Path(metrics["run_dir"]) / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return armset, metrics, report


def select(dev_files: list[str], val_files: list[str],
           registry_path: str) -> dict:
    registry = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    arm_to_config = {c["arm"]: c["config_id"]
                     for c in registry["configs"]}
    role_of = {c["config_id"]: c["role"] for c in registry["configs"]}
    nets: dict[str, dict[str, float]] = {}
    openings: set[float] = set()
    for split, files in (("dev", dev_files), ("val", val_files)):
        for path in files:
            armset, _metrics, report = load_cell(path)
            if armset not in arm_to_config:
                raise ValueError(f"{path}: armset {armset!r} not in registry")
            config_id = arm_to_config[armset]
            net = float(report["closing_equity"]) - float(
                report["opening_equity"])
            openings.add(float(report["opening_equity"]))
            nets.setdefault(config_id, {})[split] = net
    if len(openings) != 1:
        raise ValueError(f"mixed opening equities across cells: "
                         f"{sorted(openings)}")
    candidates = sorted(c for c, r in role_of.items() if r == "candidate")
    missing = [c for c in candidates
               if set(nets.get(c, {})) != {"dev", "val"}]
    if missing:
        raise ValueError(f"candidates missing a split: {missing}")
    qualified = [c for c in candidates
                 if nets[c]["dev"] > 0 and nets[c]["val"] > 0]
    qualified.sort(key=lambda c: (-nets[c]["val"], -nets[c]["dev"], c))
    winner = qualified[0] if qualified else None
    return {
        "rule": "X1.md section 10",
        "opening_equity": next(iter(openings)),
        "nets": {c: nets[c] for c in sorted(nets)},
        "candidates": candidates,
        "qualified": qualified,
        "winner": winner,
        "verdict": ("ADVANCE " + winner) if winner else "NONE "
                   "(RESEARCH UNRESOLVED unless a candidate qualifies)",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--registry", required=True)
    parser.add_argument("--dev", nargs="+", required=True,
                        help="dev comparison.json files (one cell each)")
    parser.add_argument("--val", nargs="+", required=True,
                        help="val comparison.json files (one cell each)")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        result = select(args.dev, args.val, args.registry)
    except ValueError as exc:
        print(f"BLOCKED: {exc}")
        return 3
    result["inputs"] = {"registry": args.registry, "dev": args.dev,
                        "val": args.val}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"selection: {result['verdict']} "
          f"qualified={result['qualified']} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
