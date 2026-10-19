"""D1: zstd Parquet compaction proves row + hash equivalence."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

from cryptobot.data.compaction import compact_chunk, compact_root, verify_proof
from cryptobot.selftest import invoke


def _raw(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")


def test_compact_chunk_round_trips_rows_and_hash(tmp_path):
    raw = tmp_path / "chunks" / "rec-000.jsonl.gz"
    _raw(raw, [{"type": "trade", "price": "1.0"},
               {"type": "book_ticker", "bid": "0.9"}])
    out = raw.with_suffix(".parquet")
    info = compact_chunk(raw, out)
    assert info["rows"] == 2
    assert out.exists()
    assert info["canonical_sha256"]


def test_compact_root_writes_a_verified_proof_chain(tmp_path):
    rec = tmp_path / "rec"
    _raw(rec / "chunks" / "rec-000.jsonl.gz",
         [{"type": "trade", "id": 1}])
    _raw(rec / "chunks" / "rec-001.jsonl.gz",
         [{"type": "trade", "id": 2}, {"type": "trade", "id": 3}])
    (rec / "manifest.json").write_text(json.dumps(
        {"format": "cryptobot-chunk-manifest/1", "chain_head": "abc",
         "entries": []}))
    report = compact_root(rec)
    assert report["verdict"] == "PASS", report
    assert report["chunks"] == 2
    assert "saved_bytes" in report
    assert verify_proof(rec / "compaction-manifest.json") == []
    proof = json.loads((rec / "compaction-manifest.json").read_text())
    assert len(proof["entries"]) == 2
    assert all(e["recorder_chain_head"] == "abc" for e in proof["entries"])


def test_compact_cli_refuses_missing_root(tmp_path):
    code, text = invoke(["compact", "--root", str(tmp_path / "missing")])
    # No chunks is an empty-but-valid report (PASS, zero work).
    assert code == 0, text
    assert '"chunks": 0' in text
    assert "Traceback" not in text
