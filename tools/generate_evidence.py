"""Status-evidence gate (manager-owned).

Runs required checks (pytest, M1 slice) plus optional diagnostics, prints a
Markdown report, optionally writes a machine-readable JSON result, and exits
nonzero when any REQUIRED check fails. Optional-check failures are reported
but never fail the gate. Simulated inputs stay labelled synthetic; nothing
here claims profitability.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
VENV_PY = ROOT / ".venv" / "bin" / "python"


class Check(NamedTuple):
    name: str
    cmd: list[str]
    required: bool


def run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=300)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def collect(py: str) -> list[tuple[Check, int, str]]:
    checks = [
        Check("pytest", [py, "-m", "pytest", "-q"], True),
        Check("m1-slice", [py, "tools/m1_vertical_slice.py",
                            "--out", "/tmp/ev_m1.json"], True),
        Check("git-log", ["git", "log", "--oneline", "-n", "5"], False),
        Check("git-head", ["git", "rev-parse", "HEAD"], False),
    ]
    return [(check, *run(check.cmd, ROOT)) for check in checks]


def main() -> int:
    parser = argparse.ArgumentParser(description="Status-evidence gate")
    parser.add_argument("--out", default="",
                        help="Write Markdown report to PATH (default: stdout only)")
    parser.add_argument("--json-out", default="",
                        help="Write machine-readable result JSON to PATH")
    parser.add_argument("--baseline", default="",
                        help="Baseline SHA recorded in the JSON result")
    args = parser.parse_args()

    py = str(VENV_PY if VENV_PY.exists() else sys.executable)
    results = collect(py)
    failed_required = [name for check, code, _ in
                       ((c, e, o) for c, e, o in results)
                       if check.required and code != 0
                       for name in [check.name]]
    tasks = json.loads((ROOT / "coord" / "tasks.json").read_text())
    workers = json.loads((ROOT / "coord" / "workers.json").read_text())

    by_name = {check.name: (code, out) for check, code, out in results}
    pytest_code, pytest_out = by_name["pytest"]
    m1_code, _m1_out = by_name["m1-slice"]
    git_code, git_out = by_name["git-log"]
    head_code, head_out = by_name["git-head"]

    lines = [
        f"# Status evidence ({datetime.now(timezone.utc).isoformat(timespec='seconds')})",
        "",
        f"- gate: {'FAIL' if failed_required else 'PASS'}"
        + (f" (failed required: {', '.join(failed_required)})" if failed_required else ""),
        f"- pytest exit={pytest_code} [required]; tail: `{pytest_out.splitlines()[-1] if pytest_out else 'empty'}`",
        f"- M1 slice exit={m1_code} [required] (synthetic)",
        "- git log [optional]:",
    ]
    lines += [f"  - {line}" for line in (git_out.splitlines() if git_code == 0 else ["unavailable"])]
    lines += ["- tasks:"]
    for tid, task in tasks.get("tasks", {}).items():
        lines.append(f"  - {tid}: {task.get('state')} ({task.get('owner_session')})")
    lines += ["- workers:"]
    for name, worker in workers.get("workers", {}).items():
        lines.append(f"  - {name}: {worker.get('status')}")
    report = "\n".join(lines) + "\n"
    if args.out:
        Path(args.out).write_text(report)
    print(report)

    if args.json_out:
        payload = {
            "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "baseline_sha": args.baseline or None,
            "head_sha": head_out.splitlines()[0] if head_code == 0 and head_out else None,
            "gate": "FAIL" if failed_required else "PASS",
            "failed_required": failed_required,
            "checks": [
                {"name": check.name, "cmd": check.cmd, "required": check.required,
                 "exit": code, "output_tail": out.splitlines()[-3:] if out else []}
                for check, code, out in results
            ],
        }
        Path(args.json_out).write_text(json.dumps(payload, indent=1) + "\n")

    return 1 if failed_required else 0


if __name__ == "__main__":
    raise SystemExit(main())
