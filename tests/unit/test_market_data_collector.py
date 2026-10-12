"""Collector supervision + ingest tests (Worker 2, E-006). Fakes only, no network."""
import json
import socket
from collections import deque
from pathlib import Path

from cryptobot.market_data.collector import (
    Collector,
    CollectorConfig,
    measure_clock_offset_ms,
    select_capture_set,
)
from cryptobot.market_data.ws import WsClosed, WsHandshakeError


def _config(tmp_path, **kw):
    base = dict(symbols=("BTCUSDT",), run_dir=str(tmp_path / "run"),
                run_id="test-run", capture_set_rule="test")
    base.update(kw)
    return CollectorConfig(**base)


class FakeConn:
    """Scripted connection: select() fires only while scripted, then idles forever."""

    def __init__(self, script=()):
        self.sock, self.peer = socket.socketpair()
        self.script = deque(script)
        if self.script:
            self.peer.send(b"x")  # arm exactly one readable trigger.
        self.closed = False

    @property
    def native_socket(self):
        return self.sock

    def recv_message(self, timeout_s=None):
        if not self.script:
            raise WsClosed("drained")  # unreachable: select never fires when quiet.
        item = self.script.popleft()
        if not self.script:
            self.sock.setblocking(False)  # last item: disarm so select idles after.
            try:
                self.sock.recv(1)
            except OSError:
                pass
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        self.closed = True
        try:
            self.sock.close()
        except OSError:
            pass


def _trade_msg(seq_id=1, price="100", ts=1000):
    return ("text", json.dumps(
        {"stream": "btcusdt@aggTrade",
         "data": {"e": "aggTrade", "E": ts, "s": "BTCUSDT", "a": seq_id, "p": price,
                  "q": "0.5", "f": seq_id, "l": seq_id, "T": ts, "m": False}}).encode())


