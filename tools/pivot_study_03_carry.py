"""STUDY-03: P2 funding-carry accounting (read-only, manager-owned).

Preregistered in reports/pivot/PILOT-SCORING-PREREG.md BEFORE any pilot
scoring. Sums OBSERVED funding settlements (funding.jsonl sidecar with
provenance) per pilot day in bps of notional for a 1x perp-long held
through settlement. No hedge leg exists in pilot channels: full
delta-neutral carry is NOT scored — funding-only descriptive, reported
against P2's 40bps min_target with that caveat. PILOT-SIGNAL impossible
by construction (incomplete strategy).

Exit 0 results written; 2 input/contract error.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

EXIT_BLOCKED = 2
TARGET_BPS = 40.0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="STUDY-03 P2 funding accounting (read-only)")
    parser.add_argument("--capture", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        capture = Path(args.capture)
        fund_path = capture / "funding.jsonl"
        if not fund_path.exists():
            raise ValueError(f"{capture}: funding.jsonl missing")
        manifest = json.loads((capture / "manifest.json").read_text())
        total_bps = 0.0
        n = 0
        no_source = 0
        for line in fund_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            rate = float(row["funding_rate"])
            total_bps += rate * 1e4
            n += 1
            if not row.get("source"):
                no_source += 1
        if no_source:
            raise ValueError(f"{no_source} settlements lack provenance")
    except (ValueError, KeyError) as exc:
        print(f"BLOCKED: {exc}")
        return EXIT_BLOCKED
    result = {"capture": str(capture), "date": manifest.get("date"),
              "settlements": n, "funding_bps": round(total_bps, 3),
              "target_bps": TARGET_BPS,
              "target_ratio": round(total_bps / TARGET_BPS, 4) if n else None,
              "caveat": "funding leg only; hedge leg unobservable in pilot"}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"STUDY-03 -> {args.out}: n={n} funding={total_bps:.3f}bps "
          f"(target {TARGET_BPS}bps)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
