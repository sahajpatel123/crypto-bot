"""Hard runtime limiter: no continuous job may exceed its budget (30-min plan §2).

Usage:
    run_budget.py --budget-s 1500 --checkpoint-dir DIR --report-out R.json
        [--heartbeat-s 60] [--term-grace-s 10] -- <command...>

Contract:
- Absolute monotonic deadline enforced OUTSIDE the timed worker
  (this parent). Setup, retries, subprocesses and cleanup are inside it.
- The child runs in its own process group; at the deadline the whole
  process TREE (group + reparented/nested-session descendants) gets
  SIGTERM, then SIGKILL after --term-grace-s. Nested wrappers create
  new sessions, so group-kill alone cannot reach grandchildren.
- Children inherit the deadline via CRYPTOBOT_DEADLINE_MONO (and the
  budget via CRYPTOBOT_BUDGET_S). A nested run_budget takes the MIN of
  its own budget and the inherited deadline: a restart must not reset it.
- A job reaching its deadline checkpoints and exits INCOMPLETE_BUDGET
  (exit 124), never PASS. Success/failure of the child passes through.
- Heartbeat to stderr at least every --heartbeat-s: elapsed, records
  (unknown here; jobs log their own), checkpoint path, remaining budget.
- No auto-relaunch: this wrapper runs the child exactly once and returns.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

EXIT_INCOMPLETE = 124
ENV_DEADLINE = "CRYPTOBOT_DEADLINE_MONO"
ENV_BUDGET = "CRYPTOBOT_BUDGET_S"


def _write_checkpoint(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(record, indent=1) + "\n")
    os.replace(tmp, path)


def _descendants(root: int) -> set[int]:
    # All live PIDs under root (nested sessions escape killpg; orphans
    # reparent out of the group). `ps` exists on macOS and Linux.
    try:
        out = subprocess.run(["ps", "-eo", "pid,ppid"], capture_output=True,
                             text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    kids: dict[int, list[int]] = {}
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        kids.setdefault(ppid, []).append(pid)
    seen = {root}
    stack = [root]
    while stack:
        for child in kids.get(stack.pop(), []):
            if child not in seen:
                seen.add(child)
                stack.append(child)
    seen.discard(root)
    return seen


def _kill_tree(pgid: int, root: int, sig: int) -> None:
    # Snapshot descendants BEFORE signaling: a child killed first lets
    # grandchildren reparent to init, where no ppid walk can find them.
    # Killing by PID still works after reparenting (PID reuse inside this
    # window is negligible).
    strays = _descendants(root)
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass
    for pid in strays | {root}:
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--budget-s", type=float, required=True)
    ap.add_argument("--checkpoint-dir", required=True)
    ap.add_argument("--report-out", required=True)
    ap.add_argument("--heartbeat-s", type=float, default=60.0)
    ap.add_argument("--term-grace-s", type=float, default=10.0)
    ap.add_argument("command", nargs=argparse.REMAINDER)
    args = ap.parse_args(argv)
    if not args.command or args.command[0] != "--":
        ap.error("command must follow a lone -- separator")
    child_cmd = args.command[1:]
    if not child_cmd:
        ap.error("no command to run")
    if args.budget_s <= 0:
        ap.error("--budget-s must be positive")

    start_mono = time.monotonic()
    deadline = start_mono + args.budget_s
    inherited = os.environ.get(ENV_DEADLINE)
    if inherited:
        try:
            outer = float(inherited)
        except ValueError:
            outer = None
        if outer is not None and outer < deadline:
            deadline = outer  # nested runs never extend the outer deadline.

    ckpt_dir = Path(args.checkpoint_dir)
    ckpt_path = ckpt_dir / "budget_checkpoint.json"
    report_path = Path(args.report_out)
    _write_checkpoint(ckpt_path, {
        "status": "RUNNING", "pid": os.getpid(),
        "budget_s": args.budget_s,
        "deadline_inherited": inherited is not None,
        "started_mono": start_mono, "command": child_cmd,
    })

    env = dict(os.environ)
    env[ENV_DEADLINE] = repr(deadline)
    env[ENV_BUDGET] = repr(max(0.0, deadline - start_mono))
    proc = subprocess.Popen(child_cmd, env=env, start_new_session=True)
    pgid = proc.pid  # start_new_session => child is its own group leader.
    last_beat = 0.0
    timed_out = False
    while True:
        try:
            rc = proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            rc = None
        now = time.monotonic()
        if now - last_beat >= min(args.heartbeat_s, 60.0):
            last_beat = now
            print(f"[run_budget] elapsed={now - start_mono:.1f}s "
                  f"remaining={max(0.0, deadline - now):.1f}s "
                  f"checkpoint={ckpt_path} pid={proc.pid}",
                  file=sys.stderr, flush=True)
        if rc is not None:
            elapsed = now - start_mono
            record = {"status": "CHILD_EXIT", "child_rc": rc,
                      "elapsed_s": round(elapsed, 3),
                      "budget_s": args.budget_s, "command": child_cmd}
            _write_checkpoint(ckpt_path, record)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(record, indent=1) + "\n")
            return rc
        if now >= deadline:
            timed_out = True
            break

    # Deadline: terminate the whole tree, then kill survivors.
    # Re-sweep each beat: late forks must not escape the first snapshot.
    _kill_tree(pgid, proc.pid, signal.SIGTERM)
    grace_until = time.monotonic() + max(0.0, args.term_grace_s)
    while time.monotonic() < grace_until:
        if proc.poll() is not None and not _descendants(proc.pid):
            break
        time.sleep(0.1)
        _kill_tree(pgid, proc.pid, signal.SIGTERM)
    _kill_tree(pgid, proc.pid, signal.SIGKILL)
    try:
        proc.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        pass
    elapsed = time.monotonic() - start_mono
    record = {"status": "INCOMPLETE_BUDGET", "child_rc": proc.poll(),
              "elapsed_s": round(elapsed, 3), "budget_s": args.budget_s,
              "command": child_cmd,
              "note": "deadline reached; partial work is incomplete, never PASS"}
    _write_checkpoint(ckpt_path, record)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(record, indent=1) + "\n")
    print(f"[run_budget] INCOMPLETE_BUDGET after {elapsed:.1f}s", file=sys.stderr)
    return EXIT_INCOMPLETE


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
