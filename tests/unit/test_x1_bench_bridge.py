"""Bench-bridge tests (W4): synthetic bench outputs only, no round data.

Covers the mechanical reshape (comparison/report/fills/coverage)
and every BLOCKED condition. No selection or economics logic
lives in the bridge; none is asserted here.
"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

REPO = Path(__file__).resolve().parents[2]


def _load_tool(name):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        name, REPO / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _cell_kit(tmp_path: Path, fills=2, run_id="x1-realistic-X1-R1_dev"):
    ckpt = tmp_path / "ckpt"
    work = ckpt / "work"
    work.mkdir(parents=True)
    (ckpt / "bench_checkpoint.json").write_text(json.dumps({
        "run_id": run_id,
        "cursor": {"day": "2026-09-11", "seqs": {"BTCUSDT": 10}},
        "identity": {"config_fingerprint": "fp1",
                     "dataset": {"manifest_sha": "abc",
                                 "symbols": ["BTCUSDT", "ETHUSDT"]}},
        "engine": {"position": {}, "reservations": {}},
    }))
    journal = []
    for i in range(fills):
        journal.append({"event": "fill", "exec_id": f"e{i}",
                        "client_id": f"c{i}", "symbol": "ETHUSDT",
                        "venue_side": "LONG" if i == 0 else "SHORT",
                        "qty": 1.0, "price": 100.0, "fee": 0.05,
                        "ts_utc": "2026-09-12T00:00:00+00:00"})
    journal.append({"event": "commit", "cursor": {}})
    (work / "engine_journal.jsonl").write_text(
        "\n".join(json.dumps(r) for r in journal) + "\n")
    db = sqlite3.connect(ckpt / "store.db")
    db.execute("CREATE TABLE intents (run_id TEXT)")
    db.executemany("INSERT INTO intents VALUES (?)",
                   [(run_id,), (run_id,)])
    db.commit()
    db.close()
    rep1 = tmp_path / "j1.json"
    rep1.write_text(json.dumps({
        "run_id": run_id, "status": "INCOMPLETE_BUDGET",
        "booked": {"equity_close": 121.0, "commissions": 0.1,
                   "funding": 0.0, "realised": 0.5},
        "events": {"ingested": 100, "skipped_window": 5}}))
    rep2 = tmp_path / "j2.json"
    rep2.write_text(json.dumps({
        "run_id": run_id, "status": "COMPLETE",
        "booked": {"equity_close": 122.0, "commissions": 0.2,
                   "funding": 0.0, "realised": 1.0},
        "events": {"ingested": 50, "skipped_window": 0}}))
    toml = tmp_path / "cell.toml"
    toml.write_text("[paper]\ncapital_usdt = 120.0\n[fees]\ntaker_bps = 5.0\n")
    splits = tmp_path / "splits.toml"
    splits.write_text(
        "[[split]]\nidx = 1\nrole = \"dev\"\n"
        "[[split.coverage]]\nsymbol = \"BTCUSDT\"\nchannel = \"aggTrade\"\n"
        "rows = 1000\n[[split.coverage]]\nsymbol = \"ETHUSDT\"\n"
        "channel = \"aggTrade\"\nrows = 2000\n")
    return {"config_id": "X1-R1", "arm": "X1", "split": "dev",
            "tag": "realistic", "toml": str(toml),
            "ckpt_dir": str(ckpt),
            "jobs": [{"report": str(rep1)}, {"report": str(rep2)}]}, splits


def test_bridge_cell_mechanics(tmp_path):
    bridge = _load_tool("x1_bench_bridge")
    cell, splits = _cell_kit(tmp_path)
    out = tmp_path / "econ"
    record = bridge.bridge_cell(cell, out, str(splits))
    comp = json.loads((out / "X1-R1_dev.comparison.json").read_text())
    assert list(comp["cells"]) == ["X1|dev"]
    assert comp["cells"]["X1|dev"]["closing_equity"] == 122.0
    assert comp["dataset_manifest_sha"] == "abc"
    rundir = out / "X1-R1_dev.rundir"
    report = json.loads((rundir / "report.json").read_text())
    assert report["opening_equity"] == 120.0
    assert report["closing_equity"] == 122.0
    assert report["paid_costs"] == 0.2
    assert report["intents_admitted"] == 2
    assert report["fee_schedule"] == {"taker_bps": 5.0}
    fills = (rundir / "fills.jsonl").read_text().splitlines()
    assert len(fills) == 2
    first = json.loads(fills[0])
    assert first["execution_id"] == "e0" and first["side"] == "LONG"
    assert record["ingested_total"] == 150
    assert record["skipped_window_total"] == 5
    assert record["split_event_total"] == 3000
    assert record["coverage_frac"] == pytest.approx(0.05)
    assert record["exposed_at_cap"] is False
    assert record["final_status"] == "COMPLETE"


def test_bridge_blocked_conditions(tmp_path):
    bridge = _load_tool("x1_bench_bridge")
    cell, splits = _cell_kit(tmp_path)
    out = tmp_path / "econ"
    # Missing job report.
    bad = dict(cell, jobs=[{"report": str(tmp_path / "nope.json")}])
    with pytest.raises(ValueError, match="missing job report"):
        bridge.bridge_cell(bad, out, str(splits))
    # Run-id mismatch across chain.
    rep3 = tmp_path / "j3.json"
    rep3.write_text(json.dumps({"run_id": "other", "status": "COMPLETE",
                                "booked": {}, "events": {}}))
    bad = dict(cell, jobs=[{"report": cell["jobs"][0]["report"]},
                           {"report": str(rep3)}])
    with pytest.raises(ValueError, match="run-id mismatch"):
        bridge.bridge_cell(bad, out, str(splits))
    # Duplicate execution ids.
    ckpt2 = tmp_path / "ckpt2"
    (ckpt2 / "work").mkdir(parents=True)
    (ckpt2 / "bench_checkpoint.json").write_text(
        (Path(cell["ckpt_dir"]) / "bench_checkpoint.json").read_text())
    dup = {"event": "fill", "exec_id": "e0", "client_id": "c0",
           "symbol": "ETHUSDT", "venue_side": "LONG", "qty": 1.0,
           "price": 100.0, "fee": 0.0, "ts_utc": "2026-09-12T00:00:00+00:00"}
    (ckpt2 / "work" / "engine_journal.jsonl").write_text(
        json.dumps(dup) + "\n" + json.dumps(dup) + "\n")
    bad = dict(cell, ckpt_dir=str(ckpt2))
    with pytest.raises(ValueError, match="duplicate execution_ids"):
        bridge.bridge_cell(bad, out, str(splits))
    # Duplicate manifest cell.
    manifest = {"cells": [cell, dict(cell)]}
    man_path = tmp_path / "man.json"
    man_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="duplicate manifest cell"):
        bridge.bridge(str(man_path), str(out), str(splits))
