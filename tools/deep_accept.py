"""Deep-research single acceptance command (manager-owned).

Gates (each PASS / BLOCKED / FAIL on the integrated tree):
  A1  run_budget enforce-or-refuse + 13-row lifecycle proof (W1 evidence).
  A2  sandbox drill: one offline command, interrupt/resume, reconciled flat
      or explicit failure, BLOCKED-never-PASS (W2 evidence).
  A3  frozen X1 round-1 on frozen splits, untouched EVAL reserved, economics
      reconciled (W3/W4 evidence).

Overall verdict: PASS only when A1+A2+A3 PASS. Any FAIL -> FAIL.
Any BLOCKED (and no FAIL) -> BLOCKED. Synthetic profits never qualify.

Completion filings (written by workers, read here):
  coord/outbox/DEEP-W1-D1.done.json, DEEP-W1-D2.done.json,
  DEEP-W2-D3.done.json, DEEP-W3-D5.done.json, DEEP-W4-D4.done.json
Each filing: {"sha": "...", "commands": [{"cmd": [...], "cwd": null,
"expect_rc": 0, "artifacts": ["path", ...], "note": "..."}], ...}.
Every cited command is RE-RUN here (observed output, never quoted claims).

Usage:
    python tools/deep_accept.py --suite full --report-out R.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUTBOX = ROOT / "coord" / "outbox"
CMD_TIMEOUT_S = 900

GATE_FILINGS = {
    "A1": ["DEEP-W1-D1.done.json", "DEEP-W1-D2.done.json"],
    "A2": ["DEEP-W2-D3.done.json"],
    "A3": ["DEEP-W3-D5.done.json", "DEEP-W4-D4.done.json"],
}


def _rerun(cmd: list[str], cwd: str | None) -> dict:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=CMD_TIMEOUT_S,
                              cwd=cwd or str(ROOT))
    except subprocess.TimeoutExpired as exc:
        return {"rc": None, "timeout": True,
                "tail": (exc.stdout or "")[-2000:] + (exc.stderr or "")[-2000:]}
    tail = (proc.stdout[-2000:] if proc.stdout else "") + \
        (proc.stderr[-2000:] if proc.stderr else "")
    return {"rc": proc.returncode, "timeout": False, "tail": tail}


def _check_filing(name: str) -> dict:
    path = OUTBOX / name
    if not path.exists():
        return {"filing": name, "verdict": "BLOCKED",
                "detail": "completion filing missing"}
    try:
        filing = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        return {"filing": name, "verdict": "FAIL",
                "detail": f"unreadable filing: {exc}"}
    results = []
    verdict = "PASS"
    for i, item in enumerate(filing.get("commands", [])):
        obs = _rerun(item["cmd"], item.get("cwd"))
        ok = (not obs["timeout"]) and obs["rc"] == item.get("expect_rc", 0)
        missing = [a for a in item.get("artifacts", [])
                   if not (ROOT / a).exists()
                   or (ROOT / a).stat().st_size == 0]
        if missing:
            ok = False
        if not ok:
            verdict = "FAIL"
        results.append({"note": item.get("note", f"cmd{i}"),
                        "observed_rc": obs["rc"], "timeout": obs["timeout"],
                        "missing_artifacts": missing, "tail": obs["tail"]})
    if not results:
        verdict = "BLOCKED"
    return {"filing": name, "sha": filing.get("sha"), "verdict": verdict,
            "reruns": results}


def _check_gate(gate: str) -> dict:
    filings = [_check_filing(n) for n in GATE_FILINGS[gate]]
    verdicts = [f["verdict"] for f in filings]
    verdict = ("FAIL" if "FAIL" in verdicts else
               "BLOCKED" if "BLOCKED" in verdicts else "PASS")
    return {"gate": gate, "verdict": verdict, "filings": filings}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Deep-research acceptance gate")
    ap.add_argument("--suite", default="full",
                    choices=("full", "a1", "a2", "a3"))
    ap.add_argument("--report-out", required=True)
    args = ap.parse_args(argv)
    wanted = (("A1", "A2", "A3") if args.suite == "full"
              else (args.suite.upper(),))
    results = [_check_gate(g) for g in wanted]
    verdicts = [r["verdict"] for r in results]
    overall = ("FAIL" if "FAIL" in verdicts else
               "BLOCKED" if "BLOCKED" in verdicts else "PASS")
    report = {"overall": overall, "gates": results}
    Path(args.report_out).write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report, indent=1))
    return {"PASS": 0, "BLOCKED": 2, "FAIL": 1}[overall]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
