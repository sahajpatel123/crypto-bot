"""Observed streaming-slice fixture tests (Worker 2, E-006). No network.

The slice is a verbatim 400-event prefix of the cap-30min capture
(data/observed/stream_cap-30min_slice400_events.jsonl), pinned by hash so any
modification fails loudly. It exercises the replay path on real venue data:
determinism, arrival-order identity, provenance labels, attributed bar
rebuilds, and streaming/list replay equivalence (the bulk path must hash
byte-identically to the list path). Full-run agreement (1.13M events) is
proven by the bulk evidence, not here.
"""
import json
from pathlib import Path

import pytest

from cryptobot.market_data.bars import Bar1s, BarAggregator, BarMissing, to_s1_bar
from cryptobot.market_data.events import CHANNELS
from cryptobot.market_data.replayer import (
    events_hash,
    iter_events,
    load_events,
    replay_events,
    streaming_events_hash,
)

ROOT = Path(__file__).resolve().parents[2]
SLICE = ROOT / "data/observed/stream_cap-30min_slice400_events.jsonl"
MANIFEST = ROOT / "data/observed/stream_cap-30min_manifest.json"
REPORT = ROOT / "data/observed/stream_cap-30min_report.json"
SLICE_SHA256 = "1f17343c28558f98e7aa251258afb1995752e2a5f38a698aa961d8df7ff5ec88"


def test_slice_replay_is_deterministic_and_pinned():
    records = load_events(SLICE)
    assert len(records) == 400
    assert events_hash(records) == SLICE_SHA256
    assert events_hash(load_events(SLICE)) == SLICE_SHA256  # independent reload.


def test_slice_arrival_order_matches_file_order():
    records = load_events(SLICE)
    assert [e["seq"] for e in replay_events(records)] == [r["seq"] for r in records]
    assert [r["seq"] for r in records] == list(range(1, 401))  # arrival prefix.


def test_slice_records_carry_full_provenance():
    records = load_events(SLICE)
    seen = set()
    for record in records:
        assert record["input_class"] == "observed-public"
        assert record["format"] == "cryptobot-events/1"
        assert record["run_id"] == "cap-30min"
        assert record["channel"] in CHANNELS
        assert record["exchange_ts_ms"] > 0 and record["local_recv_ms"] > 0
        seen.add((record["channel"], record["symbol"]))
    assert {s for _, s in seen} == {"BTCUSDT", "ETHUSDT"}
    assert len(seen) == 8  # all channel/symbol streams present in the prefix.


def test_slice_rebuilds_attributed_windows():
    records = load_events(SLICE)
    aggregators: dict[str, BarAggregator] = {}
    closed: list = []
    for event in replay_events(records):
        agg = aggregators.setdefault(event["symbol"], BarAggregator(event["symbol"]))
        if event["channel"] == "aggTrade":
            closed.extend(agg.on_trade(event))
        elif event["channel"] == "bookTicker":
            payload = event["payload"]
            agg.on_bbo(payload["bid"], payload["ask"], event["exchange_ts_ms"])
    for agg in aggregators.values():
        closed.extend(agg.flush())
    assert closed, "the observed prefix must close windows"
    for bar in closed:
        assert isinstance(bar, (Bar1s, BarMissing))
        assert bar.symbol in ("BTCUSDT", "ETHUSDT")
        assert bar.window_start_ms > 0
        to_s1_bar(bar)  # conversion must never raise on observed rebuilds.


def _rebuild_windows(record_iter):
    """Arrival-order bar rebuild; returns the (symbol, window, kind) set."""
    aggregators: dict[str, BarAggregator] = {}
    windows: set[tuple[str, int, str]] = set()

    def _note(symbol, closed):
        for bar in closed:
            kind = "missing" if isinstance(bar, BarMissing) else "bar"
            windows.add((symbol, bar.window_start_ms, kind))

    for event in record_iter:
        agg = aggregators.setdefault(event["symbol"], BarAggregator(event["symbol"]))
        if event["channel"] == "aggTrade":
            _note(event["symbol"], agg.on_trade(event))
        elif event["channel"] == "bookTicker":
            payload = event["payload"]
            agg.on_bbo(payload["bid"], payload["ask"], event["exchange_ts_ms"])
    for symbol, agg in aggregators.items():
        _note(symbol, agg.flush())
    return windows


def test_streaming_hash_matches_pinned_list_hash():
    digest, count = streaming_events_hash(SLICE, expect_class="observed-public")
    assert (digest, count) == (SLICE_SHA256, 400)
    again, _ = streaming_events_hash(SLICE, expect_class="observed-public")
    assert again == digest  # independent second pass.


def test_streaming_rebuild_matches_list_rebuild():
    assert _rebuild_windows(iter_events(SLICE)) == _rebuild_windows(
        replay_events(load_events(SLICE))
    )


def test_streaming_rejects_unordered_and_mislabeled_files(tmp_path):
    ordered = tmp_path / "ordered.jsonl"
    ordered.write_text(
        '{"seq": 1, "input_class": "observed-public"}\n'
        '{"seq": 2, "input_class": "observed-public"}\n'
    )
    assert streaming_events_hash(ordered, expect_class="observed-public")[1] == 2
    swapped = tmp_path / "swapped.jsonl"
    swapped.write_text(
        '{"seq": 2, "input_class": "observed-public"}\n'
        '{"seq": 1, "input_class": "observed-public"}\n'
    )
    with pytest.raises(ValueError, match="not arrival-ordered"):
        streaming_events_hash(swapped, expect_class="observed-public")
    with pytest.raises(ValueError, match="input_class mismatch"):
        streaming_events_hash(ordered, expect_class="synthetic")
    broken = tmp_path / "broken.jsonl"
    broken.write_text('{"seq": 1, "input_class": "observed-public"}\nnot json\n')
    with pytest.raises(ValueError, match="line 2"):
        streaming_events_hash(broken, expect_class="observed-public")


def test_manifest_and_report_agree_on_the_run():
    manifest = json.loads(MANIFEST.read_text())
    report = json.loads(REPORT.read_text())
    assert manifest["run_id"] == "cap-30min" == report["run_id"]
    assert manifest["input_class"] == "observed-public"
    assert manifest["symbols"] == ["BTCUSDT", "ETHUSDT"] == report["symbols"]
    assert set(manifest["files"]) == {"raw", "events", "bars"}
    assert all(len(v["sha256"]) == 64 for v in manifest["files"].values())
    assert report["stop_reason"] == "duration-reached"
    assert report["events_total"] == 1129445
    assert report["disconnects"] == {"natural": 0, "injected": 1}
    assert report["latency_claim_boundary"].startswith("REST RTT, event age")
