"""V-007: strict run-file loaders fail loudly, never silently adjust."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from cryptobot.reporting.schemas import RunFileError, load_run

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "v007_run"


def _copy(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    shutil.copytree(FIX, run)
    return run


def test_load_fixture_run_counts():
    run = load_run(FIX)
    assert len(run.fills) == 3
    assert len(run.equity) == 5
    assert len(run.rejections) == 2
    assert len(run.risk_events) == 2
    assert run.config["run"]["dataset"] == "synthetic-v007"


def test_missing_file_fails(tmp_path):
    run = _copy(tmp_path)
    (run / "fills.jsonl").unlink()
    with pytest.raises(RunFileError, match="missing run file"):
        load_run(run)


def test_missing_required_field_fails(tmp_path):
    run = _copy(tmp_path)
    rows = (run / "fills.jsonl").read_text().splitlines()
    bad = json.loads(rows[0])
    del bad["fee"]
    rows[0] = json.dumps(bad)
    (run / "fills.jsonl").write_text("\n".join(rows) + "\n")
    with pytest.raises(RunFileError, match="fee must be a finite"):
        load_run(run)


def test_duplicate_execution_id_fails(tmp_path):
    run = _copy(tmp_path)
    with (run / "fills.jsonl").open("a") as fh:
        fh.write((run / "fills.jsonl").read_text().splitlines()[0] + "\n")
    with pytest.raises(RunFileError, match="duplicate execution_id"):
        load_run(run)


def test_fill_qty_mismatch_vs_ledger_fails(tmp_path):
    run = _copy(tmp_path)
    rows = (run / "fills.jsonl").read_text().splitlines()
    bad = json.loads(rows[0])
    bad["qty"] = bad["qty"] + 1.0
    rows[0] = json.dumps(bad)
    (run / "fills.jsonl").write_text("\n".join(rows) + "\n")
    with pytest.raises(RunFileError, match="no ledger fill agrees"):
        load_run(run)


def test_fill_unseen_by_ledger_fails(tmp_path):
    run = _copy(tmp_path)
    rows = (run / "fills.jsonl").read_text().splitlines()
    bad = json.loads(rows[0])
    bad["execution_id"] = "ghost"
    rows.append(json.dumps(bad))
    (run / "fills.jsonl").write_text("\n".join(rows) + "\n")
    with pytest.raises(RunFileError, match="no ledger fill agrees"):
        load_run(run)


def test_unknown_fill_symbol_fails(tmp_path):
    run = _copy(tmp_path)
    rows = (run / "fills.jsonl").read_text().splitlines()
    bad = json.loads(rows[0])
    bad["instrument"] = "ETHUSDT"
    rows[0] = json.dumps(bad)
    (run / "fills.jsonl").write_text("\n".join(rows) + "\n")
    with pytest.raises(RunFileError, match="unknown instrument"):
        load_run(run)


def test_naive_timestamp_fails(tmp_path):
    run = _copy(tmp_path)
    rows = (run / "equity.jsonl").read_text().splitlines()
    bad = json.loads(rows[0])
    bad["ts_utc"] = "2026-10-10T12:00:00"
    rows[0] = json.dumps(bad)
    (run / "equity.jsonl").write_text("\n".join(rows) + "\n")
    with pytest.raises(RunFileError, match="tz-aware"):
        load_run(run)


def test_empty_fills_is_valid(tmp_path):
    run = _copy(tmp_path)
    (run / "fills.jsonl").write_text("")
    from cryptobot.accounting import Ledger
    Ledger(10000.0).save(run / "ledger.json")
    loaded = load_run(run)
    assert loaded.fills == ()


def test_fills_without_ledger_fills_fails(tmp_path):
    run = _copy(tmp_path)
    from cryptobot.accounting import Ledger
    Ledger(10000.0).save(run / "ledger.json")
    with pytest.raises(RunFileError, match="fills present without ledger fills"):
        load_run(run)


def test_equity_mark_provenance_defaults_unrecorded():
    run = load_run(FIX)
    assert all(r.mark_source == "unrecorded" for r in run.equity)
    assert all(r.mark_age_ms is None for r in run.equity)


def test_equity_mark_provenance_loads(tmp_path):
    run = _copy(tmp_path)
    rows = (run / "equity.jsonl").read_text().splitlines()
    first = json.loads(rows[0])
    first["mark_source"] = "exchange"
    first["mark_age_ms"] = 250.0
    rows[0] = json.dumps(first)
    (run / "equity.jsonl").write_text("\n".join(rows) + "\n")
    loaded = load_run(run)
    assert loaded.equity[0].mark_source == "exchange"
    assert loaded.equity[0].mark_age_ms == 250.0


def test_equity_bad_mark_provenance_fails(tmp_path):
    run = _copy(tmp_path)
    rows = (run / "equity.jsonl").read_text().splitlines()
    bad = json.loads(rows[0])
    bad["mark_age_ms"] = -5.0
    rows[0] = json.dumps(bad)
    (run / "equity.jsonl").write_text("\n".join(rows) + "\n")
    with pytest.raises(RunFileError, match="mark_age_ms"):
        load_run(run)
