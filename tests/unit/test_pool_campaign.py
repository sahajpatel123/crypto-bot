"""pool_campaign unit tests (manager-owned, self-contained)."""
from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "pool_campaign", REPO / "tools" / "pool_campaign.py")
assert SPEC and SPEC.loader
pool_campaign = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pool_campaign)


def _ev(seq, ts):
    return {"v": 1, "format": "cryptobot-events/1", "seq": seq,
            "channel": "aggTrade", "symbol": "BTCUSDT",
            "exchange_ts_ms": ts, "payload": {"price": 100.0}}


def test_pool_orders_time_reseqs_and_skips(tmp_path):
    import sys
    camp = tmp_path / "camp"
    c0 = camp / "chunk-000"
    c0.mkdir(parents=True)
    with gzip.open(c0 / "events.jsonl.gz", "wt") as fh:
        for i in range(1200):
            fh.write(json.dumps(_ev(i, 2000 + i)) + "\n")
    (c0 / "SETTLED.json").write_text("{}")
    c1 = camp / "chunk-001"
    c1.mkdir(parents=True)
    with open(c1 / "events.jsonl", "w") as fh:
        for i in range(1200):
            fh.write(json.dumps(_ev(i, 1000 + i)) + "\n")
    (c1 / "SETTLED.json").write_text("{}")
    c2 = camp / "chunk-002"  # unsettled -> skipped
    c2.mkdir(parents=True)
    with open(c2 / "events.jsonl", "w") as fh:
        fh.write(json.dumps(_ev(1, 9000)) + "\n")
    argv, sys.argv = sys.argv, ["pool", "--campaign", str(camp),
                               "--out", str(tmp_path / "pooled")]
    try:
        assert pool_campaign.main() == 0
    finally:
        sys.argv = argv
    lines = (tmp_path / "pooled" / "events.jsonl").read_text().splitlines()
    assert len(lines) == 2400
    ts = [json.loads(line)["exchange_ts_ms"] for line in lines]
    assert ts == sorted(ts)
    seq = [json.loads(line)["seq"] for line in lines]
    assert seq == list(range(1, 2401))
    manifest = json.loads((tmp_path / "pooled" / "manifest.json").read_text())
    assert manifest["events_total"] == 2400
    assert any("chunk-002" in s for s in manifest["chunks_skipped"])
