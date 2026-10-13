"""Hard runtime limiter: no continuous job may exceed its budget (30-min plan §2).

Usage:
    run_budget.py --budget-s 1500 --checkpoint-dir DIR --report-out R.json
        [--heartbeat-s 60] [--term-grace-s 10] -- <command...>

Contract:
- Absolute monotonic deadline enforced OUTSIDE the timed worker
  (this parent). Setup, retries, subprocesses and cleanup are inside it.
- The child runs in its own process group; at the deadline the whole
  process TREE gets SIGTERM, then SIGKILL after --term-grace-s.
- Kill identity is the birth registry: every descendant PID ever observed
  under the child (plus a fresh snapshot at kill time). Only those PIDs
  (and the child itself) are ever signaled; unrelated processes are never
  touched.
- On Linux the wrapper becomes a child subreaper, so orphaned descendants
  reparent to it and stay visible. Other platforms (macOS) have no
  subreaper: enforcement there is best-effort and the report says so.
- The child tree NEVER inherits the caller's stdout/stderr: output flows
  through a wrapper-owned relay. An escaped descendant therefore cannot
  block a capturing caller past wrapper exit (bounded drain). Note: the
  child's stdout/stderr are pipes, never a tty, even when the wrapper's
  own output is a terminal.
- Children inherit the deadline via CRYPTOBOT_DEADLINE_MONO (and the
  budget via CRYPTOBOT_BUDGET_S). A nested run_budget takes the MIN of
  its own budget and the inherited deadline: a restart must not reset it.
- A job reaching its deadline checkpoints and exits INCOMPLETE_BUDGET
  (exit 124), never PASS. Success/failure of the child passes through.
- Enforcement is verified, not assumed: after the kill the wrapper
  re-sweeps known PIDs. If enumeration ever failed during the kill phase
  or known survivors remain, the report carries enforcement=UNVERIFIED
  with the reason (fail-closed). Exit stays 124 either way.
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
import threading
import time
from pathlib import Path

EXIT_INCOMPLETE = 124
ENV_DEADLINE = "CRYPTOBOT_DEADLINE_MONO"
ENV_BUDGET = "CRYPTOBOT_BUDGET_S"
SCAN_TICK_S = 0.25  # birth-registry refresh while waiting.
DRAIN_S = 2.0  # bounded relay drain after the child exits.
RELAY_CHUNK = 65536


def _write_checkpoint(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(record, indent=1) + "\n")
    os.replace(tmp, path)


def _try_subreaper() -> bool:
    """Become a child subreaper on Linux (best-effort, never fatal).

    Orphaned descendants then reparent to this wrapper instead of init,
    so the ppid walk keeps seeing them. Returns True only when the kernel
    accepted the request. No-op on platforms without prctl/Linux.
    """
    if sys.platform != "linux":
        return False
    try:
        import ctypes
        PR_SET_CHILD_SUBREAPER = 36
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        return libc.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) == 0
    except Exception:
        return False


def _scan_descendants(root: int) -> tuple[set[int], bool]:
    # All live PIDs under root. Returns (pids, ok): ok=False when the
    # enumeration itself failed, so callers fail closed instead of
    # mistaking "no data" for "no descendants".
    try:
        proc = subprocess.run(["ps", "-eo", "pid,ppid"], capture_output=True,
                              text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return set(), False
    # A nonzero exit or empty output is failed enumeration, NOT an empty
    # tree: parsing it as "no descendants" would fail open.
    if proc.returncode != 0 or not proc.stdout.strip():
        return set(), False
    out = proc.stdout
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
    return seen, True


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else: treat as alive.
    return True


def _kill_targets(pgid: int, pids: set[int], sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass
    for pid in pids:
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass


class _Relay:
    """Wrapper-owned stdout/stderr relay for the child tree.

    The child writes to relay pipes; daemon forwarder threads copy bytes
    to the wrapper's own stdout/stderr. The caller's fds are never
    inherited downstream, so no descendant — escaped or lingering — can
    hold the caller's pipe open past wrapper exit. Drain is bounded:
    lingering writers delay wrapper exit by at most DRAIN_S.
    """

    def __init__(self) -> None:
        self.out_r, self.out_w = os.pipe()
        self.err_r, self.err_w = os.pipe()
        self._threads: list[threading.Thread] = []

    def _forward(self, fd: int, stream) -> None:
        try:
            while True:
                chunk = os.read(fd, RELAY_CHUNK)
                if not chunk:
                    return
                try:
                    stream.write(chunk)
                    stream.flush()
                except (BrokenPipeError, OSError, ValueError):
                    return  # caller went away; keep enforcing, drop output.
        except OSError:
            return
        finally:
            try:
                os.close(fd)
            except OSError:
                pass

    def start(self) -> None:
        for fd, stream in ((self.out_r, sys.stdout.buffer),
                           (self.err_r, sys.stderr.buffer)):
            t = threading.Thread(target=self._forward, args=(fd, stream),
                                 daemon=True)
            t.start()
            self._threads.append(t)

    def child_fds(self) -> tuple[int, int]:
        return self.out_w, self.err_w

    def close_parent_write_ends(self) -> None:
        for fd in (self.out_w, self.err_w):
            try:
                os.close(fd)
            except OSError:
                pass

    def drain(self, timeout: float = DRAIN_S) -> None:
        deadline = time.monotonic() + max(0.0, timeout)
        for t in self._threads:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            t.join(timeout=remaining)


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

    subreaper = _try_subreaper()

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
    relay = _Relay()
    relay.start()
    out_w, err_w = relay.child_fds()
    proc = subprocess.Popen(child_cmd, env=env, start_new_session=True,
                            stdout=out_w, stderr=err_w)
    relay.close_parent_write_ends()  # parent must not hold the write ends.
    pgid = proc.pid  # start_new_session => child is its own group leader.
    last_beat = 0.0
    registry: set[int] = set()  # every descendant PID ever observed.
    enum_healthy = True
    timed_out = False
    while True:
        try:
            rc = proc.wait(timeout=SCAN_TICK_S)
        except subprocess.TimeoutExpired:
            rc = None
        now = time.monotonic()
        if rc is None:  # child still running: refresh the birth registry.
            seen, ok = _scan_descendants(proc.pid)
            if not ok:
                enum_healthy = False
            registry |= seen
        if now - last_beat >= min(args.heartbeat_s, 60.0):
            last_beat = now
            print(f"[run_budget] elapsed={now - start_mono:.1f}s "
                  f"remaining={max(0.0, deadline - now):.1f}s "
                  f"checkpoint={ckpt_path} pid={proc.pid}",
                  file=sys.stderr, flush=True)
        if rc is not None:
            relay.drain()
            elapsed = time.monotonic() - start_mono
            record = {"status": "CHILD_EXIT", "child_rc": rc,
                      "elapsed_s": round(elapsed, 3),
                      "budget_s": args.budget_s, "command": child_cmd,
                      "subreaper": subreaper}
            _write_checkpoint(ckpt_path, record)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(record, indent=1) + "\n")
            return rc
        if now >= deadline:
            timed_out = True
            break

    # Deadline: terminate the registry + fresh snapshot, then kill survivors.
    # Re-sweep through the grace window: late forks must not escape.
    assert timed_out
    kill_enum_ok = True

    def sweep(sig: int) -> set[int]:
        nonlocal kill_enum_ok
        seen, ok = _scan_descendants(proc.pid)
        if not ok:
            kill_enum_ok = False
        registry.update(seen)
        targets = set(registry) | {proc.pid}
        _kill_targets(pgid, targets, sig)
        return targets

    sweep(signal.SIGTERM)
    grace_until = time.monotonic() + max(0.0, args.term_grace_s)
    while time.monotonic() < grace_until:
        seen, ok = _scan_descendants(proc.pid)
        if not ok:
            kill_enum_ok = False
        registry.update(seen)
        if proc.poll() is not None and not seen:
            break
        time.sleep(0.1)
        sweep(signal.SIGTERM)
    sweep(signal.SIGKILL)
    try:
        proc.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        pass
    relay.drain()
    # Verification sweep: prove known descendants stopped, fail closed.
    final_seen, final_ok = _scan_descendants(proc.pid)
    if not final_ok:
        kill_enum_ok = False
    survivors = sorted(p for p in (set(final_seen) | registry)
                       if _alive(p))
    if kill_enum_ok and enum_healthy and not survivors:
        enforcement, enforcement_detail = "verified", (
            f"all {len(registry)} known descendants dead; "
            f"subreaper={'on' if subreaper else 'off'}")
    else:
        reasons = []
        if not enum_healthy or not kill_enum_ok:
            reasons.append("descendant enumeration failed; kill set "
                           "incomplete")
        if survivors:
            reasons.append(f"{len(survivors)} known survivors: "
                           f"{survivors[:10]}")
        enforcement, enforcement_detail = "UNVERIFIED", "; ".join(reasons)
    elapsed = time.monotonic() - start_mono
    record = {"status": "INCOMPLETE_BUDGET", "child_rc": proc.poll(),
              "elapsed_s": round(elapsed, 3), "budget_s": args.budget_s,
              "command": child_cmd,
              "note": "deadline reached; partial work is incomplete, never PASS",
              "enforcement": enforcement,
              "enforcement_detail": enforcement_detail,
              "subreaper": subreaper,
              "platform_note": None if subreaper else
              "no child subreaper on this OS: daemonizing children that "
              "reparent before any scan are undetectable; Linux enforces "
              "fully, this platform is best-effort plus verified reporting"}
    _write_checkpoint(ckpt_path, record)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(record, indent=1) + "\n")
    print(f"[run_budget] INCOMPLETE_BUDGET after {elapsed:.1f}s "
          f"enforcement={enforcement}", file=sys.stderr)
    return EXIT_INCOMPLETE


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
