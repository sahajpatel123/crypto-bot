"""#49 recorder inputs: settled funding + daily klines + restart hardening.

Every guard here ships with a deletion proof: the test fails if the guard is
removed (wrong default, missing quarantine, silent fallback, swallowed
OSError, frozen heartbeat). All REST traffic is injected fakes; nothing in
this file touches the network, the edge tree, or live state.
"""
from __future__ import annotations

import gzip
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

GRID_MS = 8 * 3600 * 1000
DAY_MS = 24 * 3600 * 1000


def _grid_base() -> int:
    return (1_760_000_000_000 // GRID_MS) * GRID_MS


def _records_of(root: Path) -> list[dict]:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    out: list[dict] = []
    for entry in manifest["entries"]:
        with gzip.open(root / entry["chunk"], "rt", encoding="utf-8") as fh:
            out.extend(json.loads(line) for line in fh if line.strip())
    return out


def _recorder(tmp_path: Path, **cfg):
    from cryptobot.market_data.live_recorder import Recorder, RecorderConfig

    handler = cfg.pop("_rest_handler", None)
    config = RecorderConfig(out_dir=str(tmp_path), chunk_seconds=3600,
                            disk_budget_mb=0, **cfg)
    calls: list[str] = []

    def fake_rest(url: str, timeout: float):
        calls.append(url)
        assert handler is not None, f"unexpected REST call: {url}"
        return handler(url), 0.0

    rec = Recorder(config, connect=lambda url: None, rest_get=fake_rest)
    return rec, calls


# -- P1: funding_settlements -------------------------------------------------


def test_funding_sweep_emits_new_settlements_only(tmp_path):
    from cryptobot.market_data.live_recorder import FUNDING_STREAM_TOKEN

    base = _grid_base()
    boot = base + 3_600_000
    settle_new = base + GRID_MS
    rows = [
        {"symbol": "BTCUSDT", "fundingTime": base, "fundingRate": "0.00010000"},
        {"symbol": "BTCUSDT", "fundingTime": settle_new,
         "fundingRate": "0.00012000"},
    ]
    rec, _ = _recorder(tmp_path, kline_symbols=("BTCUSDT",),
                       _rest_handler=lambda url: rows)
    try:
        rec._boot_ms = boot
        now_ms = settle_new + 60_000
        summary = rec._funding_sweep("binance", now_ms)
        assert summary["emitted"] == 1  # the pre-boot row is skipped
        repeat = rec._funding_sweep("binance", now_ms)
        assert repeat["emitted"] == 0  # high-water mark holds
    finally:
        rec.writer.close()
    funding = [r for r in _records_of(tmp_path)
               if r.get("type") == "funding_rate_settled"]
    assert len(funding) == 1
    rec_out = funding[0]
    assert rec_out["stream"] == FUNDING_STREAM_TOKEN
    assert rec_out["symbol"] == "BTCUSDT"
    assert rec_out["event_ms"] == settle_new
    assert rec_out["event_ms"] % GRID_MS == 0
    assert rec_out["grid_8h"] is True
    assert rec_out["universe_source"] == "explicit"
    assert float(rec_out["fundingRate"]) == pytest.approx(0.00012)
    assert isinstance(rec_out["event_ms"], int)
    # High-water persisted for the next process.
    state = json.loads((tmp_path / "funding_state.json").read_text())
    assert state == {"BTCUSDT": settle_new}


def test_funding_cold_start_skips_preboot_history(tmp_path):
    base = _grid_base()
    boot = base + 3_600_000
    rows = [{"symbol": "BTCUSDT", "fundingTime": base,
             "fundingRate": "0.00010000"}]
    rec, _ = _recorder(tmp_path, kline_symbols=("BTCUSDT",),
                       _rest_handler=lambda url: rows)
    try:
        rec._boot_ms = boot
        summary = rec._funding_sweep("binance", boot + 60_000)
        assert summary["emitted"] == 0
    finally:
        rec.writer.close()
    kinds = {r.get("type") for r in _records_of(tmp_path)}
    assert "funding_rate_settled" not in kinds


def test_funding_warm_restart_fills_downtime_gap(tmp_path):
    base = _grid_base()
    boot = base + 3_600_000
    # Previous process died right after the `base - GRID` settlement.
    (tmp_path / "funding_state.json").write_text(
        json.dumps({"BTCUSDT": base - GRID_MS}))
    rows = [
        {"symbol": "BTCUSDT", "fundingTime": base, "fundingRate": "0.00010000"},
        {"symbol": "BTCUSDT", "fundingTime": base + GRID_MS,
         "fundingRate": "0.00012000"},
    ]
    rec, _ = _recorder(tmp_path, kline_symbols=("BTCUSDT",),
                       _rest_handler=lambda url: rows)
    try:
        rec._boot_ms = boot
        summary = rec._funding_sweep("binance", base + GRID_MS + 60_000)
        assert summary["emitted"] == 2  # missed row + new row
    finally:
        rec.writer.close()


def test_funding_off_grid_row_kept_and_flagged(tmp_path):
    base = _grid_base()
    boot = base + 3_600_000
    off_grid = base + 3600_000  # 1 h after a settlement: 1h-interval symbol
    assert off_grid % GRID_MS != 0
    rows = [{"symbol": "BTCUSDT", "fundingTime": off_grid,
             "fundingRate": "0.00001000"}]
    rec, _ = _recorder(tmp_path, kline_symbols=("BTCUSDT",),
                       _rest_handler=lambda url: rows)
    try:
        rec._boot_ms = boot - 3600_000  # cold mark before the row
        summary = rec._funding_sweep("binance", off_grid + 60_000)
        assert summary["emitted"] == 1
        assert summary["off_grid"] == 1
        kinds = [a["kind"] for a in rec.writer.alerts]
        assert "funding-off-grid" in kinds
    finally:
        rec.writer.close()
    funding = [r for r in _records_of(tmp_path)
               if r.get("type") == "funding_rate_settled"]
    assert funding[0]["grid_8h"] is False


def test_n49_record_types_fill_d1_buckets():
    # Contract test: the recorder must satisfy d1_eval's fixed vocabulary
    # without any evaluator change. If D1 renames a bucket, this fails and
    # forces a deliberate, reviewed update on one side.
    from cryptobot.market_data.live_recorder import FUNDING_STREAM_TOKEN
    from cryptobot.research.d1_eval import (
        FUNDING_RECORD_TYPES,
        RANKING_RECORD_TYPES,
        classify_stream,
    )

    assert "funding_rate_settled" in FUNDING_RECORD_TYPES
    assert "kline_1d" in RANKING_RECORD_TYPES
    assert classify_stream(FUNDING_STREAM_TOKEN) == "funding"
    assert classify_stream("kline_1d") == "ranking_klines_1d"


# -- P2: universe_daily_klines ------------------------------------------------


def _kline_row(open_ms: int, quote_volume: float) -> list:
    return [open_ms, "1.0", "2.0", "0.5", "1.5", "10.0",
            open_ms + DAY_MS - 1, str(quote_volume), 100, "5.0",
            str(quote_volume / 2), "0"]


def test_kline_before_cutoff_pulls_nothing(tmp_path):
    seen: list[str] = []

    def handler(url: str):
        seen.append(url)
        raise AssertionError(f"must not pull before cutoff: {url}")

    rec, _ = _recorder(tmp_path, kline_symbols=("BTCUSDT",),
                       _rest_handler=handler)
    try:
        result = rec._kline_sweep(
            "binance", datetime(2026, 10, 27, 0, 3, tzinfo=UTC))
        assert result == {"pulled": False, "reason": "before-cutoff"}
        assert seen == []
    finally:
        rec.writer.close()


def test_kline_pulls_completed_bars_only_and_marks_day(tmp_path):
    now = datetime(2026, 10, 27, 0, 6, tzinfo=UTC)
    now_ms = int(now.timestamp() * 1000)
    day26 = int(datetime(2026, 10, 26, tzinfo=UTC).timestamp() * 1000)
    day25 = int(datetime(2026, 10, 25, tzinfo=UTC).timestamp() * 1000)
    day27 = int(datetime(2026, 10, 27, tzinfo=UTC).timestamp() * 1000)
    rows = [_kline_row(day26, 123.5), _kline_row(day25, 100.0),
            _kline_row(day27, 1.0)]  # forming bar: closeTime in the future
    calls: list[str] = []

    def handler(url: str):
        calls.append(url)
        return rows

    rec, _ = _recorder(tmp_path, kline_symbols=("BTCUSDT",),
                       _rest_handler=handler)
    try:
        result = rec._kline_sweep("binance", now)
        assert result["pulled"] is True
        assert result["emitted"] == 2
        assert result["universe_source"] == "explicit"
        again = rec._kline_sweep("binance", now)
        assert again["reason"] == "already-pulled"
        assert len(calls) == 1  # second sweep made no REST calls
    finally:
        rec.writer.close()
    klines = [r for r in _records_of(tmp_path) if r.get("type") == "kline_1d"]
    assert len(klines) == 2
    by_open = {k["exchange_open_ms"]: k for k in klines}
    assert by_open[day26]["quote_volume"] == pytest.approx(123.5)
    assert by_open[day25]["quote_volume"] == pytest.approx(100.0)
    for kline in klines:
        assert kline["event_ms"] == now_ms  # fresh stamp, monotonic-safe
        assert isinstance(kline["event_ms"], int)
        assert kline["universe_size"] == 1
        assert kline["symbol"] == "BTCUSDT"
    state = json.loads((tmp_path / "kline_state.json").read_text())
    assert state["last_pulled_day"] == "2026-10-27"


def test_kline_partial_pull_retries_with_throttle(tmp_path):
    from datetime import timedelta

    now = datetime(2026, 10, 27, 0, 6, tzinfo=UTC)
    now_ms = int(now.timestamp() * 1000)
    day26 = int(datetime(2026, 10, 26, tzinfo=UTC).timestamp() * 1000)
    calls: list[str] = []
    eth_broken = [True]

    def handler(url: str):
        calls.append(url)
        symbol = url.split("symbol=")[1].split("&")[0]
        if symbol == "ETHUSDT" and eth_broken[0]:
            raise OSError("gateway flake")
        return [_kline_row(day26, 10.0)]

    rec, _ = _recorder(tmp_path, kline_symbols=("BTCUSDT", "ETHUSDT"),
                       _rest_handler=handler)
    try:
        first = rec._kline_sweep("binance", now)
        assert first["pulled"] is False
        assert first["reason"] == "partial-failed"
        assert first["emitted"] == 1 and first["errors"] == 1
        state = json.loads((tmp_path / "kline_state.json").read_text())
        assert "last_pulled_day" not in state  # unmarked: retry allowed
        assert state["last_attempt_ms"] == now_ms
        calls_after_first = len(calls)
        assert calls_after_first == 2

        throttled = rec._kline_sweep("binance", now)
        assert throttled["pulled"] is False
        assert throttled["reason"] == "retry-throttled"
        assert throttled["retry_in_s"] == 1800
        assert len(calls) == calls_after_first  # zero REST calls

        eth_broken[0] = False
        later = now + timedelta(minutes=31)
        done = rec._kline_sweep("binance", later)
        assert done["pulled"] is True
        assert done["errors"] == 0
        assert done["emitted"] == 2  # BTCUSDT re-emitted, idempotent downstream
        state = json.loads((tmp_path / "kline_state.json").read_text())
        assert state["last_pulled_day"] == "2026-10-27"
    finally:
        rec.writer.close()


def test_kline_full_listing_discovers_trading_usd_perps(tmp_path):
    requested: list[str] = []

    def handler(url: str):
        if "exchangeInfo" in url:
            return {"symbols": [
                {"symbol": "BTCUSDT", "status": "TRADING",
                 "contractType": "PERPETUAL", "quoteAsset": "USDT"},
                {"symbol": "ETHUSDT", "status": "TRADING",
                 "contractType": "PERPETUAL", "quoteAsset": "USDT"},
                {"symbol": "OLDUSDT", "status": "BREAK",
                 "contractType": "PERPETUAL", "quoteAsset": "USDT"},
                {"symbol": "QUSDT", "status": "TRADING",
                 "contractType": "CURRENT_QUARTER", "quoteAsset": "USDT"},
                {"symbol": "XUSDC", "status": "TRADING",
                 "contractType": "PERPETUAL", "quoteAsset": "USDC"},
            ]}
        assert "klines" in url
        requested.append(url.split("symbol=")[1].split("&")[0])
        return []

    rec, _ = _recorder(tmp_path, _rest_handler=handler)
    try:
        result = rec._kline_sweep(
            "binance", datetime(2026, 10, 27, 0, 6, tzinfo=UTC))
        assert sorted(requested) == ["BTCUSDT", "ETHUSDT"]
        assert result["symbols"] == 2
        assert result["universe_source"] == "exchangeInfo"
    finally:
        rec.writer.close()


def test_kline_explicit_list_is_tagged_never_silent(tmp_path):
    now = datetime(2026, 10, 27, 0, 6, tzinfo=UTC)
    day26 = int(datetime(2026, 10, 26, tzinfo=UTC).timestamp() * 1000)
    rec, _ = _recorder(tmp_path, kline_symbols=("btcusdt",),
                       _rest_handler=lambda url: [_kline_row(day26, 5.0)])
    try:
        result = rec._kline_sweep("binance", now)
        assert result["universe_source"] == "explicit"
    finally:
        rec.writer.close()
    klines = [r for r in _records_of(tmp_path) if r.get("type") == "kline_1d"]
    assert klines[0]["universe_source"] == "explicit"
    assert klines[0]["universe_size"] == 1


def test_universe_discovery_failure_degrades_loudly(tmp_path):
    def handler(url: str):
        if "exchangeInfo" in url:
            raise OSError("dns blackhole")
        return []

    rec, _ = _recorder(tmp_path, _rest_handler=handler)
    try:
        symbols, source = rec._universe_for_pull("klines")
        assert source == "config-fallback"
        assert symbols == ["BTCUSDT", "ETHUSDT"]
        kinds = [a["kind"] for a in rec.writer.alerts]
        assert "universe-discovery-failed" in kinds
    finally:
        rec.writer.close()


def test_kline_symbols_config_normalized():
    from cryptobot.market_data.live_recorder import RecorderConfig

    assert RecorderConfig().kline_symbols == ()
    assert RecorderConfig(kline_symbols=("btcusdt", " ")).kline_symbols == (
        "BTCUSDT",)


# -- P4: restart hardening -----------------------------------------------------


def test_orphan_chunks_quarantined_on_startup(tmp_path):
    from cryptobot.market_data.live_recorder import ManifestChain, RecorderConfig, RecorderWriter

    chunks = tmp_path / "chunks"
    chunks.mkdir()
    (chunks / "rec-000000-20261018T213756Z.jsonl.gz").write_bytes(b"sealed0")
    (chunks / "rec-000001-20261018T214256Z.jsonl.gz").write_bytes(b"sealed1")
    (chunks / "rec-000001-20261018T214257Z.jsonl.gz").write_bytes(b"twin")
    (chunks / "rec-000002-20261018T214756Z.jsonl.gz").write_bytes(b"tail")
    (chunks / "orphan-rec-000009-20261018T214756Z.jsonl.gz").write_bytes(b"old")
    (tmp_path / "manifest.json").write_text(json.dumps({
        "format": "cryptobot-chunk-manifest/1", "chain_head": "genesis",
        "entries": [
            {"chunk": "chunks/rec-000000-20261018T213756Z.jsonl.gz"},
            {"chunk": "chunks/rec-000001-20261018T214256Z.jsonl.gz"},
        ]}))
    cfg = RecorderConfig(out_dir=str(tmp_path), chunk_seconds=3600,
                         disk_budget_mb=0)
    writer = RecorderWriter(
        cfg, manifest=ManifestChain(tmp_path / "manifest.json"))
    try:
        names = sorted(p.name for p in chunks.iterdir())
        assert "rec-000000-20261018T213756Z.jsonl.gz" in names
        assert "rec-000001-20261018T214256Z.jsonl.gz" in names
        assert "orphan-rec-000001-20261018T214257Z.jsonl.gz" in names
        assert "orphan-rec-000002-20261018T214756Z.jsonl.gz" in names
        assert "rec-000001-20261018T214257Z.jsonl.gz" not in names
        assert "rec-000002-20261018T214756Z.jsonl.gz" not in names
        assert writer._chunk_index == 2  # manifest length, never reused
        quarantined = [a for a in writer.alerts
                       if a["kind"] == "orphan-quarantined"]
        assert len(quarantined) == 2
    finally:
        writer.close()


def test_writer_enospc_fails_loudly_and_leaves_partial_unsealed(tmp_path, monkeypatch):
    import cryptobot.market_data.live_recorder as recorder
    from cryptobot.market_data.live_recorder import (
        RecorderConfig,
        RecorderWriter,
    )

    cfg = RecorderConfig(out_dir=str(tmp_path), chunk_seconds=3600,
                         disk_budget_mb=0, heartbeat_s=15)
    writer = RecorderWriter(cfg)
    partial = writer._raw_path
    assert partial is not None

    def boom(path, doc):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(recorder, "_atomic_json", boom)
    writer._last_heartbeat = 0.0  # force the heartbeat path on next write
    writer.submit({"type": "trade", "event_ms": 1})
    with pytest.raises(OSError):
        writer.close()
    assert writer.fatal_error is not None
    kinds = [a["kind"] for a in writer.alerts]
    assert "writer-fatal" in kinds
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["entries"] == []  # partial never sealed
    assert partial.exists()  # left for the next startup to quarantine


def test_heartbeat_is_time_based_with_ws_flag(tmp_path):
    from cryptobot.market_data.live_recorder import RecorderConfig, RecorderWriter

    clock = [1_000.0]
    cfg = RecorderConfig(out_dir=str(tmp_path), chunk_seconds=3600,
                         disk_budget_mb=0, heartbeat_s=10, ws_alive_s=100)
    writer = RecorderWriter(cfg, now=lambda: clock[0])
    try:
        # Sync with writer startup: the header heartbeat must land at t=1000
        # before the clock advances, or the race decides the assertions.
        deadline = time.time() + 10.0
        while not (tmp_path / "heartbeat.json").exists():
            assert time.time() < deadline, "writer thread never started"
            time.sleep(0.01)
        clock[0] += 11.0
        writer.submit({"type": "open_interest", "event_ms": 1})
    finally:
        writer.close()
    beat = json.loads((tmp_path / "heartbeat.json").read_text())
    assert beat["ws_alive"] is False  # no websocket frame ever arrived
    assert beat["ws_idle_s"] is None
    assert beat["records_total"] >= 2  # header + record, tiny-chunk-proof


def test_heartbeat_ws_alive_tracks_stream_activity(tmp_path):
    from cryptobot.market_data.live_recorder import RecorderConfig, RecorderWriter

    clock = [2_000.0]
    cfg = RecorderConfig(out_dir=str(tmp_path), chunk_seconds=3600,
                         disk_budget_mb=0, heartbeat_s=10, ws_alive_s=100)

    def run_phase(mark_ws: bool, advance_s: float) -> dict:
        writer = RecorderWriter(cfg, now=lambda: clock[0])
        try:
            if mark_ws:
                writer.note_ws_activity(int(clock[0] * 1000))
            clock[0] += advance_s
            writer.submit({"type": "open_interest", "event_ms": 1})
        finally:
            writer.close()
        return json.loads((tmp_path / "heartbeat.json").read_text())

    beat = run_phase(True, 11.0)
    assert beat["ws_alive"] is True
    assert beat["ws_idle_s"] == pytest.approx(11.0)
    beat = run_phase(False, 200.0)
    assert beat["ws_alive"] is False  # fresh writer never saw a frame


def test_header_and_gap_carry_event_ms(tmp_path):
    from cryptobot.market_data.live_recorder import RecorderConfig, RecorderWriter

    cfg = RecorderConfig(out_dir=str(tmp_path), chunk_seconds=3600,
                         disk_budget_mb=0)
    writer = RecorderWriter(cfg)
    try:
        writer.gapped = True  # force the gap-marker path deterministically
        writer.dropped = 3
        writer.submit({"type": "open_interest", "event_ms": 5})
    finally:
        writer.close()
    records = _records_of(tmp_path)
    by_type = {r.get("type") for r in records}
    assert {"header", "gap", "open_interest"} <= by_type
    for record in records:
        assert isinstance(record.get("event_ms"), int) and not isinstance(
            record.get("event_ms"), bool)


def test_format_and_manifest_schema_unchanged(tmp_path):
    from cryptobot.market_data.live_recorder import FORMAT, ManifestChain

    assert FORMAT == "cryptobot-recorder/2"
    target = tmp_path / "c.jsonl.gz"
    target.write_bytes(b"blob")
    chain = ManifestChain(tmp_path / "manifest.json")
    entry = chain.seal(target, first_ms=1, last_ms=2, records=9,
                       streams=["funding_settlement", "kline_1d"])
    # New inputs ride the existing schema: only the free-form streams list
    # gains tokens. Any key change must be a deliberate versioned decision.
    assert set(entry) == {"chunk", "sha256", "bytes", "first_ms", "last_ms",
                          "records", "streams", "gaps", "venue", "symbol",
                          "class", "sealed_utc", "prev", "entry_hash"}
    assert entry["streams"] == ["funding_settlement", "kline_1d"]
