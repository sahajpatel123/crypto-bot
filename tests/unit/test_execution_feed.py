"""Stream-pump unit tests (Worker 2, E-007). Fixture streams only.

Requires nautilus_trader (trial venv); skipped in the stdlib-only project env.
"""
import json
from datetime import datetime, timezone

import pytest

nautilus = pytest.importorskip("nautilus_trader")

from cryptobot.adapters import NautilusPaperEngine  # noqa: E402
from cryptobot.app.engine import EngineOrder  # noqa: E402
from cryptobot.execution import StreamPump  # noqa: E402
from cryptobot.market_data.bridge import iter_market_stream, snapshot_record  # noqa: E402

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
T0MS = int(T0.timestamp() * 1000)


def _engine():
    engine = NautilusPaperEngine(taker_bps=5.0, now_utc=lambda: T0,
                                 submit_delay_ms=0, fill_delay_ms=1)
    engine.add_instrument("BTCUSDT", price_precision=2, size_precision=3,
                          tick_size=0.01, step_size=0.001, ts_utc=T0)
    return engine


def _base(seq, recv_ms, channel):
    return {
        "v": 1, "format": "cryptobot-events/1", "input_class": "observed-public",
        "source": "binance-fapi-ws", "route": "public", "run_id": "r1", "seq": seq,
        "channel": channel, "symbol": "BTCUSDT", "exchange_ts_ms": recv_ms,
        "local_recv_ms": recv_ms, "local_mono_ns": recv_ms * 1_000_000,
        "gap_kind": None, "venue_seq": seq, "payload": {},
    }


def _ticker(seq, recv_ms, bid, ask):
    record = _base(seq, recv_ms, "bookTicker")
    record["payload"] = {"update_id": seq, "bid": bid, "bid_qty": 10.0,
                         "ask": ask, "ask_qty": 10.0, "book_ts_ms": recv_ms}
    return record


def _trade(seq, recv_ms, agg_id, price, maker):
    record = _base(seq, recv_ms, "aggTrade")
    record["route"] = "market"
    record["venue_seq"] = agg_id
    record["payload"] = {"agg_id": agg_id, "price": price, "qty": 0.5,
                         "first_id": agg_id, "last_id": agg_id,
                         "trade_ts_ms": recv_ms, "buyer_is_maker": maker}
    return record


def _depth(seq, recv_ms, first, last, prev, bids=(), asks=()):
    record = _base(seq, recv_ms, "depth")
    record["venue_seq"] = last
    record["payload"] = {"first_update": first, "last_update": last,
                         "prev_last_update": prev,
                         "bids": [list(lv) for lv in bids],
                         "asks": [list(lv) for lv in asks]}
    return record


def _mark(seq, recv_ms, rate, next_ms):
    record = _base(seq, recv_ms, "markPrice")
    record["route"] = "market"
    record["venue_seq"] = None
    record["payload"] = {"mark": 60000.0, "funding_rate": rate,
                         "next_funding_ms": next_ms}
    return record


