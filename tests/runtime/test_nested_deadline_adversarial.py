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
DRAIN_ALLOW = 5.0  # relay drain bound + generous scheduling slack.


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
        assert rep.get("enforcement") == "verified", (
            f"iteration {i}: healthy nested kill must verify: {rep}")
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
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert rep.get("enforcement") == "verified", rep


def _daemon_child(marker: Path, pidfile: Path, sleep_s: float) -> list[str]:
    # Wrapper-direct child: fork a middle process, then sleep (to be killed).
    # Middle: setsid, fork the daemon, exit. Daemon: reparented to init.
    script = (
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
        f"time.sleep({sleep_s})\n"
        "open(MARK, 'w').write('daemon-survived')\n"
    )
    return [sys.executable, "-c", script]


def test_daemon_reparent_escape(tmp_path, stray_reaper):
    """A grandchild reparented to init BEFORE the deadline must still stop.

    Double-fork + setsid detaches the daemon from the victim process group
    and from any ppid walk rooted at the wrapper's child. Where the OS
    provides a child subreaper (Linux) the daemon must die. Where it does
    not (macOS), the wrapper must say so honestly in the report and the
    caller must still return promptly (relay containment).
    """
    root = _repo_root()
    marker = tmp_path / "daemon-done.txt"
    pidfile = stray_reaper(tmp_path / "daemon.pid")
    proc, wall = _run(2.0, 1.0,
                      _daemon_child(marker, pidfile, 10.0),
                      tmp_path / "ckpt", tmp_path / "rep.json", root)
    assert proc.returncode == 124, proc.stderr
    rep = json.loads((tmp_path / "rep.json").read_text())
    if rep.get("subreaper"):
        time.sleep(max(0.0, 10.5 - wall))
        assert not marker.exists(), (
            "ESCAPE on a subreaper platform: daemonized grandchild "
            "survived; orphan reparenting is not contained")
    else:
        # Honest degradation: no silent claim of enforcement, no hang.
        # Success ~4.3s (2 budget + TERM + 2s bounded drain); a caller
        # pipe hold would block the full 10s daemon lifetime.
        assert "subreaper" in (rep.get("platform_note") or ""), (
            f"missing no-subreaper honesty note: {rep}")
        assert wall < 6.5, f"caller blocked {wall:.2f}s despite relay"
        assert rep.get("enforcement") in ("verified", "UNVERIFIED"), rep


def test_inherited_pipe_blocks_caller_on_escape(tmp_path, stray_reaper):
    """REGRESSION: the child tree must never inherit the caller's pipes.

    The wrapper-owned relay carries child output; an escaped or lingering
    descendant therefore cannot hold the capturing caller's pipe open.
    Required on every platform: caller wall matches the report even when
    a daemon outlives the wrapper (the daemon itself is contained only
    where the OS offers a subreaper; see test_daemon_reparent_escape).
    """
    root = _repo_root()
    marker = tmp_path / "pipedaemon-done.txt"
    pidfile = stray_reaper(tmp_path / "pipedaemon.pid")
    proc, wall = _run(2.0, 1.0,
                      _daemon_child(marker, pidfile, 8.0),
                      tmp_path / "ckpt", tmp_path / "rep.json", root)
    assert proc.returncode == 124, proc.stderr
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert wall - rep["elapsed_s"] < 2.0, (
        f"caller wall={wall:.2f}s vs report elapsed={rep['elapsed_s']}s: "
        f"a descendant is holding the caller's pipe open past wrapper exit")
    # Success is ~2s budget + fast TERM + 2s bounded drain; failure is ~8s.
    assert wall < 6.5, f"caller blocked {wall:.2f}s"


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
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert rep.get("enforcement") == "verified", rep
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

    With `ps` unavailable for the whole run, no kill set can be built and
    grandchildren escape (each wrapper child starts in its OWN session, so
    group-kill-only cannot reach them). Required: the report carries
    enforcement=UNVERIFIED naming enumeration failure, rc stays 124, and
    the caller still returns promptly (relay containment, not a pipe hang).
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
    assert proc.returncode == 124, proc.stderr
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert rep["status"] == "INCOMPLETE_BUDGET"
    assert rep.get("enforcement") == "UNVERIFIED", (
        f"fail-open: enumeration broken yet report claims "
        f"{rep.get('enforcement')}: {rep}")
    assert "enumeration" in (rep.get("enforcement_detail") or ""), rep
    assert wall < 6.5, f"caller blocked {wall:.2f}s despite relay"


