"""Generate a reproducible status-evidence report (manager-owned).

Collects only observed facts: pytest outcome, M1 slice report, task board,
worker status, and recent git history. Prints Markdown to stdout.
Simulated inputs stay labelled synthetic; nothing here claims profitability.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_PY = ROOT / ".venv" / "bin" / "python"


def run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=300)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Evidence report generator")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    py = str(VENV_PY if VENV_PY.exists() else sys.executable)
    pytest_code, pytest_out = run([py, "-m", "pytest", "-q"], ROOT)
    m1_code, m1_out = run([py, "tools/m1_vertical_slice.py", "--out", "/tmp/ev_m1.json"], ROOT)
    git_code, git_out = run(["git", "log", "--oneline", "-n", "5"], ROOT)
    tasks = json.loads((ROOT / "coord" / "tasks.json").read_text())
    workers = json.loads((ROOT / "coord" / "workers.json").read_text())

    lines = [
        f"# Status evidence ({datetime.now(timezone.utc).isoformat(timespec='seconds')})",
        "",
        f"- pytest exit={pytest_code}; tail: `{pytest_out.splitlines()[-1] if pytest_out else 'empty'}`",
        f"- M1 slice exit={m1_code} (synthetic)",
        "- git log:",
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
