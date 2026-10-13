"""EXP runner tests (Worker 1, Q-003 Phase 2): manifest, execute, resume."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.research.runner import (
    build_manifest,
    execute_trial,
    load_completed,
    main,
    reconcile,
    run_manifest,
)


def test_manifest_derived_from_frozen_definitions():
    m1 = build_manifest("EXP-001")
    # arms x scenarios x (3 train seeds on train split + 2 val seeds on val split)
    assert m1["planned"] == 3 * 6 * 5
    assert m1["promotion_rule"].startswith("NONE")
    assert m1["code"]["registry_version"] == "0.4.0"
    ids = [t["trial_id"] for t in m1["trials"]]
    assert len(set(ids)) == len(ids)
    first = m1["trials"][0]
    assert first["trial_id"] == "EXP-001:S1:long-breakout:11:train"
    assert first["split_range"] == [0, 168]
    assert len(first["fixture_hash"]) == 64
    m2 = build_manifest("EXP-002")
    assert m2["planned"] == 3 * 4 * 5


def test_execute_trial_records_metrics_and_zero_signals_valid():
    m = build_manifest("EXP-001")
    flat = next(t for t in m["trials"]
                if t["scenario"] == "flat" and t["arm"] == "S1" and t["split"] == "train")
    rec = execute_trial(flat)
    assert rec.status == "ok"
    metrics = dict(rec.metrics)
    assert metrics["n_signals_long"] == "0"
    assert metrics["n_signals_short"] == "0"
    assert metrics["fixture_hash"] == flat["fixture_hash"]


def test_execute_trial_counts_constructed_breakout():
    m = build_manifest("EXP-001")
    trial = next(t for t in m["trials"]
                 if t["scenario"] == "long-breakout" and t["seed"] == 11
                 and t["arm"] == "S1" and t["split"] == "train")
    rec = execute_trial(trial)
    metrics = dict(rec.metrics)
    assert metrics["n_signals_long"] == "6"  # bars 154..159
    assert metrics["n_signals_short"] == "0"


def test_run_resume_and_reconcile(tmp_path):
    m = build_manifest("EXP-002")
    log1 = run_manifest(m, tmp_path, limit=3)
    assert len(log1.trials) == 3
    assert (tmp_path / "manifest.json").exists()
    assert (tmp_path / "trials.jsonl").exists()
    log2 = run_manifest(m, tmp_path, limit=5)  # resumes past 3
    assert len(log2.trials) == 5
    assert len(load_completed(tmp_path / "trials.jsonl").trials) == 5
    rec = reconcile({**m, "trials": m["trials"][:5]}, log2)
    assert (rec["planned"], rec["completed"], rec["failed"]) == (5, 5, 0)
    assert rec["missing"] == []


def test_failed_trials_persist_with_reason(tmp_path):
    m = build_manifest("EXP-001")
    bad = dict(m["trials"][0])
    bad["trial_id"] = "EXP-001:S1:bogus:11:train"
    bad["scenario"] = "bogus"
    log = run_manifest({**m, "trials": [bad]}, tmp_path)
    assert log.trials[0].status == "failed"
    assert "ValueError" in log.trials[0].reason


def test_main_smoke_and_exit_codes(tmp_path):
    assert main(["--exp", "EXP-002", "--out", str(tmp_path), "--limit", "2"]) == 0
    assert main(["--exp", "EXP-002", "--out", str(tmp_path / "d2"),
                 "--dry-run"]) == 0
    assert json.loads((tmp_path / "d2" / "EXP-002" / "manifest.json").read_text())["planned"] == 60


def test_manifest_counts_exp003_exp004():
    assert build_manifest("EXP-003")["planned"] == 3 * 4 * 5
    assert build_manifest("EXP-004")["planned"] == 2 * 4 * 5