def test_registry_kills_when_ps_dies_midrun(tmp_path):
    """REGRESSION: a birth registry built during life covers kill-time failure.

    A flaky `ps` works for the first scans (registry learns the sleeper)
    then fails through the kill phase. Required: the registry kill set
    still stops the tree (marker absent), the caller returns on time, and
    the report is honest (UNVERIFIED: enumeration failed during the kill).
    """
    import os as _os
    root = _repo_root()
    marker = tmp_path / "flakyps-done.txt"
    fakedir = tmp_path / "fakebin"
    fakedir.mkdir()
    cnt = tmp_path / "pscount.txt"
    cnt.write_text("0")
    (fakedir / "ps").write_text(
        "#!/bin/sh\n"
        f'n=$(cat "{cnt}" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "{cnt}"\n'
        'if [ "$n" -gt "$W5PSFAIL_AFTER" ]; then exit 1; fi\n'
        'exec /bin/ps "$@"\n')
    (fakedir / "ps").chmod(0o755)
    cmd = WRAPPER + ["--budget-s", "3", "--checkpoint-dir",
                     str(tmp_path / "ckpt"), "--report-out",
                     str(tmp_path / "rep.json"), "--term-grace-s", "1",
                     "--", sys.executable, "-c",
                     f"import time; time.sleep(8); "  # {TOKEN}
                     f"open({str(marker)!r}, 'w').write('survived')"]
    env = dict(_os.environ)
    env["PATH"] = str(fakedir) + os.pathsep + env.get("PATH", "")
    env["W5PSFAIL_AFTER"] = "6"
    t0 = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=root,
                          timeout=60, env=env)
    wall = time.monotonic() - t0
    assert proc.returncode == 124, proc.stderr
    rep = json.loads((tmp_path / "rep.json").read_text())
    time.sleep(max(0.0, 8.5 - wall))
    assert not marker.exists(), (
        "registry kill failed: 8s sleeper survived although `ps` worked "
        "during life")
    assert wall < 3.0 + 1.0 + DRAIN_ALLOW, f"caller blocked {wall:.2f}s"
    assert rep.get("enforcement") == "UNVERIFIED", (
        f"kill-phase enumeration failed yet report claims "
        f"{rep.get('enforcement')}: {rep}")


def test_child_output_relayed_verbatim(tmp_path):
    """Child stdout/stderr bytes must pass the relay unaltered."""
    root = _repo_root()
    payload_out = "OUT-LINE-1\nOUT-LINE-2-no-newline"
    payload_err = "ERR-LINE-1\n"
    cmd = WRAPPER + ["--budget-s", "30", "--checkpoint-dir",
                     str(tmp_path / "ckpt"), "--report-out",
                     str(tmp_path / "rep.json"), "--",
                     sys.executable, "-c",
                     "import sys; "
                     f"sys.stdout.write({payload_out!r}); "
                     f"sys.stderr.write({payload_err!r}); "
                     "sys.stdout.buffer.write(bytes([0, 255, 1])); "
                     "sys.stdout.flush(); sys.stderr.flush()"]
    proc = subprocess.run(cmd, capture_output=True, cwd=root, timeout=60)
    assert proc.returncode == 0, proc.stderr[-500:]
    assert payload_out.encode() in proc.stdout, proc.stdout[-300:]
    assert b"\x00\xff\x01" in proc.stdout, proc.stdout[-300:]
    assert payload_err.encode() in proc.stderr, proc.stderr[-500:]


def test_success_path_lingering_grandchild_does_not_hang_caller(
        tmp_path, stray_reaper):
    """A grandchild outliving a successful child must not hang the caller.

    Required: rc 0 / CHILD_EXIT with a prompt caller return (bounded
    drain), even while the relay-holding grandchild is still alive.
    """
    root = _repo_root()
    pidfile = stray_reaper(tmp_path / "linger.pid")
    script = (
        "import subprocess, sys, time\n"
        f"# {TOKEN}\n"
        "p = subprocess.Popen([sys.executable, '-c',\n"
        f"    \"import os, time; open({str(pidfile)!r}, 'w').write(str(os.getpid())); "
        f"time.sleep(6)  # {TOKEN}\"])\n"
        "time.sleep(0.5)\n"  # let the grandchild start and inherit the relay.
    )
    cmd = WRAPPER + ["--budget-s", "30", "--checkpoint-dir",
                     str(tmp_path / "ckpt"), "--report-out",
                     str(tmp_path / "rep.json"), "--",
                     sys.executable, "-c", script]
    t0 = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=root,
                          timeout=60)
    wall = time.monotonic() - t0
    assert proc.returncode == 0, proc.stderr[-500:]
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert rep["status"] == "CHILD_EXIT"
    assert wall < 0.5 + DRAIN_ALLOW, (
        f"caller blocked {wall:.2f}s on a lingering grandchild")


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
            assert rep.get("enforcement") == "verified", rep
        outcomes.append(rep["status"])
    assert outcomes  # recorded distribution; either verdict is contract-valid.
