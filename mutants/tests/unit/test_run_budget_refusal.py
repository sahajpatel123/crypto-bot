"""Enforce-or-refuse tests for tools/run_budget.py (DEEP-W1-D1).

Strict (default) refuses on hosts where containment cannot be verified
(not Linux, no subreaper, or broken table scan): exit 125, REFUSED on
stderr, REFUSED_UNSUPPORTED in checkpoint+report, child never spawned.
--allow-best-effort preserves the legacy path bit-for-bit on rc and
report shape.
"""
import json
import subprocess
import sys
import time

import pytest

WRAPPER = [sys.executable, "tools/run_budget.py"]

REFUSAL_KEYS = {"status", "pid", "budget_s", "deadline_inherited",
                "command", "reason", "note"}
REASON_KEYS = {"platform", "linux", "subreaper_acquired", "table_scan_ok"}
# Legacy report shapes (bit-for-bit contract for --allow-best-effort).
CHILD_EXIT_KEYS = {"status", "child_rc", "elapsed_s", "budget_s",
                   "command", "subreaper"}
TIMEOUT_KEYS = {"status", "child_rc", "elapsed_s", "budget_s", "command",
                "note", "enforcement", "enforcement_detail",
                "enum_source", "subreaper", "platform_note"}


def _needs_refusal_host():
    """Skip the live-refusal tests where containment verifies (Linux)."""
    import tools.run_budget as run_budget
    supported, _ = run_budget._preflight_supported()
    if supported:
        pytest.skip("host verifies containment; refusal N/A here")


def test_strict_refuses_and_never_spawns(tmp_path):
    _needs_refusal_host()
    marker = tmp_path / "spawned.txt"
    ckpt = tmp_path / "ckpt"
    rep = tmp_path / "report.json"
    child = [sys.executable, "-c",
             f"open({str(marker)!r}, 'w').write('x'); import time; "
             f"time.sleep(60)"]
    t0 = time.monotonic()
    proc = subprocess.run(
        WRAPPER + ["--budget-s", "60", "--checkpoint-dir", str(ckpt),
                   "--report-out", str(rep), "--", *child],
        capture_output=True, text=True, timeout=60)
    wall = time.monotonic() - t0
    assert proc.returncode == 125, proc.stderr
    assert "REFUSED" in proc.stderr
    assert wall < 15, f"refusal took {wall:.1f}s; child may have spawned"
    assert not marker.exists(), "strict refusal spawned the child"
    report = json.loads(rep.read_text())
    assert report["status"] == "REFUSED_UNSUPPORTED", report
    checkpoint = json.loads((ckpt / "budget_checkpoint.json").read_text())
    assert checkpoint["status"] == "REFUSED_UNSUPPORTED", checkpoint


def test_refusal_record_shape(tmp_path):
    _needs_refusal_host()
    ckpt = tmp_path / "ckpt"
    rep = tmp_path / "report.json"
    child = [sys.executable, "-c", "pass"]
    proc = subprocess.run(
        WRAPPER + ["--budget-s", "60", "--checkpoint-dir", str(ckpt),
                   "--report-out", str(rep), "--", *child],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 125, proc.stderr
    report = json.loads(rep.read_text())
    assert set(report) == REFUSAL_KEYS, sorted(report)
    assert set(report["reason"]) == REASON_KEYS, report["reason"]
    assert report["command"] == child
    assert report["budget_s"] == 60.0
    assert report["reason"]["platform"] == sys.platform
    # Checkpoint carries the same refusal record.
    checkpoint = json.loads((ckpt / "budget_checkpoint.json").read_text())
    assert checkpoint == report


def test_best_effort_quick_job_bit_for_bit(tmp_path):
    ckpt = tmp_path / "ckpt"
    rep = tmp_path / "report.json"
    proc = subprocess.run(
        WRAPPER + ["--allow-best-effort", "--budget-s", "60",
                   "--checkpoint-dir", str(ckpt), "--report-out",
                   str(rep), "--", sys.executable, "-c", "print('ok')"],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    report = json.loads(rep.read_text())
    assert report["status"] == "CHILD_EXIT"
    assert set(report) == CHILD_EXIT_KEYS, sorted(report)
    assert report["child_rc"] == 0


def test_best_effort_child_rc_passthrough(tmp_path):
    ckpt = tmp_path / "ckpt"
    rep = tmp_path / "report.json"
    proc = subprocess.run(
        WRAPPER + ["--allow-best-effort", "--budget-s", "60",
                   "--checkpoint-dir", str(ckpt), "--report-out",
                   str(rep), "--", sys.executable, "-c",
                   "import sys; sys.exit(3)"],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 3, proc.stderr
    report = json.loads(rep.read_text())
    assert set(report) == CHILD_EXIT_KEYS, sorted(report)
    assert report["child_rc"] == 3


def test_best_effort_timeout_bit_for_bit(tmp_path):
    ckpt = tmp_path / "ckpt"
    rep = tmp_path / "report.json"
    proc = subprocess.run(
        WRAPPER + ["--allow-best-effort", "--budget-s", "2",
                   "--checkpoint-dir", str(ckpt), "--report-out",
                   str(rep), "--term-grace-s", "1", "--",
                   sys.executable, "-c", "import time; time.sleep(60)"],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 124, proc.stderr
    report = json.loads(rep.read_text())
    assert report["status"] == "INCOMPLETE_BUDGET"
    assert set(report) == TIMEOUT_KEYS, sorted(report)


@pytest.mark.parametrize("platform,reaper,scan,expected", [
    ("darwin", False, True, False),   # this host: no Linux, no subreaper.
    ("linux", True, True, True),      # fully supported.
    ("linux", False, True, False),    # subreaper leg decides.
    ("linux", True, False, False),    # scan leg decides.
])
def test_preflight_legs(monkeypatch, platform, reaper, scan, expected):
    import tools.run_budget as run_budget
    monkeypatch.setattr("sys.platform", platform)
    monkeypatch.setattr(run_budget, "_try_subreaper", lambda: reaper)
    monkeypatch.setattr(run_budget, "_scan_descendants",
                        lambda *roots: (set(), scan))
    supported, reason = run_budget._preflight_supported()
    assert supported is expected, reason
    assert set(reason) == REASON_KEYS, reason
    assert reason["linux"] is (platform == "linux")
