"""Book-imbalance scan tests (retained recorder diagnostic)."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

from cryptobot.research.book_scan import (
    scan_recorder,
    scan_records,
    snapshot_imbalance,
)


def _snap(symbol: str, bids: list[list[float]], asks: list[list[float]],
          ts: int = 1) -> dict:
    return {"type": "depth_snapshot", "symbol": symbol, "event_ms": ts,
            "bids": bids, "asks": asks}


def test_snapshot_imbalance_known_values() -> None:
    # bid notional 5,000 vs ask 505 -> strongly positive.
    positive = _snap("BTCUSDT", [[100.0, 10.0]] * 5, [[101.0, 1.0]] * 5)
    assert snapshot_imbalance(positive) > 0.8
    # Reversed -> strongly negative.
    negative = _snap("ETHUSDT", [[100.0, 1.0]] * 5, [[101.0, 10.0]] * 5)
    assert snapshot_imbalance(negative) < -0.8
    # Empty book is unavailable, never zero-filled.
    assert snapshot_imbalance({"bids": [], "asks": []}) is None


def test_scan_counts_threshold_breaches() -> None:
    records = [
        _snap("BTCUSDT", [[100.0, 10.0]] * 5, [[101.0, 1.0]] * 5),
        _snap("BTCUSDT", [[100.0, 5.0]] * 5, [[101.0, 5.0]] * 5),
        _snap("ETHUSDT", [[100.0, 1.0]] * 5, [[101.0, 10.0]] * 5),
        {"type": "book_ticker", "bids": [[1, 1]], "asks": [[2, 1]]},
    ]
    report = scan_records(records, threshold=0.6)
    assert report["snapshots"] == 3
    assert report["total"]["n"] == 3
    assert report["total"]["signals"] == 2
    assert report["per_symbol"]["BTCUSDT"]["signals"] == 1
    assert report["per_symbol"]["ETHUSDT"]["signals"] == 1


def test_scan_recorder_reads_gzip_chunks(tmp_path: Path) -> None:
    root = tmp_path / "recorder"
    (root / "chunks").mkdir(parents=True)
    rows = [
        _snap("BTCUSDT", [[100.0, 10.0]] * 5, [[101.0, 1.0]] * 5),
        {"type": "book_ticker", "symbol": "BTCUSDT"},
    ]
    with gzip.open(root / "chunks" / "rec-000000-test.jsonl.gz", "wt") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    report = scan_recorder(root, threshold=0.6)
    assert report["chunks"] == 1
    assert report["total"]["n"] == 1
    assert report["total"]["signals"] == 1
    assert report["diagnostic"] is True
    assert report["not_a_verdict"] is True
