"""Data-use audit tests: hash chains, capture completeness, preflight."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from cryptobot.data_assets import (
    _capture,
    chain_problems,
    verify_benchmark_inputs,
)


def _write_jsonl(path: Path, rows: int) -> None:
    path.write_text(
        "".join(json.dumps({"v": 1, "i": i}) + "\n" for i in range(rows)),
        encoding="utf-8",
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _chain() -> dict:
    entries = []
    prev = "genesis"
    for i in range(2):
        entry = {"n": i, "prev": prev}
        entry["entry_hash"] = hashlib.sha256(
            json.dumps(entry, sort_keys=True).encode()).hexdigest()
        entries.append(entry)
        prev = entry["entry_hash"]
    return {"entries": entries, "chain_head": prev}


def test_chain_problems_accepts_valid_chain() -> None:
    assert chain_problems(_chain()) == []


def test_chain_problems_detects_tampered_entry() -> None:
    doc = _chain()
    doc["entries"][0]["n"] = 99
    problems = chain_problems(doc)
    assert any("hash mismatch" in p for p in problems)


def test_chain_problems_detects_broken_head() -> None:
    doc = _chain()
    doc["chain_head"] = "0" * 64
    assert any("chain_head" in p for p in chain_problems(doc))


def _capture_manifest(root: Path, *, with_events: bool) -> dict:
    depth = root / "depth_snapshots.jsonl"
    _write_jsonl(depth, 3)
    files = {
        "depth_snapshots": {
            "path": str(depth),
            "bytes": depth.stat().st_size,
            "sha256": _sha(depth),
        }
    }
    events = root / "events.jsonl"
    if with_events:
        _write_jsonl(events, 5)
    files["events"] = {
        "path": str(events),
        "bytes": events.stat().st_size if events.exists() else 999,
        "sha256": _sha(events) if events.exists() else "0" * 64,
    }
    return {
        "run_id": "test-capture",
        "input_class": "observed-public",
        "symbols": ["BTCUSDT"],
        "files": files,
    }


def test_capture_complete_is_ok(tmp_path: Path) -> None:
    root = tmp_path / "capture"
    root.mkdir()
    (root / "manifest.json").write_text(
        json.dumps(_capture_manifest(root, with_events=True)), encoding="utf-8")
    asset = _capture("test_capture", root, repo=tmp_path, full=True)
    assert asset["status"] == "OK", asset
    assert asset["details"]["depth_rows"] == 3
    assert asset["consumer"] == "tools/score_h1_capture.py"


def test_capture_missing_bulk_is_partial(tmp_path: Path) -> None:
    root = tmp_path / "capture"
    root.mkdir()
    (root / "manifest.json").write_text(
        json.dumps(_capture_manifest(root, with_events=False)), encoding="utf-8")
    asset = _capture("test_capture", root, repo=tmp_path, full=True)
    assert asset["status"] == "PARTIAL", asset
    assert any("missing events" in p for p in asset["problems"])
    assert "bulk events not retained" in asset["consumer"]


def test_benchmark_preflight_fails_closed(tmp_path: Path) -> None:
    result = verify_benchmark_inputs(tmp_path)
    assert result["ok"] is False
    assert result["sources"] == 0
    assert result["problems"]
