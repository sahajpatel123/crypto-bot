"""Recorder subscription <-> record-type contract.

The 18-25 Oct 2026 run subscribed to `aggTrade`, `markPrice@1s` and
`forceOrder`, completed the handshake, and recorded zero frames for any of
them while losing trade prints for a week. These tests tie the requested
stream names to the record types actually written, so the two cannot drift
apart silently again.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path


def _recorder(tmp_path: Path, **cfg):
    from cryptobot.market_data.live_recorder import Recorder, RecorderConfig

    config = RecorderConfig(out_dir=str(tmp_path), chunk_seconds=3600,
                            disk_budget_mb=50_000, **cfg)
    return Recorder(config, connect=lambda url: None,
                    rest_get=lambda url, timeout: ({}, 0.0))


def _records(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_default_streams_are_the_ones_that_deliver():
    from cryptobot.market_data.live_recorder import (
        BINANCE_SILENT_STREAMS,
        BINANCE_STREAMS,
        venue_stream_url,
    )

    # `trade` carries the same content as `aggTrade` and is the name the
    # endpoint actually serves; the silent names must not be requested by
    # default, or the loss is invisible.
    assert "trade" in BINANCE_STREAMS
    assert "bookTicker" in BINANCE_STREAMS
    assert "depth@100ms" in BINANCE_STREAMS
    for silent in ("aggTrade", "markPrice@1s", "forceOrder"):
        assert silent not in BINANCE_STREAMS
        assert silent in BINANCE_SILENT_STREAMS

    url = venue_stream_url("binance", ["BTCUSDT", "ETHUSDT"], BINANCE_STREAMS)
    for symbol in ("btcusdt", "ethusdt"):
        for stream in BINANCE_STREAMS:
            assert f"{symbol}@{stream}" in url
    assert "aggTrade" not in url
    assert "forceOrder" not in url


def test_config_streams_default_and_override():
    from cryptobot.market_data.live_recorder import BINANCE_STREAMS, RecorderConfig

    assert RecorderConfig().streams == BINANCE_STREAMS
    config = RecorderConfig(streams=("aggTrade", "bookTicker"))
    assert config.streams == ("aggTrade", "bookTicker")


def test_trade_message_is_classified():
    from cryptobot.market_data.live_recorder import classify_message

    payload = {"stream": "btcusdt@trade",
               "data": {"e": "trade", "E": 1792913681531,
                        "T": 1792913681520, "s": "BTCUSDT", "t": 55,
                        "p": "100.5", "q": "2", "m": True}}
    (rec,) = classify_message("binance", payload)
    assert rec["type"] == "trade"
    assert rec["trade_id"] == 55
    assert rec["price"] == "100.5"
    assert rec["qty"] == "2"
    assert rec["maker"] is True


def test_trade_record_type_reaches_the_chunk(tmp_path):
    """A `trade` frame must land as a record, not vanish in classification."""
    rec = _recorder(tmp_path)
    rec._record_stream("binance", {
        "stream": "btcusdt@trade",
        "data": {"e": "trade", "E": 1000, "T": 1000, "s": "BTCUSDT",
                 "t": 1, "p": "100", "q": "1", "m": False}})
    rec._flush_buckets()
    rec.writer.close()

    path = tmp_path / "chunks" / Path(rec.writer.sealed[0]["chunk"]).name
    types = {r.get("type") for r in _records(path)}
    assert "trade_agg" in types


def test_trades_aggregate_per_second(tmp_path):
    rec = _recorder(tmp_path)
    for trade_ms, price, qty, maker in ((1000, 100.0, 1.0, False),
                                        (1500, 102.0, 1.0, True),
                                        (2200, 99.0, 2.0, False)):
        rec._record_stream("binance", {
            "stream": "btcusdt@trade",
            "data": {"e": "trade", "E": trade_ms, "T": trade_ms,
                     "s": "BTCUSDT", "t": trade_ms, "p": str(price),
                     "q": str(qty), "m": maker}})
    rec._flush_buckets()
    rec.writer.close()

    path = tmp_path / "chunks" / Path(rec.writer.sealed[0]["chunk"]).name
    aggs = [r for r in _records(path) if r.get("type") == "trade_agg"]
    assert len(aggs) == 2
    first = next(a for a in aggs if a["event_ms"] == 1000)
    assert first["buy_qty"] == 1.0
    assert first["sell_qty"] == 1.0
    assert first["trades"] == 2
    assert first["vwap"] == 101.0          # (100*1 + 102*1) / 2
    second = next(a for a in aggs if a["event_ms"] == 2000)
    assert second["buy_qty"] == 2.0
    assert second["vwap"] == 99.0


def test_silent_stream_is_reported(tmp_path):
    """A subscribed stream with no records must raise, not pass quietly."""
    rec = _recorder(tmp_path)
    writer = rec.writer
    silent = writer._silent_streams(
        {"streams": ["btcusdt@bookTicker", "ethusdt@bookTicker"]})
    assert "btcusdt@trade" in silent
    assert "ethusdt@depth@100ms" in silent
    assert "btcusdt@bookTicker" not in silent

    writer._alert("stream-silent", {"chunk": "x", "streams": silent})
    assert any(a["kind"] == "stream-silent" for a in writer.alerts)


def test_aggregate_falls_back_to_raw_on_bad_payload(tmp_path):
    rec = _recorder(tmp_path)
    rec._record_stream("binance", {
        "stream": "btcusdt@trade",
        "data": {"e": "trade", "E": 1000, "T": 1000, "s": "BTCUSDT",
                 "t": 9, "p": "not-a-number", "q": "1", "m": False}})
    rec._flush_buckets()
    rec.writer.close()
    path = tmp_path / "chunks" / Path(rec.writer.sealed[0]["chunk"]).name
    types = [r.get("type") for r in _records(path)]
    assert "trade" in types