def test_file_pump_feeds_engine_and_views(tmp_path):
    snaps = [snapshot_record(run_id="r1", symbol="BTCUSDT", last_update_id=50,
                             bids=[["60000.00", "1.0"]], asks=[["60000.50", "1.0"]],
                             rest_recv_ms=T0MS, rest_mono_ns=T0MS * 10**6,
                             limit=1000, outcome="synced")]
    events = [
        _depth(1, T0MS + 100, 51, 52, 50, bids=[(59999.50, 2.0)],
               asks=[(60000.50, 1.0)]),
        _ticker(2, T0MS + 1000, 60000.00, 60000.50),
        _trade(3, T0MS + 1100, 1, 60000.25, False),
        _trade(4, T0MS + 1200, 2, 60000.75, True),
        _ticker(5, T0MS + 2000, 60001.00, 60001.50),
        _trade(6, T0MS + 2100, 3, 60001.00, False),
    ]
    snaps_path, events_path = tmp_path / "s.jsonl", tmp_path / "e.jsonl"
    snaps_path.write_text("\n".join(json.dumps(r) for r in snaps) + "\n")
    events_path.write_text("\n".join(json.dumps(r) for r in events) + "\n")
    engine = _engine()
    pump = StreamPump(engine)
    ticks = list(pump.pump_stream(iter_market_stream(events_path, snaps_path)))
    assert len(ticks) == 6
    # Depth synced from snapshot + diff with observed features.
    assert ticks[0].depth is not None and ticks[0].depth_reason == ""
    assert ticks[0].depth["bid"] == pytest.approx(60000.00)
    # Flow: the window-[T0,T0+1s) aggregate closes on the first trade past it.
    flow_tick = next(t for t in ticks if t.flow is not None)
    assert flow_tick.flow_reason == ""
    assert flow_tick.flow["buy_notional"] == pytest.approx(60000.25 * 0.5)
    assert flow_tick.flow["sell_notional"] == pytest.approx(60000.75 * 0.5)
    assert flow_tick.flow["last_id"] == 2
    # Engine ingested the quotes: a market order crosses the pumped book.
    cid = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    engine.note_event(_ticker(7, T0MS + 3000, 60002.00, 60002.50))
    fills = [e for e in engine.poll() if e.kind == "fill"]
    assert [f.payload.client_order_id for f in fills] == [cid]
    # CORR-EXEC: due at T0+2.1s, so it crosses the due-time print
    # (60001.00); the T0+3s ticker is future information at that time.
    assert fills[0].payload.price == pytest.approx(60001.00)


def test_funding_settles_once_when_crossed_with_position(tmp_path):
    # E-008: funding is engine-owned — it settles from markPrice terms against
    # the engine's own open position; the pump only splits it out.
    events = [
        _mark(1, T0MS, 0.0001, T0MS + 5000),
        _ticker(2, T0MS + 1000, 60000.00, 60000.50),
        _ticker(3, T0MS + 6000, 60001.00, 60001.50),
        _ticker(4, T0MS + 7000, 60002.00, 60002.50),
    ]
    events_path = tmp_path / "e.jsonl"
    events_path.write_text("\n".join(json.dumps(r) for r in events) + "\n")
    engine = _engine()
    pump = StreamPump(engine)
    cid = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.002, "MARKET"))
    ticks = list(pump.pump_stream(iter_market_stream(events_path, None)))
    assert ticks[0].funding == [] and ticks[1].funding == []
    assert [e.payload.client_order_id for e in ticks[1].engine_events
            if e.kind == "fill"] == [cid]
    assert len(ticks[2].funding) == 1
    funding = ticks[2].funding[0]
    assert funding.instrument == "BTCUSDT"
    assert funding.amount == pytest.approx(-0.002 * 60000.00 * 0.0001)
    assert funding.event_id == f"funding:BTCUSDT:{T0MS + 5000}"
    assert ticks[3].funding == []  # settled once; no double-book.
    assert pump.stats["funding"] == 1


def test_funding_skipped_when_flat_or_zero_rate(tmp_path):
    events = [
        _mark(1, T0MS, 0.0, T0MS + 5000),
        _ticker(2, T0MS + 6000, 60001.00, 60001.50),
    ]
    events_path = tmp_path / "e.jsonl"
    events_path.write_text("\n".join(json.dumps(r) for r in events) + "\n")
    engine = _engine()  # flat: no position, no cash flow.
    ticks = list(StreamPump(engine).pump_stream(
        iter_market_stream(events_path, None)))
    assert ticks[1].funding == []
    engine2 = _engine()  # open position but zero rate: still nothing.
    engine2.submit(EngineOrder("BTCUSDT", "BUY", 0.002, "MARKET"))
    ticks = list(StreamPump(engine2).pump_stream(
        iter_market_stream(events_path, None)))
    assert ticks[1].funding == []


