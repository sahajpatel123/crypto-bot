"""F3 recorder/vault tests. All payloads are SYNTHETIC fixtures."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest


def _write_chunk(path: Path, rows: list[dict], *,
                 input_class: str = "observed-public") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "header", "format": "test/1",
                             "input_class": input_class}) + "\n")
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return path


def test_manifest_chain_seals_and_detects_tamper(tmp_path):
    from cryptobot.market_data.live_recorder import ManifestChain

    a = _write_chunk(tmp_path / "a.jsonl.gz", [{"n": 1}])
    b = _write_chunk(tmp_path / "b.jsonl.gz", [{"n": 2}])
    chain = ManifestChain(tmp_path / "manifest.json")
    chain.seal(a, first_ms=1, last_ms=2, records=1, streams=["aggTrade"])
    chain.seal(b, first_ms=3, last_ms=4, records=1, streams=["aggTrade"])
    assert chain.verify() == []
    chain.doc["entries"][0]["records"] = 99
    problems = chain.verify()
    assert problems and "entry 0" in problems[0]
    assert any("hash mismatch" in p for p in problems)


def test_recorder_writer_overflow_is_counted_and_flagged(tmp_path):
    import queue as _queue

    from cryptobot.market_data.live_recorder import (ManifestChain,
                                                     RecorderConfig,
                                                     RecorderWriter)

    cfg = RecorderConfig(out_dir=str(tmp_path), queue_max=1)
    writer = RecorderWriter(cfg, manifest=ManifestChain(
        tmp_path / "manifest.json"))
    writer.queue = _queue.Queue(maxsize=1)
    writer.queue.put_nowait({"type": "held"})
    assert writer.submit({"type": "overflow"}) is False
    assert writer.dropped == 1
    assert writer.gapped is True
    assert writer.alerts[-1]["kind"] == "writer-queue-full"
    # Drain the held item so the writer thread can finish cleanly.
    writer.queue.get_nowait()
    writer.close()


def test_classify_binance_messages():
    from cryptobot.market_data.live_recorder import classify_message

    trade = classify_message("binance", {
        "stream": "btcusdt@aggTrade",
        "data": {"e": "aggTrade", "s": "BTCUSDT", "a": 7, "p": "100.5",
                 "q": "0.2", "E": 1000, "T": 999, "m": False}})
    assert trade[0]["type"] == "trade" and trade[0]["trade_id"] == 7
    depth = classify_message("binance", {
        "stream": "btcusdt@depth@100ms",
        "data": {"e": "depthUpdate", "s": "BTCUSDT", "U": 10, "u": 12,
                 "pu": 9, "b": [], "a": [], "E": 1001}})
    assert depth[0]["type"] == "depth" and depth[0]["first_id"] == 10
    mark = classify_message("binance", {
        "stream": "btcusdt@markPrice@1s",
        "data": {"e": "markPriceUpdate", "s": "BTCUSDT", "p": "101",
                 "i": "100.9", "r": "0.0001", "T": 2000, "E": 1002}})
    assert mark[0]["type"] == "mark"
    liq = classify_message("binance", {
        "stream": "btcusdt@forceOrder",
        "data": {"e": "forceOrder", "E": 1003,
                 "o": {"s": "BTCUSDT", "S": "SELL", "p": "99",
                       "q": "1"}}})
    assert liq[0]["type"] == "liquidation"


def test_venue_plugins_are_opt_in_and_addressable():
    from cryptobot.market_data.live_recorder import (
        subscription_messages, venue_stream_url)

    assert "binance.com/stream" in venue_stream_url(
        "binance", ["BTCUSDT"], ["aggTrade"])
    assert venue_stream_url("bybit", ["BTCUSDT"]).startswith("wss://")
    assert venue_stream_url("okx", ["BTCUSDT"]).startswith("wss://")
    assert "publicTrade.BTCUSDT" in subscription_messages(
        "bybit", ["BTCUSDT"])[0]
    assert "BTC-USDT-SWAP" in subscription_messages("okx", ["BTCUSDT"])[0]
    with pytest.raises(ValueError):
        venue_stream_url("unknown", ["BTCUSDT"])


def test_integrity_report_detects_gap_and_bad_chunk(tmp_path):
    from cryptobot.market_data.live_recorder import (
        ManifestChain, integrity_report)

    rows = [
        {"type": "trade", "stream": "aggTrade", "trade_id": 1,
         "event_ms": 1000, "symbol": "BTCUSDT"},
        {"type": "trade", "stream": "aggTrade", "trade_id": 4,
         "event_ms": 900, "symbol": "BTCUSDT"},
        {"type": "depth", "stream": "depth", "first_id": 20,
         "final_id": 22, "event_ms": 1100, "symbol": "BTCUSDT"},
        {"type": "depth", "stream": "depth", "first_id": 30,
         "final_id": 32, "event_ms": 1200, "symbol": "BTCUSDT"},
    ]
    chunk = _write_chunk(tmp_path / "c.jsonl.gz", rows)
    chain = ManifestChain(tmp_path / "manifest.json")
    chain.seal(chunk, first_ms=1, last_ms=2, records=len(rows),
               streams=["aggTrade", "depth"], gaps=0)
    report = integrity_report(tmp_path)
    assert report["ok"] is True
    assert report["records"] == len(rows)  # header is not a record
    stream = report["streams"]["aggTrade"]
    assert stream["trade_gaps"] == 1
    assert stream["out_of_order"] == 1
    assert report["streams"]["depth"]["depth_breaks"] == 1

    # Corrupt the chunk bytes: report must flag it, not crash.
    with open(chunk, "ab") as fh:
        fh.write(b"corrupt")
    broken = integrity_report(tmp_path)
    assert broken["ok"] is False
    assert broken["broken_chunks"]


def test_disk_budget():
    from cryptobot.market_data.live_recorder import (
        RecorderConfig, check_disk_budget)

    cfg = RecorderConfig(out_dir="/tmp/does-not-matter",
                         disk_budget_mb=100)
    assert check_disk_budget(cfg, free_mb=101)["ok"] is True
    assert check_disk_budget(cfg, free_mb=99)["ok"] is False
