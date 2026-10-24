"""Streaming replay tests (Worker 1, W1-24H). O(1)-memory replayer + report stats."""
import json
from pathlib import Path

import pytest

from cryptobot.app.config import load_config
from cryptobot.app.session import Session
from cryptobot.app.store import RunStore
from cryptobot.market_data.replayer import (
    RollingEventHash,
    events_hash,
    iter_events,
    load_events,
    replay_events,
    stream_events,
)

CLASS = "synthetic-test"
T0 = 1_700_000_000_000


def _evt(seq, ts, channel="aggTrade", cls=CLASS):
    return {"v": 1, "format": "cryptobot-events/1", "input_class": cls,
            "source": "synthetic", "route": "test", "run_id": "t",
            "seq": seq, "channel": channel, "symbol": "BTCUSDT",
            "exchange_ts_ms": ts, "local_recv_ms": ts,
            "local_mono_ns": seq, "gap_kind": None, "venue_seq": seq,
            "payload": {"agg_id": seq, "price": 100.0, "qty": 1.0,
                        "buyer_is_maker": False}}


def _write(path: Path, events) -> Path:
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n",
                    encoding="utf-8")
    return path


def test_stream_matches_load_sort(tmp_path):
    events = [_evt(3, T0 + 300), _evt(1, T0 + 100), _evt(2, T0 + 200)]
    ordered = [_evt(1, T0 + 100), _evt(2, T0 + 200), _evt(3, T0 + 300)]
    path = _write(tmp_path / "events.jsonl", ordered)
    assert list(stream_events(path)) == list(replay_events(load_events(path)))
    assert list(stream_events(path)) == ordered
    # Unordered input: legacy sorts, streaming raises (enforce, not reorder).
    _write(tmp_path / "events.jsonl", events)
    assert [e["seq"] for e in replay_events(load_events(path))] == [1, 2, 3]
    with pytest.raises(ValueError, match="not arrival-ordered"):
        list(stream_events(path))


def test_stream_enforces_exchange_ts_order(tmp_path):
    ok = [_evt(1, T0 + 100), _evt(2, T0 + 100), _evt(3, T0 + 200)]
    path = _write(tmp_path / "events.jsonl", ok)
    assert [e["seq"] for e in stream_events(path, order="exchange_ts")] == [1, 2, 3]
    bad = [_evt(1, T0 + 200), _evt(2, T0 + 100)]
    _write(tmp_path / "events.jsonl", bad)
    with pytest.raises(ValueError, match="not exchange_ts-ordered"):
        list(stream_events(path, order="exchange_ts"))
    # Same file is fine under arrival order (seq enforced, ts free).
    assert [e["seq"] for e in stream_events(path)] == [1, 2]


def test_stream_rejects_unknown_order_and_missing_label(tmp_path):
    path = _write(tmp_path / "events.jsonl", [_evt(1, T0)])
    with pytest.raises(ValueError, match="unknown replay order"):
        list(stream_events(path, order="wallclock"))
    bad = _evt(1, T0)
    del bad["input_class"]
    _write(tmp_path / "events.jsonl", [bad])
    with pytest.raises(ValueError, match="input_class"):
        list(stream_events(path))
    with pytest.raises(ValueError, match="input_class"):
        list(iter_events(path))


def test_stream_is_incremental_not_bulk(tmp_path):
    # A corrupt tail line must not break reading the head: proof the
    # reader never slurps the file before yielding.
    path = tmp_path / "events.jsonl"
    path.write_text(json.dumps(_evt(1, T0)) + "\nNOT-JSON\n", encoding="utf-8")
    stream = stream_events(path)
    assert next(stream)["seq"] == 1
    with pytest.raises(ValueError):
        list(stream)


def test_rolling_hash_equals_events_hash(tmp_path):
    events = [_evt(i, T0 + i * 100) for i in range(1, 51)]
    path = _write(tmp_path / "events.jsonl", events)
    rolling = RollingEventHash()
    for event in stream_events(path):
        rolling.update(event)
    assert rolling.count == 50
    assert rolling.hexdigest() == events_hash(load_events(path))
    # Order-sensitive: same events reversed hash differently (legacy too).
    rev = RollingEventHash()
    for event in events[::-1]:
        rev.update(event)
    assert rev.hexdigest() != rolling.hexdigest()


def _session(tmp_path: Path):
    text = open("configs/paper.toml").read()
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    cfg_path = tmp_path / "test.toml"
    cfg_path.write_text(text)
    cfg = load_config(cfg_path)
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    return Session(cfg, store, tmp_path / "runs" / "sess-test", "sess-test"), store


def test_run_replay_report_carries_stream_stats(tmp_path):
    session, store = _session(tmp_path)
    try:
        cap = tmp_path / "cap"
        cap.mkdir()
        events = [_evt(i, T0 + i * 1000) for i in range(1, 8)]
        _write(cap / "events.jsonl", events)
        report = session.run_replay(cap, expect_class=CLASS)
        stream = report["replay_stream"]
        assert stream["mode"] == "streaming-v1"
        assert stream["events_hashed"] == 7
        assert stream["events_hash"] == events_hash(events)
        assert stream["skipped_prefix"] == 0
        assert stream["first_ms"] == T0 + 1000
        assert stream["last_ms"] == T0 + 7000
        assert report["events_seen"] == 7
    finally:
        store.close()


def test_run_replay_empty_capture_raises(tmp_path):
    session, store = _session(tmp_path)
    try:
        cap = tmp_path / "cap"
        cap.mkdir()
        (cap / "events.jsonl").write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="no events"):
            session.run_replay(cap, expect_class=CLASS)
    finally:
        store.close()


def test_run_replay_resume_hash_covers_full_stream(tmp_path):
    session, store = _session(tmp_path)
    try:
        cap = tmp_path / "cap"
        cap.mkdir()
        events = [_evt(i, T0 + i * 1000) for i in range(1, 8)]
        _write(cap / "events.jsonl", events)
        with pytest.raises(RuntimeError, match="test-hook crash"):
            session.run_replay(cap, expect_class=CLASS, crash_after=3)
        store2 = RunStore(tmp_path / "runs" / "cryptobot.db")
        resumed = Session(session.config, store2,
                          tmp_path / "runs" / "sess-test", "sess-test")
        try:
            report = resumed.run_replay(cap, expect_class=CLASS, resume=True)
        finally:
            store2.close()
        # Hash covers the whole stream incl. the skipped prefix, so a
        # resumed run carries the same stream hash as a fresh run.
        assert report["replay_stream"]["events_hashed"] == 7
        assert report["replay_stream"]["events_hash"] == events_hash(events)
        assert report["replay_stream"]["skipped_prefix"] == 3
    finally:
        store.close()