def test_refuses_reference_and_fake_engines(tmp_path):
    from cryptobot.app.reference import ReferenceEngine

    class _Fake:
        model_label = "fake-test"

    with pytest.raises(ValueError, match="refuses engine 'reference-fake-venue'"):
        StreamPump(ReferenceEngine(log_path=tmp_path / "ref.jsonl",
                                   outcome_sink=None, taker_bps=5.0))
    with pytest.raises(ValueError, match="refuses engine 'fake-test'"):
        StreamPump(_Fake())
    with pytest.raises(ValueError, match="refuses engine None"):
        StreamPump(object())
    StreamPump(_engine())  # nautilus-paper passes the guard.


def test_none_heartbeat_advances_clock_and_counts_stats():
    engine = _engine()
    pump = StreamPump(engine)
    before = engine.now_utc
    ticks = list(pump.pump_live(iter([
        _ticker(1, T0MS, 60000.00, 60000.50),
        None,  # B3 idle heartbeat: wall-clock advance, drain, no views.
    ])))
    assert ticks[1].record is None
    assert engine.now_utc > before
    assert ticks[1].depth is None and ticks[1].depth_reason == "depth:heartbeat"
    assert ticks[1].flow is None and ticks[1].flow_reason == "flow:heartbeat"
    assert pump.stats["records"] == 2
    assert pump.stats["heartbeats"] == 1
    assert "" not in pump._books  # heartbeats never open a book entry.


def test_replay_heartbeat_advances_one_virtual_second():
    from datetime import timedelta
    engine = _engine()
    pump = StreamPump(engine)
    ticks = list(pump.pump_live(iter([
        _ticker(1, T0MS, 60000.00, 60000.50),
        None,
        None,
    ]), replay=True))
    assert engine.now_utc == datetime.fromtimestamp(T0MS / 1000, tz=timezone.utc) + timedelta(seconds=2)
    assert pump.stats["heartbeats"] == 2
    assert all(t.record is None for t in ticks[1:])


def test_live_pump_syncs_books_via_rest_snapshot():
    def rest_get(url, timeout):
        assert "symbol=BTCUSDT" in url
        return {"bids": [["60000.00", "1.0"]], "asks": [["60000.50", "1.0"]],
                "lastUpdateId": 50}, 1.0

    engine = _engine()
    pump = StreamPump(engine, rest_get=rest_get)
    records = [
        _depth(1, T0MS + 100, 51, 52, 50, bids=[(59999.50, 2.0)],
               asks=[(60000.50, 1.0)]),
    ]
    (tick,) = list(pump.pump_live(iter(records)))
    assert tick.depth is not None and tick.depth_reason == ""
    assert tick.depth["bid"] == pytest.approx(60000.00)


def test_live_pump_chain_break_resyncs_with_reason():
    calls = []

    def rest_get(url, timeout):
        calls.append(url)
        return {"bids": [["60000.00", "1.0"]], "asks": [["60000.50", "1.0"]],
                "lastUpdateId": 50}, 1.0

    engine = _engine()
    pump = StreamPump(engine, rest_get=rest_get)
    records = [
        _depth(1, T0MS + 100, 51, 52, 50),
        _depth(2, T0MS + 200, 60, 61, 59),  # pu 59 != 52: chain break.
    ]
    ticks = list(pump.pump_live(iter(records)))
    assert ticks[0].depth is not None
    assert ticks[1].depth is None
    assert ticks[1].depth_reason == "depth:resync-in-flight"
    assert len(calls) == 1  # refetch scheduled after the re-buffer window.


def test_replay_pump_is_offline_no_rest_no_live_book():
    """Manager fixup: replay=True never fetches REST snapshots (B5 offline).

    Without this, replay contaminates books with live snapshots and
    reports depth_ok on depthless archive data.
    """
    def rest_get(url, timeout):
        raise AssertionError(f"replay must not fetch REST: {url}")

    engine = _engine()
    pump = StreamPump(engine, rest_get=rest_get)
    records = [
        _trade(1, T0MS + 100, 101, 60000.00, False),
        None,
        _trade(2, T0MS + 1200, 102, 60000.50, True),
    ]
    ticks = list(pump.pump_live(iter(records), replay=True))
    assert ticks[0].depth is None
    assert ticks[0].depth_reason == "depth:unsynced-no-snapshot"
    assert ticks[2].depth is None
    assert pump.stats["depth_ok"] == 0
