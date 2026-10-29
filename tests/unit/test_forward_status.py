"""Unified forward-status tests: read-only table + 6-line report, leak-proof.

All fixtures are SYNTHETIC (empty tmp roots or canned status docs). No
Vision pull, no forward-dated real file is ever decoded, no holdout file
is touched, no network. The leak-guard tests prove no performance field
(Sharpe, P&L, equity, returns, verdicts) can reach any output pre-power:
each guard below was deleted in a scratch copy and the named test was
confirmed to fail (see PR body).
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("pandas")

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "forward_status", str(ROOT / "tools" / "forward_status.py"))
fs = importlib.util.module_from_spec(_spec)
sys.modules["forward_status"] = fs
_spec.loader.exec_module(fs)

SENTINELS = ("LEAKME_SHARPE", "LEAKME_STATS", "LEAKME_VERDICT", "LEAKME_RET",
             "987654", "777777", "3.14159265")


def _studs():
    return [dict(s) for s in fs.STUDIES]


def _empty_roots(tmp_path):
    # NOTE: dirs intentionally NOT created: day-0 must render, never crash.
    return tmp_path / "data", tmp_path / "reports"


def _collect_all(data, reports):
    return [fs.collect(s, Path(data) / s["leaf"]) for s in _studs()]


def test_table_empty_roots_day_zero(tmp_path, capsys):
    data, reports = _empty_roots(tmp_path)
    rc = fs.main(["--data", str(data), "--reports", str(reports)])
    assert rc == 0
    out = capsys.readouterr().out
    for study in ("B4b", "F-CARRY", "V-REG"):
        assert study in out
    assert out.count("0/90") == 3
    assert "forward_days" in out
    assert "Traceback" not in out


def test_table_columns_and_hashes(tmp_path):
    data, reports = _empty_roots(tmp_path)
    rows = _collect_all(data, reports)
    assert [r["study"] for r in rows] == ["B4b", "F-CARRY", "V-REG"]
    for r in rows:
        assert r["forward_days"] == 0
        assert r["to_power_days"] == 90
        assert r["to_pass_days"] == 121
        assert r["blocking_gate"] == "forward_days"
        assert r["powered"] is False
        assert len(r["manifest_hash"]) == 12
        assert len(r["prereg_sha12"]) == 12
        assert len(r["code_sha12"]) == 12
    # Deterministic across runs.
    rows2 = _collect_all(data, reports)
    assert rows == rows2


def test_prereg_sha_matches_frozen_files(tmp_path):
    data, reports = _empty_roots(tmp_path)
    rows = _collect_all(data, reports)
    for r, s in zip(rows, _studs(), strict=True):
        want = hashlib.sha256((ROOT / s["prereg"]).read_bytes()).hexdigest()
        assert r["prereg"] == s["prereg"]
        assert r["prereg_sha12"] == want[:12]


def test_report_empty_matches_template(tmp_path, capsys):
    data, reports = _empty_roots(tmp_path)
    rc = fs.main(["--data", str(data), "--reports", str(reports), "--report"])
    assert rc == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 6
    assert lines[0].startswith("1. Gate: NO-GO | Money proven: $0")
    assert "Forward-waiting: 3" in lines[1] and "Edge: none" in lines[1]
    assert "0/90d" in lines[1]
    assert lines[2].startswith("3. Code: tip ")
    assert "day1 2026-11-01" in lines[3]
    assert "2027-01-29 kill-only" in lines[3]
    assert "2027-03-01 PASS-capable" in lines[3]
    assert lines[4].startswith("5. Blocker: ")
    assert lines[5].startswith("6. Next: ")


def _poisoned_doc():
    return {
        "forward_days": 10, "forward_days_required": 90,
        "forward_days_remaining": 80, "powered": False,
        "blocking_gate": "forward_days",
        "years_assessable_from_forward_day": 121,
        "years_assessable_from": "2027-03-01",
        "forward_days_to_first_possible_pass": 111,
        "forward_clock_start": "2026-11-01",
        "coverage": {}, "regime_absent_cells": [],
        "per_cell": {"c": {"round_trips": 3, "round_trips_required": 20,
                           "round_trips_remaining": 17,
                           "sharpe_1x": 987654.0, "note": "LEAKME_SHARPE"}},
        # --- injected performance fields: none may ever reach output ---
        "sharpe": 987654.0, "sharpe_2x": 3.14159265,
        "net_daily": [3.14159265], "stats": {"x": "LEAKME_STATS"},
        "verdict": "LEAKME_VERDICT", "equity": 777777.7,
        "pnl": [9.99], "returns": "LEAKME_RET", "dsr": 0.99, "pbo": 0.01,
    }


def test_leak_guard_blocks_performance_fields(tmp_path, capsys, monkeypatch):
    data, reports = _empty_roots(tmp_path)
    poison = _poisoned_doc()
    # Unit proof on the guard itself: scrub keeps exactly the allowlist.
    scrubbed = fs._scrub(dict(poison))
    assert set(scrubbed) <= set(fs._SAFE_TOP_FIELDS), (
        set(scrubbed) - set(fs._SAFE_TOP_FIELDS))
    for cell in scrubbed.get("per_cell", {}).values():
        assert set(cell) <= set(fs._SAFE_CELL_FIELDS), set(cell)
    blob = json.dumps(scrubbed, sort_keys=True, default=str)
    for sent in SENTINELS:
        assert sent not in blob, sent
    # End-to-end: poisoned status docs still render clean tables/reports.
    for s in _studs():
        mod = fs._load_module(s["module"], s["file"])
        monkeypatch.setattr(mod, "status_doc", lambda root, _p=poison: dict(_p))
    rows = _collect_all(data, reports)
    table = fs.render_table(rows)
    verdicts = {s["key"]: None for s in _studs()}
    report = fs.render_report(rows, verdicts, "tip")
    for sent in SENTINELS:
        assert sent not in table, sent
        assert sent not in report, sent
    # ...while the counters DO come through (guard is precise, not a gag).
    assert "10/90" in table
    assert "days so far: 10" in report
    # Scrubbed rows carry exactly the allowlisted shape (no stowaways).
    allowed = {"study", "forward_days", "days_required", "cells", "powered",
               "blocking_gate", "to_power_days", "to_pass_days", "years_from",
               "manifest_hash", "prereg", "prereg_sha12", "code_sha12",
               "clock_start"}
    for r in rows:
        assert set(r) <= allowed, set(r) - allowed


def test_returns_stays_zero_until_pass(tmp_path):
    data, reports = _empty_roots(tmp_path)
    rows = _collect_all(data, reports)
    # (a) no verdict files at all
    assert "$0" in fs.render_report(
        rows, fs._verdict_statuses(reports), "tip").splitlines()[0]
    # (b) stored KILLED verdict still proves $0 (never reads its numbers)
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "V-reg-forward.json").write_text(json.dumps({
        "status": "KILLED", "sharpe": 987654.0, "note": "LEAKME_VERDICT"}))
    rep = fs.render_report(rows, fs._verdict_statuses(reports), "tip")
    assert "Money proven: $0" in rep.splitlines()[0]
    assert "LEAKME_VERDICT" not in rep and "987654" not in rep
    assert "V-REG" in rep.splitlines()[1]  # named under forward kills
    # (c) stored PASS names the study, prints no numbers
    (reports / "V-reg-forward.json").write_text(json.dumps({
        "status": "PASS", "stats": {"sharpe": 555.666}}))
    rep2 = fs.render_report(rows, fs._verdict_statuses(reports), "tip")
    assert "PASS V-REG" in rep2.splitlines()[0]
    assert "555.666" not in rep2
    assert "Edge: V-REG" in rep2.splitlines()[1]
    # (d) corrupt verdict file behaves as missing (never crashes)
    (reports / "V-reg-forward.json").write_text("{not json")
    rep3 = fs.render_report(rows, fs._verdict_statuses(reports), "tip")
    assert "Money proven: $0" in rep3.splitlines()[0]


def _boom(*a, **k):
    raise AssertionError("forbidden call")


def test_never_calls_run_verify_evaluate(tmp_path, capsys, monkeypatch):
    data, reports = _empty_roots(tmp_path)
    mods = [fs._load_module(s["module"], s["file"]) for s in _studs()]
    for mod in mods:
        for name in ("run", "verify", "evaluate", "evaluate_frames",
                     "forward_command", "fetch"):
            if hasattr(mod, name):
                monkeypatch.setattr(mod, name, _boom)
    rows = _collect_all(data, reports)  # status_doc only: must not raise
    assert len(rows) == 3
    assert fs.main(["--data", str(data), "--reports", str(reports)]) == 0
    assert fs.main(["--data", str(data), "--reports", str(reports),
                    "--report"]) == 0
    capsys.readouterr()


def test_static_no_forbidden_calls():
    # AST proof to back the monkeypatch test: the tool's own source never
    # calls run/verify/evaluate (any flavour), forward_command, fetch, or
    # any network client. Only `<module>.status_doc(...)` may be called.
    tree = ast.parse((ROOT / "tools/forward_status.py").read_text())
    forbidden = {"run", "verify", "evaluate", "evaluate_frames",
                 "forward_command", "fetch", "urlopen", "requests", "socket",
                 "VisionClient", "netguard"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Name):
            assert fn.id not in forbidden, fn.id
        elif isinstance(fn, ast.Attribute):
            if isinstance(fn.value, ast.Name) and fn.value.id == "mod":
                assert fn.attr == "status_doc", fn.attr


def test_b4b_shape_normalized(monkeypatch):
    # B4b predates per-cell/blocking/manifest bindings: the normalizer
    # derives them from counters (all three blocking branches).
    doc = {"forward_days": 10, "forward_days_required": 90,
           "forward_days_remaining": 80, "round_trips": 3,
           "round_trips_required": 20, "round_trips_remaining": 17,
           "powered": False, "years_assessable_from_forward_day": 121,
           "years_assessable_from": "2027-03-01",
           "forward_days_to_first_possible_pass": 111,
           "forward_clock_start": "2026-11-01", "coverage": {},
           "prereg": "research/prereg/B4b-forward-basis.md"}
    mod = fs._load_module("forward_b4b", "tools/forward_b4b.py")
    monkeypatch.setattr(mod, "status_doc", lambda root: dict(doc))
    (row,) = [fs.collect(s, Path("/nonexistent"))
              for s in _studs() if s["key"] == "B4b"]
    assert row["cells"] == {"book": {"round_trips": 3,
                                     "round_trips_required": 20,
                                     "round_trips_remaining": 17}}
    assert row["blocking_gate"] == "forward_days"
    assert len(row["prereg_sha12"]) == 12 and len(row["code_sha12"]) == 12
    doc["forward_days"] = 95
    (row2,) = [fs.collect(s, Path("/nonexistent"))
               for s in _studs() if s["key"] == "B4b"]
    assert row2["blocking_gate"].startswith("round_trips")
    doc["round_trips"] = 25
    (row3,) = [fs.collect(s, Path("/nonexistent"))
               for s in _studs() if s["key"] == "B4b"]
    assert row3["blocking_gate"] == "years_assessability"


def test_manifest_hash_stable_and_sensitive(tmp_path, monkeypatch):
    data, reports = _empty_roots(tmp_path)
    a = _collect_all(data, reports)
    b = _collect_all(data, reports)
    assert [r["manifest_hash"] for r in a] == [r["manifest_hash"] for r in b]
    doc = _poisoned_doc()
    doc["data_manifest"] = {"files": [{"path": "x", "sha256": "y"}]}
    mod = fs._load_module("forward_vreg", "tools/forward_vreg.py")
    monkeypatch.setattr(mod, "status_doc", lambda root: dict(doc))
    c = _collect_all(data, reports)
    assert c[2]["manifest_hash"] != a[2]["manifest_hash"]
