"""Frozen-dataset reader tests (W2, E-008; B5). Fixture manifests only."""
import json

import pytest

pyarrow = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")
pa = pytest.importorskip("pyarrow")

from cryptobot.market_data.datasets import open_dataset  # noqa: E402

DAY = "2026-09-12"
T0MS = 1_789_171_200_000  # 2026-09-12T00:00:00Z.


def _write_vision(tmp_path):
    root = tmp_path / "ds"
    agg = root / "cache" / "symbol=BTCUSDT" / f"date={DAY}" / "channel=aggTrade"
    mark = root / "cache" / "symbol=BTCUSDT" / f"date={DAY}" / "channel=markPrice"
    agg.mkdir(parents=True)
    mark.mkdir(parents=True)
    pq.write_table(pa.table({
        "ts_ms": [T0MS + 2, T0MS + 5, T0MS + 3_200],
        "agg_id": [10, 11, 12], "price": [60000.0, 60001.0, 60002.0],
        "qty": [0.5, 0.25, 1.0], "first_id": [10, 11, 12],
        "last_id": [10, 11, 12],
        "buyer_is_maker": [False, True, False],
    }), str(agg / "part.parquet"))
    pq.write_table(pa.table({
        "ts_ms": [T0MS, T0MS + 60_000],
        "mark": [59999.0, 60003.0],
        "funding_rate": [0.0001, 0.0001],
        "next_funding_ms": [T0MS + 28_800_000, T0MS + 28_800_000],
    }), str(mark / "part.parquet"))
    (root / "benchmark_30d.toml").write_text("\n".join([
        "[dataset]",
        'name = "fixture-30d"',
        'kind = "vision-archive"',
        "manifest_version = 1",
        'window_utc = ["2026-09-12", "2026-09-12"]',
        'symbols = ["BTCUSDT"]',
        "",
        "[[source]]",
        'symbol = "BTCUSDT"',
        f'day = "{DAY}"',
        'channel = "aggTrade"',
        'url = "https://example.invalid/agg.zip"',
        'sha256 = "aa"',
        f'local = "cache/symbol=BTCUSDT/date={DAY}/channel=aggTrade/part.parquet"',
        "rows = 3",
        "",
        "[[source]]",
        'symbol = "BTCUSDT"',
        f'day = "{DAY}"',
        'channel = "markPrice"',
        'url = "https://example.invalid/mark.zip"',
        'sha256 = "bb"',
        f'local = "cache/symbol=BTCUSDT/date={DAY}/channel=markPrice/part.parquet"',
        "rows = 2",
        "",
        "[[gap]]",
        'symbol = "BTCUSDT"',
        f'day = "{DAY}"',
        f"start_ms = {T0MS + 5}",
        f"end_ms = {T0MS + 3_200}",
        'reason = "no-trades-300s+"',
        "",
        "[filters]",
        'profile = "frozen-assumed"',
        "",
        "[filters.symbols.BTCUSDT]",
        "tick = 0.1",
        "step = 0.001",
        "min_qty = 0.001",
        "min_notional = 5.0",
        "",
    ]))
    return root / "benchmark_30d.toml"


def test_vision_events_merge_channels_with_heartbeats(tmp_path):
    handle = open_dataset(_write_vision(tmp_path))
    items = list(handle.events("BTCUSDT", DAY))
    events = [e for e in items if e is not None]
    beats = [e for e in items if e is None]
    # Merged by ts: mark@0, agg@+2, agg@+5, agg@+3200, mark@+60000.
    assert [e["channel"] for e in events] == [
        "markPrice", "aggTrade", "aggTrade", "aggTrade", "markPrice"]
    assert [e["seq"] for e in events] == [1, 2, 3, 4, 5]
    assert all(e["run_id"].startswith("replay:") for e in events)
    assert all(e["input_class"] == "observed-archive" for e in events)
    assert all(e["route"] == "market" for e in events)
    assert events[1]["payload"]["price"] == 60000.0
    assert events[1]["payload"]["buyer_is_maker"] is False
    assert events[1]["venue_seq"] == 10
    assert events[0]["payload"]["funding_rate"] == pytest.approx(0.0001)
    assert events[0]["venue_seq"] is None
    # Idle virtual seconds surface as None (B3): +5..+3200 and +3200..+60000.
    assert len(beats) == 2 + 57
    assert items[0] is not None  # no leading heartbeat before the first event.


def test_coverage_and_manifest_sha(tmp_path):
    handle = open_dataset(_write_vision(tmp_path))
    assert len(handle.manifest_sha()) == 64
    assert handle.manifest_sha() == handle.manifest_sha()  # stable.
    coverage = handle.coverage()
    assert coverage["kind"] == "vision-archive"
    assert coverage["manifest_sha"] == handle.manifest_sha()
    assert len(coverage["sources"]) == 2
    assert all(s["local_exists"] for s in coverage["sources"])
    assert coverage["gaps"][0]["reason"] == "no-trades-300s+"
    assert coverage["filters"]["profile"] == "frozen-assumed"


def test_unknown_kind_and_version_rejected(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text('[dataset]\nkind = "nope"\nmanifest_version = 1\n')
    with pytest.raises(ValueError, match="unknown dataset kind"):
        open_dataset(bad)
    bad.write_text('[dataset]\nkind = "vision-archive"\nmanifest_version = 99\n')
    with pytest.raises(ValueError, match="manifest_version"):
        open_dataset(bad)


def _write_captured(tmp_path):
    root = tmp_path / "cap"
    run = root / "runs" / "r1"
    run.mkdir(parents=True)
    records = [
        {"channel": "aggTrade", "symbol": "BTCUSDT",
         "exchange_ts_ms": T0MS, "local_recv_ms": T0MS + 50,
         "input_class": "observed-public", "payload": {"price": 1.0}},
        {"channel": "bookTicker", "symbol": "BTCUSDT",
         "exchange_ts_ms": T0MS + 2_500, "local_recv_ms": T0MS + 2_550,
         "input_class": "observed-public", "payload": {"bid": 1.0}},
        {"channel": "aggTrade", "symbol": "ETHUSDT",
         "exchange_ts_ms": T0MS + 100, "local_recv_ms": T0MS + 150,
         "input_class": "observed-public", "payload": {"price": 2.0}},
    ]
    (run / "events.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n")
    (root / "captured.toml").write_text("\n".join([
        "[dataset]",
        'name = "fixture-captured"',
        'kind = "captured-runs"',
        "manifest_version = 1",
        'symbols = ["BTCUSDT", "ETHUSDT"]',
        "",
        "[[source]]",
        'run_id = "r1"',
        'file = "events.jsonl"',
        'local = "runs/r1/events.jsonl"',
        'sha256 = "cc"',
        "rows = 3",
        'channels = ["aggTrade", "bookTicker"]',
        'symbols = ["BTCUSDT", "ETHUSDT"]',
        "",
    ]))
    return root / "captured.toml"


def test_captured_events_stream_symbol_day_with_heartbeats(tmp_path):
    handle = open_dataset(_write_captured(tmp_path))
    items = list(handle.events("BTCUSDT", DAY))
    events = [e for e in items if e is not None]
    assert len(events) == 2  # ETH record filtered out.
    assert [e["seq"] for e in events] == [1, 2]
    assert all(e["run_id"].startswith("replay:") for e in events)
    assert sum(1 for e in items if e is None) == 2  # 2 idle seconds in 2500 ms.
    assert handle.coverage()["sources"][0]["local_exists"] is True