def _pump(collector, conn, tmp_path):
    run_dir = Path(collector.config.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    collector._conns = {"market": conn}
    with (run_dir / "raw.jsonl").open("w") as raw_fh, \
         (run_dir / "events.jsonl").open("w") as events_fh, \
         (run_dir / "bars.jsonl").open("w") as bars_fh:
        collector._pump_once(raw_fh, events_fh, bars_fh)


def test_ingest_counts_dup_and_ooo(tmp_path):
    collector = Collector(_config(tmp_path))
    first = FakeConn([_trade_msg(1), _trade_msg(1), _trade_msg(3)])
    for _ in range(3):  # one message per pump, like the live loop.
        _pump(collector, first, tmp_path)
    _pump(collector, FakeConn([_trade_msg(2)]), tmp_path)
    assert collector.stats.events_total == 4
    assert collector.stats.duplicates == 1
    assert collector.stats.out_of_order == 1


def test_ingest_marks_pending_gap_once(tmp_path):
    collector = Collector(_config(tmp_path))
    collector._pending_gap["market"] = "natural"
    _pump(collector, FakeConn([_trade_msg(1), _trade_msg(2)]), tmp_path)
    assert collector.stats.gaps_natural == 1
    assert collector._pending_gap["market"] is None


def test_ingest_counts_malformed_without_crashing(tmp_path):
    collector = Collector(_config(tmp_path))
    _pump(collector, FakeConn([("text", b"not json{"), ("binary", b"\x00")]), tmp_path)
    assert collector.stats.malformed == 1  # binary frames are skipped, not malformed.
    assert collector.stats.events_total == 0


def test_depth_chain_break_resyncs_via_rest(tmp_path):
    calls = []

    def rest_get(url, timeout):
        calls.append(url)
        return {"bids": [["100", "1"]], "asks": [["101", "1"]], "lastUpdateId": 50}, 5.0

    collector = Collector(_config(tmp_path), rest_get=rest_get)
    run_dir = Path(collector.config.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    fh = (run_dir / "drain.jsonl").open("w")
    collector._snapshot_symbol("BTCUSDT", fh, fh, fh, fh)
    fh.close()
    book = collector._books["BTCUSDT"]
    assert book.state.synced
    diff = {"first_update": 60, "last_update": 60, "prev_last_update": 59,
            "bids": [], "asks": []}  # normalized shape, as _ingest delivers.
    event = {"route": "public", "channel": "depth", "symbol": "BTCUSDT",
             "exchange_ts_ms": 1, "local_recv_ms": 2, "local_mono_ns": 3, "seq": 1,
             "venue_seq": 60, "gap_kind": None, "payload": diff}
    run_dir = Path(collector.config.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / "bars.jsonl").open("w") as bars_fh:
        collector._ingest(event, bars_fh)
    assert collector.stats.depth_resyncs == 1  # pu 59 != snapshot chain.
    assert len(calls) == 1  # resync only schedules; the snapshot waits for re-buffering.
    assert "BTCUSDT" in collector._snapshot_due


def test_select_capture_set_is_dynamic_not_hardcoded():
    payload = {"symbols": [
        {"symbol": "AUSDT", "baseAsset": "A", "quoteAsset": "USDT",
         "contractType": "PERPETUAL", "status": "TRADING",
         "pricePrecision": 2, "quantityPrecision": 2, "filters": []},
        {"symbol": "BUSDT", "baseAsset": "B", "quoteAsset": "USDT",
         "contractType": "PERPETUAL", "status": "TRADING",
         "pricePrecision": 2, "quantityPrecision": 2, "filters": []},
        {"symbol": "CUSDT", "baseAsset": "C", "quoteAsset": "USDT",
         "contractType": "PERPETUAL", "status": "BREAK",
         "pricePrecision": 2, "quantityPrecision": 2, "filters": []},
    ]}

    def rest_get(url, timeout):
        assert url.endswith("/ticker/24hr")
        return [{"symbol": "AUSDT", "quoteVolume": "10"},
                {"symbol": "BUSDT", "quoteVolume": "99"},
                {"symbol": "CUSDT", "quoteVolume": "999"}], 1.0

    chosen, rule, evidence = select_capture_set(payload, rest_get, "https://x", top_n=1)
    assert chosen == ("BUSDT",)  # top volume among TRADING only; BREAK excluded.
    assert "top-1" in rule and evidence == {"BUSDT": 99.0}


def test_measure_clock_offset_halves_rtt():
    def rest_get(url, timeout):
        return {"serverTime": 2000}, 1.0

    import cryptobot.market_data.collector as collector_mod
    calls = iter([1.0, 1.1])  # seconds; the measurer converts to ms.
    original = collector_mod.time.time
    collector_mod.time.time = lambda: next(calls)
    try:
        offset = measure_clock_offset_ms(rest_get)
    finally:
        collector_mod.time.time = original
    assert offset["offset_ms"] == 2000 - 1050.0
    assert offset["rtt_ms"] == 100.0


def _stub_rest(url, timeout):
    if url.endswith("/fapi/v1/time"):
        return {"serverTime": 1000}, 1.0
    return {"bids": [["100", "1"]], "asks": [["101", "1"]], "lastUpdateId": 50}, 1.0


def test_run_writes_manifest_stats_heartbeat_and_cleans_pid(tmp_path):
    made = []

    def connect(url):
        # First two connections drop once (exactly 2 reconnects); later ones deliver.
        conn = FakeConn([] if len(made) >= 2 else [WsClosed("drop")])
        made.append(conn)
        return conn

    collector = Collector(_config(tmp_path), connect=connect, rest_get=_stub_rest)
    stats = collector.run(duration_s=0.5)
    run_dir = Path(collector.config.run_dir)
    assert stats.stop_reason == "duration-reached"
    assert stats.reconnects == 2
    assert stats.disconnects_natural == 2
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "run_stats.json").exists()
    assert (run_dir / "heartbeat.json").exists()
    assert not (run_dir / "pid").exists()
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert set(manifest["files"]) == {"raw", "events", "bars", "depth_snapshots"}
    assert all(len(v["sha256"]) == 64 for v in manifest["files"].values())


def test_run_honors_stop_file_and_storage_bound(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "STOP").write_text("stop")
    collector = Collector(_config(tmp_path), connect=lambda url: FakeConn(),
                          rest_get=_stub_rest)
    assert collector.run(duration_s=60).stop_reason == "stop-file"

    collector2 = Collector(_config(tmp_path, run_dir=str(tmp_path / "run2"),
                                   run_id="run2", max_bytes=1),
                           connect=lambda url: FakeConn([_trade_msg(1)] * 50),
                           rest_get=_stub_rest)
    assert collector2.run(duration_s=60).stop_reason == "storage-bound"


def test_run_returns_when_routes_never_recover(tmp_path):
    def dead(url):
        raise OSError("endpoint down")

    collector = Collector(_config(tmp_path), connect=dead, rest_get=_stub_rest)
    assert collector.run(duration_s=0.5).stop_reason == "connect-failed"

    calls = []

    def flaky(url):
        if len(calls) < 2:
            calls.append(url)
            return FakeConn([WsClosed("drop")])  # setup succeeds; first pump drops.
        raise OSError("endpoint down")  # every reconnect attempt fails.

    collector2 = Collector(_config(tmp_path, run_dir=str(tmp_path / "run2"), run_id="run2"),
                           connect=flaky, rest_get=_stub_rest)
    assert collector2.run(duration_s=0.5).stop_reason == "routes-exhausted"


def test_snapshot_rest_garbage_reschedules_instead_of_crashing(tmp_path):
    calls = []

    def rest_get(url, timeout):
        calls.append(url)
        if len(calls) == 1:
            raise ValueError("HTML error page")
        return {"bids": [["100", "1"]], "asks": [["101", "1"]], "lastUpdateId": 50}, 5.0

    collector = Collector(_config(tmp_path), rest_get=rest_get)
    run_dir = Path(collector.config.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    fh = (run_dir / "drain.jsonl").open("w")
    collector._snapshot_due["BTCUSDT"] = 0.0  # due now.
    collector._snapshot_due_check(fh, fh, fh, fh)  # must not raise.
    assert "BTCUSDT" in collector._snapshot_due  # rescheduled for retry.
    collector._snapshot_due["BTCUSDT"] = 0.0
    collector._snapshot_due_check(fh, fh, fh, fh)
    assert collector._books["BTCUSDT"].state.synced
    fh.close()


def test_open_retries_handshake_rejections_then_succeeds(tmp_path):
    attempts = []
    good = FakeConn()

    def connect(url):
        attempts.append(url)
        if len(attempts) < 3:
            raise WsHandshakeError("edge 429")
        return good

    collector = Collector(_config(tmp_path), connect=connect)
    assert collector._open_with_retry("market") is True
    assert len(attempts) == 3 and collector._conns["market"] is good


def test_run_survives_clock_probe_failure(tmp_path):
    def rest_get(url, timeout):
        if url.endswith("/fapi/v1/time"):
            raise OSError("time endpoint down")
        return {"bids": [["100", "1"]], "asks": [["101", "1"]], "lastUpdateId": 50}, 1.0

    collector = Collector(_config(tmp_path), connect=lambda url: FakeConn(), rest_get=rest_get)
    stats = collector.run(duration_s=0.3)
    assert stats.stop_reason == "duration-reached"


def test_snapshot_symbol_persists_record_with_sync_boundary(tmp_path):
    def rest_get(url, timeout):
        return {"bids": [["100", "1"]], "asks": [["101", "1"]],
                "lastUpdateId": 50}, 5.0

    collector = Collector(_config(tmp_path), rest_get=rest_get)
    run_dir = Path(collector.config.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    drain = (run_dir / "drain.jsonl").open("w")
    snaps_path = run_dir / "depth_snapshots.jsonl"
    with snaps_path.open("w") as snaps_fh:
        collector._snapshot_symbol("BTCUSDT", drain, drain, drain, snaps_fh)
    drain.close()
    records = [json.loads(line) for line in snaps_path.read_text().splitlines()]
    assert len(records) == 1
    record = records[0]
    assert record["format"] == "cryptobot-depth-snapshots/1"
    assert record["symbol"] == "BTCUSDT" and record["last_update_id"] == 50
    assert record["bids"] == [["100", "1"]] and record["asks"] == [["101", "1"]]
    assert record["outcome"] == "synced"  # sync boundary marker for replay.
    assert record["source"] == "binance-fapi-rest"
    assert collector._books["BTCUSDT"].state.synced


def test_run_writes_depth_snapshots_file_and_manifest(tmp_path):
    def rest_get(url, timeout):
        if url.endswith("/fapi/v1/time"):
            return {"serverTime": 1_000_000}, 1.0
        return {"bids": [["100", "1"]], "asks": [["101", "1"]],
                "lastUpdateId": 50}, 1.0

    collector = Collector(_config(tmp_path), connect=lambda url: FakeConn(), rest_get=rest_get)
    stats = collector.run(duration_s=0.3)
    assert stats.stop_reason == "duration-reached"
    run_dir = Path(collector.config.run_dir)
    assert (run_dir / "depth_snapshots.jsonl").exists()
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert "depth_snapshots" in manifest["files"]
