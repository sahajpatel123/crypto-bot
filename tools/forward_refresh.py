"""Daily public-data refresh into the FORWARD partition.

Keeps only filename dates after 2026-10-17. Holdout jobs are dropped
before any download. This script does not open a zip and does not
decode the vault.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import vision_pull  # noqa: E402


def forward_only(plan: dict) -> dict:
    jobs = [j for j in plan.get("jobs", []) if j.get("split") == "forward"]
    kept = dict(plan)
    kept["jobs"] = jobs
    kept["dropped_non_forward"] = len(plan.get("jobs", [])) - len(jobs)
    return kept


def main() -> int:
    symbols = ROOT / "data" / "lake" / "forward-symbols.txt"
    symbols.parent.mkdir(parents=True, exist_ok=True)
    if not symbols.exists():
        symbols.write_text("BTCUSDT\nETHUSDT\n")
    plan_path = ROOT / "data" / "lake" / "plan-forward.json"
    # Listing is the existing planner. The filter below is what keeps
    # holdout sealed: non-forward jobs never reach pull_job.
    args = vision_pull.build_parser().parse_args([
        "plan",
        "--datasets", "klines", "markPriceKlines", "premiumIndexKlines",
        "fundingRate", "metrics", "spot",
        "--intervals", "klines:1d", "markPriceKlines:1d",
        "premiumIndexKlines:1d", "spot:1d",
        "--symbols-file", str(symbols),
        "--workers", "8",
        "--out", str(plan_path),
    ])
    code = args.func(args)
    if code != 0:
        return code
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    kept = forward_only(plan)
    kept_path = ROOT / "data" / "lake" / "plan-forward-only.json"
    kept_path.write_text(json.dumps(kept))
    print(json.dumps({
        "planned": len(plan.get("jobs", [])),
        "forward": len(kept["jobs"]),
        "dropped_non_forward": kept["dropped_non_forward"],
    }, sort_keys=True))
    pull = vision_pull.build_parser().parse_args([
        "pull",
        "--plan", str(kept_path),
        "--dev-dir", str(ROOT / "data" / "lake" / "raw"),
        "--holdout-dir", str(ROOT / "data" / "lake" / "holdout_raw"),
        "--forward-dir", str(ROOT / "data" / "lake" / "forward"),
        "--workers", "4",
        "--disk-floor-gb", "15",
        "--state", str(ROOT / "data" / "lake" / "pull-forward.json"),
    ])
    return pull.func(pull)


if __name__ == "__main__":
    raise SystemExit(main())
