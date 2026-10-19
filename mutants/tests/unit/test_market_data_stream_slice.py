"""Observed streaming-slice fixture tests (Worker 2, E-006). No network.

The slice is a verbatim 400-event prefix of the cap-30min capture
(data/observed/stream_cap-30min_slice400_events.jsonl), pinned by hash so any
modification fails loudly. It exercises the replay path on real venue data:
determinism, arrival-order identity, provenance labels, and attributed bar
rebuilds. Full-run agreement (1.13M events) is proven by the bulk evidence,
not here.
"""
import json
from pathlib import Path

from cryptobot.market_data.bars import Bar1s, BarAggregator, BarMissing, to_s1_bar
from cryptobot.market_data.events import CHANNELS
from cryptobot.market_data.replayer import events_hash, load_events, replay_events

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
