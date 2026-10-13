"""Adversarial nested-deadline battery for tools/run_budget.py (Worker 5, CORR-VERIFY).

Seconds-scale. Each case asserts REQUIRED behavior: a red test is a genuine
finding about the hard runtime rule, not a flaky probe. Teardown reaps only
verified own-descendants (cmdline token match); unrelated PIDs are never killed.
"""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

WRAPPER = [sys.executable, "tools/run_budget.py"]
TOKEN = "w5corr-deadline-battery"


def _run(budget_s, grace_s, child_cmd, ckpt_dir, report, cwd):
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    cmd = WRAPPER + ["--budget-s", str(budget_s), "--checkpoint-dir",
                     str(ckpt_dir), "--report-out", str(report),
                     "--term-grace-s", str(grace_s), "--", *child_cmd]
    t0 = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd,
                          timeout=120)
    return proc, time.monotonic() - t0


def _reap_verified(pidfile: Path, token: str) -> str:
    """SIGKILL one recorded PID only if its cmdline still carries our token."""
    try:
        pid = int(pidfile.read_text().strip())
    except (OSError, ValueError):
        return "no-pidfile"
    try:
        out = subprocess.run(["ps", "-o", "command=", "-p", str(pid)],
                             capture_output=True, text=True,
                             timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return "ps-failed"
    if token not in out:
        return "not-ours-or-dead"
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        return "already-dead"
    time.sleep(0.3)
    try:
        os.kill(pid, 0)
        return "STILL-ALIVE"
    except ProcessLookupError:
        return "reaped"
    except PermissionError:
        return "denied"


@pytest.fixture
def stray_reaper(tmp_path):
    pids = []

    def track(pidfile: Path):
        pids.append(pidfile)
        return pidfile

    yield track
    for pf in pids:
        _reap_verified(pf, TOKEN)


def _repo_root():
    return Path(__file__).resolve().parents[2]


def test_handoff_nested_case_repeated(tmp_path):
    """Exact handoff shape (outer 1s / inner 30s / 8s sleeper), 2 iterations.

    Required: caller returns in ~1-2s AND the 8s sleeper never completes
    (marker absent after the full 8s window) AND the wrapper report does not
    understate the observed wall time.
    """
    root = _repo_root()
    for i in range(2):
        marker = tmp_path / f"sleepdone-{i}.txt"
        inner = [sys.executable, "tools/run_budget.py", "--budget-s", "30",
                 "--checkpoint-dir", str(tmp_path / f"inner-{i}"),
                 "--report-out", str(tmp_path / f"inner-{i}.json"), "--",
                 sys.executable, "-c",
                 f"import time; time.sleep(8); "  # {TOKEN}
                 f"open({str(marker)!r}, 'w').write('survived')"]
        proc, wall = _run(1.0, 0.2, inner, tmp_path / f"ckpt-{i}",
                          tmp_path / f"outer-{i}.json", root)
        assert proc.returncode == 124, proc.stderr
        assert wall < 5, f"iteration {i}: caller blocked {wall:.2f}s"
        rep = json.loads((tmp_path / f"outer-{i}.json").read_text())
        assert rep["status"] == "INCOMPLETE_BUDGET"
        assert wall - rep["elapsed_s"] < 2.0, (
            f"iteration {i}: report elapsed={rep['elapsed_s']} understates "
            f"observed wall={wall:.2f}")
        # Wait out the remainder of the 8s window; the sleeper must be dead.
        time.sleep(max(0.0, 8.5 - wall))
        assert not marker.exists(), (
            f"iteration {i}: 8s sleeper survived the outer deadline")


def test_sigterm_ignorer_gets_sigkill(tmp_path, stray_reaper):
    """A child ignoring SIGTERM must still die (SIGKILL escalation)."""
    root = _repo_root()
    marker = tmp_path / "ignorer-done.txt"
    pidfile = stray_reaper(tmp_path / "ignorer.pid")
    script = (f"import signal, sys, time; open({str(pidfile)!r}, 'w').write(str(__import__('os').getpid())); "
              "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
              f"time.sleep(30); open({str(marker)!r}, 'w').write('survived')  # {TOKEN}")
    proc, wall = _run(2.0, 1.0, [sys.executable, "-c", script],
                      tmp_path / "ckpt", tmp_path / "rep.json", root)
    assert proc.returncode == 124, proc.stderr
    assert wall < 2.0 + 1.0 + 5, f"escalation too slow: {wall:.2f}s"
    time.sleep(3)
    assert not marker.exists(), "SIGTERM-ignoring child survived SIGKILL"


def test_daemon_reparent_escape(tmp_path, stray_reaper):
    """A grandchild reparented to init BEFORE the deadline must still stop.

    Double-fork + setsid detaches the daemon from the victim process group
    and from any ppid walk rooted at the wrapper's child. If it survives,
    the wrapper cannot enforce its deadline on daemonizing children.
    """
    root = _repo_root()
    marker = tmp_path / "daemon-done.txt"
    pidfile = stray_reaper(tmp_path / "daemon.pid")
    # Wrapper-direct child: fork a middle process, then sleep (to be killed).
    # Middle: setsid, fork the daemon, exit. Daemon: reparented, sleeps 6s.
    child = (
        "import os, sys, time\n"
        f"MARK = {str(marker)!r}\n"
        f"PIDF = {str(pidfile)!r}\n"
        f"# {TOKEN}\n"
        "mid = os.fork()\n"
        "if mid > 0:\n"
        "    time.sleep(60)\n"
        "    sys.exit(0)\n"
        "os.setsid()\n"
        "d = os.fork()\n"
        "if d > 0:\n"
        "    os._exit(0)\n"
        "open(PIDF, 'w').write(str(os.getpid()))\n"
        "time.sleep(6)\n"
        "open(MARK, 'w').write('daemon-survived')\n"
    )
    proc, wall = _run(2.0, 1.0, [sys.executable, "-c", child],
                      tmp_path / "ckpt", tmp_path / "rep.json", root)
    assert proc.returncode == 124, proc.stderr
    time.sleep(max(0.0, 7.0 - wall))
    assert not marker.exists(), (
        "ESCAPE: daemonized grandchild (reparented pre-deadline) survived; "
        "ppid-walk + killpg cannot enforce the deadline on it")


def test_inherited_pipe_blocks_caller_on_escape(tmp_path, stray_reaper):
    """If a descendant escapes holding stdout, the capturing caller blocks.

    The wrapper may exit and report ~2s while the caller (capture_output)
    returns only when the last pipe holder dies. Required: no escape, so
    caller wall must match the report.
    """
    root = _repo_root()
    marker = tmp_path / "pipedaemon-done.txt"
    pidfile = stray_reaper(tmp_path / "pipedaemon.pid")
    child = (
        "import os, sys, time\n"
        f"MARK = {str(marker)!r}\n"
        f"PIDF = {str(pidfile)!r}\n"
        f"# {TOKEN}\n"
        "mid = os.fork()\n"
        "if mid > 0:\n"
        "    time.sleep(60)\n"
        "    sys.exit(0)\n"
        "os.setsid()\n"
        "d = os.fork()\n"
        "if d > 0:\n"
        "    os._exit(0)\n"
        "open(PIDF, 'w').write(str(os.getpid()))\n"
        "time.sleep(8)\n"
        "open(MARK, 'w').write('pipe-survived')\n"
    )
    proc, wall = _run(2.0, 1.0, [sys.executable, "-c", child],
                      tmp_path / "ckpt", tmp_path / "rep.json", root)
    rep = json.loads((tmp_path / "rep.json").read_text())
    time.sleep(max(0.0, 8.5 - wall))
    assert not marker.exists(), "pipe-holding daemon survived"
    assert wall - rep["elapsed_s"] < 2.0, (
        f"caller wall={wall:.2f}s vs report elapsed={rep['elapsed_s']}s: "
        f"wrapper exit/report does not prove descendants stopped")


def test_rapid_fork_during_grace(tmp_path, stray_reaper):
    """Children forked rapidly up to/into the grace window must all die."""
    root = _repo_root()
    piddir = tmp_path / "pids"
    piddir.mkdir()
    child = (
        "import os, subprocess, sys, time\n"
        f"os.environ['W5PIDDIR'] = {str(piddir)!r}\n"
        f"# {TOKEN}\n"
        "n = 0\n"
        "kids = []\n"
        "try:\n"
        "    while True:\n"
        "        p = subprocess.Popen([sys.executable, '-c',\n"
        f"            \"import os, time; open(os.path.join(os.environ['W5PIDDIR'], str(os.getpid())), 'w').write('x'); time.sleep(10)  # {TOKEN}\"])\n"
        "        kids.append(p.pid)\n"
        "        n += 1\n"
        "        time.sleep(0.05)\n"
        "except Exception:\n"
        "    pass\n"
    )
    proc, wall = _run(2.0, 1.0, [sys.executable, "-c", child],
                      tmp_path / "ckpt", tmp_path / "rep.json", root)
    assert proc.returncode == 124, proc.stderr
    time.sleep(2)
    survivors = []
    for pf in piddir.iterdir():
        try:
            pid = int(pf.name)
        except ValueError:
            continue
        try:
            out = subprocess.run(["ps", "-o", "command=", "-p", str(pid)],
                                 capture_output=True, text=True,
                                 timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        if TOKEN in out:
            survivors.append(pid)
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
    assert not survivors, f"{len(survivors)} late-forked grandchildren survived: {survivors[:5]}"


def test_enumeration_failure_must_not_fail_open(tmp_path):
    """If descendant enumeration fails, the wrapper must not claim enforcement.

    With `ps` unavailable, _descendants() returns the empty set and the kill
    degrades to group-kill-only; but every wrapper child starts in its OWN
    session, so grandchildren always escape that path. Required: either the
    descendants still stop, or the report says enforcement is UNVERIFIED.
    Silent INCOMPLETE with escaped descendants is a fail-open.
    """
    import os as _os
    root = _repo_root()
    marker = tmp_path / "nops-done.txt"
    emptybin = tmp_path / "emptybin"
    emptybin.mkdir()
    inner = [sys.executable, "tools/run_budget.py", "--budget-s", "30",
             "--checkpoint-dir", str(tmp_path / "inner"), "--report-out",
             str(tmp_path / "inner.json"), "--", sys.executable, "-c",
             f"import time; time.sleep(8); "  # {TOKEN}
             f"open({str(marker)!r}, 'w').write('survived')"]
    cmd = WRAPPER + ["--budget-s", "1", "--checkpoint-dir",
                     str(tmp_path / "ckpt"), "--report-out",
                     str(tmp_path / "rep.json"), "--term-grace-s", ".2",
                     "--", *inner]
    env = dict(_os.environ)
    env["PATH"] = str(emptybin)  # hide `ps` from the wrapper
    t0 = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=root,
                          timeout=60, env=env)
    wall = time.monotonic() - t0
    rep = json.loads((tmp_path / "rep.json").read_text())
    time.sleep(max(0.0, 8.5 - wall))
    assert not marker.exists(), (
        f"FAIL-OPEN: with enumeration broken, 8s grandchild survived "
        f"(caller wall={wall:.2f}s, report elapsed={rep['elapsed_s']}s); "
        f"nested sessions escape group-kill-only enforcement")


def test_shutdown_race_exit_at_deadline(tmp_path):
    """A child exiting exactly at the deadline: either outcome, never a hang."""
    root = _repo_root()
    outcomes = []
    for i in range(6):
        proc, wall = _run(2.0, 1.0,
                          [sys.executable, "-c",
                           "import time; time.sleep(2.0)"],
                          tmp_path / f"ckpt-{i}", tmp_path / f"rep-{i}.json",
                          root)
        rep = json.loads((tmp_path / f"rep-{i}.json").read_text())
        assert wall < 8, f"iteration {i}: hung {wall:.2f}s"
        assert proc.returncode in (0, 124), proc.stderr
        assert rep["status"] in ("CHILD_EXIT", "INCOMPLETE_BUDGET")
        if proc.returncode == 0:
            assert rep["status"] == "CHILD_EXIT"
        else:
            assert rep["status"] == "INCOMPLETE_BUDGET"
        outcomes.append(rep["status"])
    assert outcomes  # recorded distribution; either verdict is contract-valid.
