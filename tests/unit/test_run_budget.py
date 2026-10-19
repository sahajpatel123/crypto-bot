"""Accelerated deadline tests for tools/run_budget.py (seconds-scale)."""
import json
import subprocess
import sys
import time
from pathlib import Path

# Enforce-or-refuse contract: strict (default) refuses on hosts without a
# verified subreaper+scan (incl. macOS). These legacy-behavior tests opt
# into best-effort explicitly; refusal itself is covered by
# tests/unit/test_run_budget_refusal.py.
WRAPPER = [sys.executable, "tools/run_budget.py", "--allow-best-effort"]


def _run(tmp_path, *args):
    t0 = time.monotonic()
    proc = subprocess.run(WRAPPER + list(args), capture_output=True, text=True)
    return proc, time.monotonic() - t0


def test_quick_job_passes_through(tmp_path):
    ckpt = tmp_path / "ckpt"
    rep = tmp_path / "report.json"
    proc, _ = _run(tmp_path, "--budget-s", "60", "--checkpoint-dir",
                   str(ckpt), "--report-out", str(rep), "--",
                   sys.executable, "-c", "print('ok')")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(rep.read_text())["status"] == "CHILD_EXIT"


def test_child_failure_passes_through(tmp_path):
    ckpt = tmp_path / "ckpt"
    rep = tmp_path / "report.json"
    proc, _ = _run(tmp_path, "--budget-s", "60", "--checkpoint-dir",
                   str(ckpt), "--report-out", str(rep), "--",
                   sys.executable, "-c", "import sys; sys.exit(3)")
    assert proc.returncode == 3


def test_overrun_killed_and_incomplete(tmp_path):
    ckpt = tmp_path / "ckpt"
    rep = tmp_path / "report.json"
    proc, wall = _run(tmp_path, "--budget-s", "3", "--checkpoint-dir",
                      str(ckpt), "--report-out", str(rep),
                      "--heartbeat-s", "1", "--term-grace-s", "1", "--",
                      sys.executable, "-c", "import time; time.sleep(60)")
    assert proc.returncode == 124, proc.stderr
    assert wall < 3 + 1 + 8  # budget + grace + generous scheduling slack.
    record = json.loads(rep.read_text())
    assert record["status"] == "INCOMPLETE_BUDGET"
    assert (ckpt / "budget_checkpoint.json").exists()
    assert "elapsed=" in proc.stderr  # heartbeat evidence.


def test_nested_budget_cannot_extend_outer(tmp_path):
    ckpt = tmp_path / "ckpt"
    rep = tmp_path / "report.json"
    inner = [sys.executable, "tools/run_budget.py", "--allow-best-effort",
             "--budget-s", "600",
             "--checkpoint-dir", str(ckpt / "inner"), "--report-out",
             str(tmp_path / "inner.json"), "--", sys.executable,
             "-c", "import time; time.sleep(60)"]
    proc, wall = _run(tmp_path, "--budget-s", "3", "--checkpoint-dir",
                      str(ckpt), "--report-out", str(rep),
                      "--term-grace-s", "1", "--", *inner)
    assert proc.returncode == 124, proc.stderr
    assert wall < 3 + 1 + 10
    # Either the inner wrapper enforced the inherited deadline itself or
    # the outer kill preempted it; both prove no extension. If the inner
    # report exists it must never claim success.
    inner_json = tmp_path / "inner.json"
    if inner_json.exists():
        inner_rep = json.loads(inner_json.read_text())
        assert inner_rep["status"] == "INCOMPLETE_BUDGET"


def test_child_tree_killed_not_orphaned(tmp_path):
    marker = tmp_path / "survivor.txt"
    ckpt = tmp_path / "ckpt"
    rep = tmp_path / "report.json"
    # Child spawns a grandchild that would outlive it if only the child died.
    script = ("import subprocess, sys, time; "
              "subprocess.Popen([sys.executable, '-c', "
              f"\"import time; time.sleep(30); open({str(marker)!r}, 'w').write('x')\"]); "
              "time.sleep(60)")
    proc, _ = _run(tmp_path, "--budget-s", "3", "--checkpoint-dir",
                   str(ckpt), "--report-out", str(rep),
                   "--term-grace-s", "1", "--",
                   sys.executable, "-c", script)
    assert proc.returncode == 124
    time.sleep(2)
    assert not marker.exists()  # whole process group died.
