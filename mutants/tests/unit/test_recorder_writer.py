"""DurableWriter tests: rotation, fsync batching, overflow, chain, gzip.

Offline only (tmp_path + monkeypatched fsync). No network.
"""
import gzip
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptobot.recorder.writer import DurableWriter, verify_manifest_chain


def _event(symbol="BTCUSDT", ts=1_000):
    return {"symbol": symbol, "channel": "aggTrade", "exchange_ts_ms": ts,
            "local_recv_ms": ts, "venue_seq": ts, "payload": {"agg_id": ts}}


def _entries(run_dir):
    manifest = Path(run_dir) / "manifest.jsonl"
    return [json.loads(line) for line in manifest.read_text().splitlines() if line.strip()]


def test_rotation_boundary_seals_hourly_chunks(tmp_path):
    writer = DurableWriter(tmp_path)
    writer.start()
    try:
        writer.append("aggTrade", _event(ts=100))
        assert writer.wait_idle()
        now = datetime.now(timezone.utc)
        later = now + timedelta(hours=2)
        writer.rotate_if_needed(later)
        assert writer.wait_idle()
        writer.append("aggTrade", _event(ts=200))
        assert writer.wait_idle()
    finally:
        writer.close()

    chunks_dir = tmp_path / "chunks"
    gz_files = sorted(chunks_dir.glob("*.jsonl.gz"))
    assert len(gz_files) == 2  # one sealed chunk per hour bucket.
    assert list(chunks_dir.glob("*.jsonl")) == []  # no live .jsonl left after close.
    entries = _entries(tmp_path)
    assert len(entries) == 2
    hours = {e["hour"] for e in entries}
    assert len(hours) == 2
    assert all(e["events"] == 1 for e in entries)
    assert verify_manifest_chain(tmp_path / "manifest.jsonl")["ok"]


def test_gzip_on_rotation_holds_verbatim_events(tmp_path):
    writer = DurableWriter(tmp_path)
    writer.start()
    try:
        writer.append("bookTicker", _event(symbol="ETHUSDT", ts=7))
        assert writer.wait_idle()
        writer.rotate_if_needed(datetime.now(timezone.utc) + timedelta(hours=3))
        assert writer.wait_idle()
    finally:
        writer.close()

    gz_files = sorted((tmp_path / "chunks").glob("ETHUSDT.bookTicker.*.jsonl.gz"))
    assert len(gz_files) == 1
    with gzip.open(gz_files[0], "rt", encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    assert rows == [_event(symbol="ETHUSDT", ts=7)]


def test_fsync_batching_counts_batches_plus_final(monkeypatch, tmp_path):
    calls = []
    real_fsync = os.fsync

    def counting_fsync(fd):
        calls.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", counting_fsync)
    writer = DurableWriter(tmp_path, fsync_every_n=10, fsync_every_s=3600.0)
    writer.start()
    try:
        for i in range(25):
            writer.append("aggTrade", _event(ts=i))
        assert writer.wait_idle()
    finally:
        writer.close()

    # Batches at events 10 and 20, one final chunk fsync + one manifest fsync.
    assert len(calls) == 4


def test_overflow_never_silent_counts_drops_flags_gap_and_logs(tmp_path, caplog):
    writer = DurableWriter(tmp_path, queue_size=3)
    with caplog.at_level(logging.WARNING, logger="cryptobot.recorder.writer"):
        for i in range(5):  # writer not started: queue cannot drain.
            writer.append("aggTrade", _event(ts=i))
    assert writer.dropped == 2
    assert any("overflow" in r.message for r in caplog.records)
    assert len(writer.gapped_intervals) == 1

    writer.start()
    try:
        assert writer.wait_idle()
    finally:
        writer.close()
    entries = _entries(tmp_path)
    assert len(entries) == 1
    assert entries[0]["gapped"] is True  # overflow hour flagged in the manifest.
    assert entries[0]["events"] == 3  # only the 3 queued events persisted.


def test_hash_chain_verifies_and_detects_tamper(tmp_path):
    writer = DurableWriter(tmp_path)
    writer.start()
    try:
        writer.append("aggTrade", _event(ts=1))
        writer.append("aggTrade", _event(ts=2))
        assert writer.wait_idle()
    finally:
        writer.close()

    manifest = tmp_path / "manifest.jsonl"
    clean = verify_manifest_chain(manifest)
    assert clean["ok"] and clean["entries"] == 1

    gz_files = sorted((tmp_path / "chunks").glob("*.jsonl.gz"))
    with gz_files[0].open("ab") as fh:
        fh.write(b"TAMPERED")
    tampered = verify_manifest_chain(manifest)
    assert not tampered["ok"]
    assert any("SHA mismatch" in e for e in tampered["errors"])


def test_chain_genesis_and_linkage(tmp_path):
    writer = DurableWriter(tmp_path)
    writer.start()
    try:
        writer.append("aggTrade", _event(ts=1))
        assert writer.wait_idle()
        writer.rotate_if_needed(datetime.now(timezone.utc) + timedelta(hours=5))
        assert writer.wait_idle()
        writer.append("aggTrade", _event(ts=2))
        assert writer.wait_idle()
    finally:
        writer.close()

    entries = _entries(tmp_path)
    assert entries[0]["prev_hash"] == "0" * 64  # genesis.
    assert entries[1]["prev_hash"] == entries[0]["entry_hash"]  # chained.
