"""Deep-research single acceptance command (manager-owned skeleton).

Gates (each PASS / BLOCKED / FAIL on the integrated tree):
  A1  run_budget enforce-or-refuse + 13-row lifecycle proof (W1 evidence).
  A2  sandbox drill: one offline command, interrupt/resume, reconciled flat
      or explicit failure, BLOCKED-never-PASS (W2 evidence).
  A3  frozen X1 round-1 on frozen splits, untouched EVAL reserved, economics
      reconciled (W3/W4 evidence).

Overall verdict: PASS only when A1+A2+A3 PASS. Any FAIL -> FAIL.
Any BLOCKED (and no FAIL) -> BLOCKED. Synthetic profits never qualify.

Usage:
    python tools/deep_accept.py --suite full --report-out R.json
Worker outbox files are read from coord/outbox/DEEP-*.json; every cited
command is RE-RUN here (observed output, never quoted claims).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def check_a1() -> dict:
    """A1: refusal-without-spawn + lifecycle matrix. Implemented at integration."""
    return {"gate": "A1", "verdict": "BLOCKED",
            "detail": "skeleton: W1 evidence not yet integrated"}


def check_a2() -> dict:
    """A2: sandbox drill via tools/audit/sandbox_drill.py. At integration."""
    return {"gate": "A2", "verdict": "BLOCKED",
            "detail": "skeleton: W2 evidence not yet integrated"}


def check_a3() -> dict:
    """A3: X1 round via frozen splits. Implemented at integration."""
    return {"gate": "A3", "verdict": "BLOCKED",
            "detail": "skeleton: W3/W4 evidence not yet integrated"}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Deep-research acceptance gate")
    ap.add_argument("--suite", default="full", choices=("full", "a1", "a2", "a3"))
    ap.add_argument("--report-out", required=True)
    args = ap.parse_args(argv)
    checks = {"a1": check_a1, "a2": check_a2, "a3": check_a3}
    wanted = ("a1", "a2", "a3") if args.suite == "full" else (args.suite,)
    results = [checks[k]() for k in wanted]
    verdicts = [r["verdict"] for r in results]
    overall = ("FAIL" if "FAIL" in verdicts else
               "BLOCKED" if "BLOCKED" in verdicts else "PASS")
    report = {"overall": overall, "gates": results}
    Path(args.report_out).write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report, indent=1))
    return {"PASS": 0, "BLOCKED": 2, "FAIL": 1}[overall]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
