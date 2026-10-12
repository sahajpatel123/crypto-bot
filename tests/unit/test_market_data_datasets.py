"""Frozen-dataset reader tests (W2, E-009; B5). Fixture manifests only."""
import hashlib
import json

import pytest

pyarrow = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")
pa = pytest.importorskip("pyarrow")

from cryptobot.market_data.datasets import (  # noqa: E402
    open_dataset,
    verify_dataset,
)

DAY = "2026-09-12"
T0MS = 1_789_171_200_000  # 2026-09-12T00:00:00Z.


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        # v2 causal schema: closes publish at close availability with
        # open/close/availability preserved; absent funding is NULL + status.
        "ts_ms": [T0MS + 59_999, T0MS + 119_999],
        "open_time": [T0MS, T0MS + 60_000],
        "close_time": [T0MS + 59_999, T0MS + 119_999],
        "mark": [59999.0, 60003.0],
        "open_px": [59998.0, 60000.0],
        "high_px": [60001.0, 60004.0],
        "low_px": [59997.0, 59999.0],
        "funding_rate": [0.0001, None],
        "funding_status": ["sourced", "absent"],
        "next_funding_ms": [T0MS + 28_800_000, 0],
    }), str(mark / "part.parquet"))
    (root / "benchmark_30d.toml").write_text("\n".join([
        "[dataset]",
        'name = "fixture-30d"',
        'kind = "vision-archive"',
        "manifest_version = 1",
        "transform_version = 2",
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
        f'derived_sha256 = "{_sha(agg / "part.parquet")}"',
        "rows = 3",
        "",
        "[[source]]",
        'symbol = "BTCUSDT"',
        f'day = "{DAY}"',
        'channel = "markPrice"',
        'url = "https://example.invalid/mark.zip"',
        'sha256 = "bb"',
        f'local = "cache/symbol=BTCUSDT/date={DAY}/channel=markPrice/part.parquet"',
        f'derived_sha256 = "{_sha(mark / "part.parquet")}"',
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
    # Merged by ts: agg@+2, agg@+5, agg@+3200, mark@+59999, mark@+119999.
    assert [e["channel"] for e in events] == [
        "aggTrade", "aggTrade", "aggTrade", "markPrice", "markPrice"]
    assert [e["seq"] for e in events] == [1, 2, 3, 4, 5]
    assert all(e["run_id"].startswith("replay:") for e in events)
    assert all(e["input_class"] == "observed-archive" for e in events)
    assert all(e["route"] == "market" for e in events)
    assert events[0]["payload"]["price"] == 60000.0
    assert events[0]["payload"]["buyer_is_maker"] is False
    assert events[0]["venue_seq"] == 10
    mark = events[3]
    assert mark["exchange_ts_ms"] == T0MS + 59_999  # close availability, not open.
    assert mark["payload"]["open_time"] == T0MS
    assert mark["payload"]["close_time"] == T0MS + 59_999
    assert mark["payload"]["funding_rate"] == pytest.approx(0.0001)
    assert mark["payload"]["funding_status"] == "sourced"
    assert mark["venue_seq"] is None
    absent = events[4]
    assert absent["payload"]["funding_rate"] is None  # explicit, never zero.
    assert absent["payload"]["funding_status"] == "absent"
    # Idle virtual seconds surface as None (B3).
    assert len(beats) == 3 + 56 + 59
    assert items[0] is not None  # no leading heartbeat before the first event.


def test_vision_transform_v1_fails_closed(tmp_path):
    toml = _write_vision(tmp_path)
    toml.write_text(toml.read_text().replace("transform_version = 2",
                                             "transform_version = 1"))
    with pytest.raises(ValueError, match="stale vision transform"):
        open_dataset(toml)


def test_verify_dataset_checks_derived_hashes(tmp_path):
    toml = _write_vision(tmp_path)
    handle = open_dataset(toml)
    assert verify_dataset(handle) == []
    (tmp_path / "ds" / "cache" / "symbol=BTCUSDT" / f"date={DAY}"
     / "channel=aggTrade" / "part.parquet").write_bytes(b"corrupt")
    problems = verify_dataset(handle)
    assert len(problems) == 1 and "hash mismatch" in problems[0]


def _prepare():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path("datasets").resolve()))
    import prepare_benchmark_30d
    return prepare_benchmark_30d


def test_prepare_marks_publish_at_close_availability(tmp_path):
    prep = _prepare()
    rows = [["open_time", "open", "high", "low", "close", "close_time",
             "volume", "close_time_x", "quote_volume", "count",
             "taker_buy_volume", "taker_buy_quote_volume", "ignore"],
            ["1000000", "10.0", "11.0", "9.0", "10.5", "1059999",
             "0", "0", "0", "60", "0", "0", "0"]]
    [(open_ms, avail_ms, o, h, low, close)] = prep._convert_marks(rows)
    assert (open_ms, avail_ms) == (1_000_000, 1_059_999)  # never open+close.
    assert (o, h, low, close) == (10.0, 11.0, 9.0, 10.5)
    day = __import__("datetime").date(1970, 1, 1)
    grid = [(m * 60_000, m * 60_000 + 59_999, 10.0, 11.0, 9.0, 10.5)
            for m in range(1440) if m != 5]
    assert prep._missing_minutes(grid, day) == [5]  # grids on open_time.


def test_prepare_absent_funding_is_null_with_status(tmp_path):
    prep = _prepare()
    marks = [(100_000_000, 100_059_999, 10.0, 11.0, 9.0, 10.5),
             (200_000_000, 200_059_999, 10.5, 12.0, 10.0, 11.0)]
    fundings = [(1_000_000, 8, 0.0001)]  # last calc a day back: stale.
    dest = tmp_path / "mark.parquet"
    n, ts_min, ts_max, absent = prep._join_marks(marks, fundings, dest)
    assert (n, absent) == (2, True)
    table = pq.read_table(str(dest))
    assert table.column("ts_ms").to_pylist() == [100_059_999, 200_059_999]
    assert table.column("funding_rate").to_pylist() == [None, None]
    assert table.column("funding_status").to_pylist() == ["absent", "absent"]
    fresh = [(100_000_000, 8, 0.0002)]
    _, _, _, absent2 = prep._join_marks(marks, fresh, tmp_path / "m2.parquet")
    assert absent2 is True  # only the first mark is covered; no carry-forward.
    table2 = pq.read_table(str(tmp_path / "m2.parquet"))
    assert table2.column("funding_rate").to_pylist() == [0.0002, None]
    assert table2.column("funding_status").to_pylist() == ["sourced", "absent"]


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
