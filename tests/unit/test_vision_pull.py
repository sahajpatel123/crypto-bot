"""E1.2: vision pull split boundaries, checksum gating, resume, report."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "vision_pull", REPO / "tools" / "vision_pull.py")
assert SPEC and SPEC.loader
vision_pull = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(vision_pull)


def test_split_monthly_boundary():
    assert vision_pull.split_of("BTCUSDT-1d-2023-12.zip") == "dev"
    assert vision_pull.split_of("BTCUSDT-1d-2024-01.zip") == "holdout"
    assert vision_pull.split_of("BTCUSDT-1h-2020-01.zip") == "dev"
    assert vision_pull.split_of("BTCUSDT-1h-2026-09.zip") == "holdout"


def test_split_daily_boundary():
    assert vision_pull.split_of("BTCUSDT-metrics-2023-12-31.zip") == "dev"
    assert vision_pull.split_of("BTCUSDT-metrics-2024-01-01.zip") == "holdout"
    assert vision_pull.split_of("BTCUSDT-1d-2026-10-17.zip") == "holdout"


def test_split_dev_only_skips_holdout():
    assert vision_pull.split_of("BTCUSDT-1m-2023-12.zip",
                                dev_only=True) == "dev"
    assert vision_pull.split_of("BTCUSDT-1m-2024-01.zip",
                                dev_only=True) == "skip"
    with pytest.raises(ValueError, match="no YYYY-MM"):
        vision_pull.split_of("no-date-here.zip")


def test_pull_job_verifies_checksum_and_splits(tmp_path, monkeypatch):
    payload = b"PK fake-zip-bytes"
    want = __import__("hashlib").sha256(payload).hexdigest()
    monkeypatch.setattr(vision_pull, "_fetch_text",
                        lambda url: f"{want}  f.zip")
    monkeypatch.setattr(vision_pull, "_fetch_file",
                        lambda url, dest: dest.write_bytes(payload))
    dev, hold = tmp_path / "dev", tmp_path / "hold"
    job = {"key": "k", "url": "u", "checksum_url": "c",
           "dataset": "klines", "symbol": "BTCUSDT", "interval": "1d",
           "filename": "BTCUSDT-1d-2023-12.zip", "bytes": len(payload),
           "split": "dev"}
    rec = vision_pull.pull_job(job, dev_dir=dev, holdout_dir=hold)
    assert rec["status"] == "ok"
    assert (dev / "klines" / "1d" / "BTCUSDT"
            / "BTCUSDT-1d-2023-12.zip").exists()
    hold_job = dict(job, filename="BTCUSDT-1d-2024-01.zip", split="holdout")
    rec = vision_pull.pull_job(hold_job, dev_dir=dev, holdout_dir=hold)
    assert rec["status"] == "ok"
    assert (hold / "klines" / "1d" / "BTCUSDT"
            / "BTCUSDT-1d-2024-01.zip").exists()


def test_pull_job_checksum_mismatch_fails_loud(tmp_path, monkeypatch):
    monkeypatch.setattr(vision_pull, "_fetch_text",
                        lambda url: "0" * 64 + "  f.zip")
    monkeypatch.setattr(vision_pull, "_fetch_file",
                        lambda url, dest: dest.write_bytes(b"other"))
    monkeypatch.setattr(vision_pull.time, "sleep", lambda s: None)
    job = {"key": "k", "url": "u", "checksum_url": "c",
           "dataset": "klines", "symbol": "BTCUSDT", "interval": "1d",
           "filename": "f.zip", "bytes": 5, "split": "dev"}
    rec = vision_pull.pull_job(job, dev_dir=tmp_path / "dev",
                               holdout_dir=tmp_path / "hold")
    assert rec["status"] == "failed"
    assert "checksum" in rec["error"]
    assert not list((tmp_path / "dev").rglob("*.zip"))


def test_pull_state_resume_and_report(tmp_path):
    plan = {"jobs": [
        {"key": "a", "dataset": "klines", "interval": "1d",
         "symbol": "BTCUSDT", "filename": "x.zip", "split": "dev"},
        {"key": "b", "dataset": "klines", "interval": "1d",
         "symbol": "BTCUSDT", "filename": "y.zip", "split": "dev"}]}
    plan_p = tmp_path / "plan.json"
    plan_p.write_text(json.dumps(plan))
    state = vision_pull.PullState(tmp_path / "state.json")
    assert state.done("a") is False
    state.record("a", {"status": "ok", "path": "x"})
    state.save()
    assert vision_pull.PullState(tmp_path / "state.json").done("a") is True
    import argparse
    ns = argparse.Namespace(plan=str(plan_p), state=str(tmp_path / "state.json"),
                           out=str(tmp_path / "report.json"))
    assert vision_pull.cmd_report(ns) == 0
    rep = json.loads((tmp_path / "report.json").read_text())
    assert rep["ok_files"] == 1 and rep["symbols_with_gaps"] == 1
    assert rep["gaps"]["klines/1d/BTCUSDT"]["missing"] == ["y.zip"]


def test_job_builder_marks_dev_only_and_skips_checksums():
    contents = [{"Key": "data/futures/um/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-2020-01.zip",
                 "Size": 10},
                {"Key": "data/futures/um/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-2020-01.zip.CHECKSUM",
                 "Size": 89}]
    jobs = [vision_pull._job("klines", "BTCUSDT", "1m", c, dev_only=True)
            for c in contents
            if c["Key"].endswith(".zip") and ".CHECKSUM" not in c["Key"]]
    assert len(jobs) == 1
    assert jobs[0]["checksum_url"].endswith(".CHECKSUM")


def test_list_symbols_takes_last_segment(monkeypatch):
    seen = {}

    def fake_list(prefix, delimiter=None, max_keys=1000):
        seen["prefix"] = prefix
        return [], [f"{prefix}BTCUSDT/", f"{prefix}ETHUSDT/"]

    monkeypatch.setattr(vision_pull, "s3_list_keys", fake_list)
    assert vision_pull.list_symbols("klines") == ["BTCUSDT", "ETHUSDT"]
    assert seen["prefix"] == "data/futures/um/monthly/klines/"
