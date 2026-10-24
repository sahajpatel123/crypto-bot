"""Data-bridge unit tests (Worker 2, E-007). Fixture streams only, no network.

Stdlib-only except the nautilus mapping tests, which skip without nautilus.
"""
import json

import pytest

from cryptobot.market_data.bridge import (
    SNAPSHOT_FORMAT,
    StreamBook,
    book_features,
    flow_window,
    iter_market_stream,
    load_snapshots,
    snapshot_ms,
    snapshot_record,
    to_nautilus_ticks,
)
from cryptobot.market_data.depth import DepthBook


def _depth_event(seq, recv_ms, first, last, prev, bids=(), asks=()):
    return {
        "v": 1, "format": "cryptobot-events/1", "input_class": "observed-public",
        "source": "binance-fapi-ws", "route": "public", "run_id": "r1", "seq": seq,
        "channel": "depth", "symbol": "BTCUSDT", "exchange_ts_ms": recv_ms,
        "local_recv_ms": recv_ms, "local_mono_ns": recv_ms * 1_000_000,
        "gap_kind": None, "venue_seq": last,
        "payload": {"first_update": first, "last_update": last,
                    "prev_last_update": prev,
                    "bids": [list(level) for level in bids],
                    "asks": [list(level) for level in asks]},
    }


def _ticker_event(seq, recv_ms, bid, ask):
    return {
        "v": 1, "format": "cryptobot-events/1", "input_class": "observed-public",
        "source": "binance-fapi-ws", "route": "public", "run_id": "r1", "seq": seq,
        "channel": "bookTicker", "symbol": "BTCUSDT", "exchange_ts_ms": recv_ms,
        "local_recv_ms": recv_ms, "local_mono_ns": recv_ms * 1_000_000,
        "gap_kind": None, "venue_seq": seq,
        "payload": {"update_id": seq, "bid": bid, "bid_qty": 1.5,
                    "ask": ask, "ask_qty": 2.5, "book_ts_ms": recv_ms},
    }


def _trade_event(seq, recv_ms, agg_id, price, qty, buyer_is_maker):
    return {
        "v": 1, "format": "cryptobot-events/1", "input_class": "observed-public",
        "source": "binance-fapi-ws", "route": "market", "run_id": "r1", "seq": seq,
        "channel": "aggTrade", "symbol": "BTCUSDT", "exchange_ts_ms": recv_ms,
        "local_recv_ms": recv_ms, "local_mono_ns": recv_ms * 1_000_000,
        "gap_kind": None, "venue_seq": agg_id,
        "payload": {"agg_id": agg_id, "price": price, "qty": qty,
                    "first_id": agg_id, "last_id": agg_id,
                    "trade_ts_ms": recv_ms, "buyer_is_maker": buyer_is_maker},
    }


def _write(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def test_snapshot_record_shape():
    record = snapshot_record(run_id="r1", symbol="BTCUSDT", last_update_id=50,
                             bids=[["100", "1"]], asks=[["101", "2"]],
                             rest_recv_ms=1000, rest_mono_ns=10**12,
                             limit=1000, outcome="synced")
    assert record["format"] == SNAPSHOT_FORMAT == "cryptobot-depth-snapshots/1"
    assert record["input_class"] == "observed-public"
    assert record["bids"] == [["100", "1"]]  # raw REST strings verbatim.


def test_load_snapshots_missing_file_is_empty(tmp_path):
    assert load_snapshots(tmp_path / "nope.jsonl") == []


def test_stream_rebuilds_synced_book_from_snapshot_plus_diffs(tmp_path):
    snaps = [snapshot_record(run_id="r1", symbol="BTCUSDT", last_update_id=50,
                             bids=[["100.0", "1.0"]], asks=[["101.0", "2.0"]],
                             rest_recv_ms=1000, rest_mono_ns=10**12,
                             limit=1000, outcome="synced")]
    events = [
        _depth_event(1, 900, 45, 49, 44),  # pre-snapshot: buffered-then-stale.
        _depth_event(2, 1100, 51, 52, 50,
                     bids=[(100.5, 1.5)], asks=[(101.0, 0.0), (102.0, 3.0)]),
    ]
    snaps_path, events_path = tmp_path / "s.jsonl", tmp_path / "e.jsonl"
    _write(snaps_path, snaps)
    _write(events_path, events)
    seen = []
    for item in iter_market_stream(events_path, snaps_path):
        # Capture per-item: books are a live view shared across items.
        entry = item.books["BTCUSDT"]
        seen.append((entry.book.state.synced, book_features(entry)))
    assert len(seen) == 2
    assert seen[0][0] is False  # snapshot not yet received.
    assert seen[0][1] == (None, "depth:unsynced-no-snapshot")
    assert seen[1][0] is True
    features, reason = seen[1][1]
    assert reason == "" and features is not None
    assert features["bid"] == pytest.approx(100.5)
    assert features["ask"] == pytest.approx(102.0)  # 101.0 removed, 102.0 added.
    assert features["bid_qty"] == pytest.approx(1.5)
    assert features["spread_bps"] == pytest.approx(1.5 / 101.25 * 10_000)
    assert features["last_update_id"] == 52


def test_stream_chain_break_resyncs_book(tmp_path):
    snaps = [snapshot_record(run_id="r1", symbol="BTCUSDT", last_update_id=50,
                             bids=[["100.0", "1.0"]], asks=[["101.0", "2.0"]],
                             rest_recv_ms=1000, rest_mono_ns=10**12,
                             limit=1000, outcome="synced")]
    events = [
        _depth_event(1, 1100, 51, 52, 50),
        _depth_event(2, 1200, 60, 61, 59),  # pu 59 != 52: chain break.
    ]
    snaps_path, events_path = tmp_path / "s.jsonl", tmp_path / "e.jsonl"
    _write(snaps_path, snaps)
    _write(events_path, events)
    seen = []
    for item in iter_market_stream(events_path, snaps_path):
        entry = item.books["BTCUSDT"]
        seen.append((entry.book.state.synced, book_features(entry)))
    assert seen[0][0] is True
    assert seen[1][0] is False
    assert seen[1][1] == (None, "depth:resync-in-flight")


def test_book_features_reasons_and_staleness():
    features, reason = book_features(None)
    assert features is None and reason == "depth:symbol-not-captured"


def test_book_features_values_and_imbalance(tmp_path):
    snaps = [snapshot_record(run_id="r1", symbol="BTCUSDT", last_update_id=10,
                             bids=[["100.0", "2.0"], ["99.0", "1.0"]],
                             asks=[["101.0", "6.0"]],
                             rest_recv_ms=1000, rest_mono_ns=10**12,
                             limit=1000, outcome="synced")]
    events = [_ticker_event(1, 1100, 100.0, 101.0)]
    snaps_path, events_path = tmp_path / "s.jsonl", tmp_path / "e.jsonl"
    _write(snaps_path, snaps)
    _write(events_path, events)
    (item,) = list(iter_market_stream(events_path, snaps_path))
    features, reason = book_features(item.books["BTCUSDT"], levels=10)
    assert reason == ""
    assert features["bid"] == 100.0 and features["ask"] == 101.0
    assert features["spread_bps"] == pytest.approx(100.0 / 100.5 * 100)
    assert features["bid_notional_top10"] == pytest.approx(200.0 + 99.0)
    assert features["ask_notional_top10"] == pytest.approx(606.0)
    assert features["imbalance_top1"] == pytest.approx((2.0 - 6.0) / 8.0)
    stale, reason = book_features(item.books["BTCUSDT"], now_ms=1000 + 6000)
    assert stale is None and reason == "depth:stale-book"
    fresh, _ = book_features(item.books["BTCUSDT"], now_ms=1000 + 1000)
    assert fresh is not None


def test_flow_window_signed_aggregates():
    trades = [
        {"price": 100.0, "qty": 2.0, "buyer_is_maker": False,
         "first_id": 11, "last_id": 11},
        {"price": 101.0, "qty": 1.0, "buyer_is_maker": True,
         "first_id": 12, "last_id": 12},
    ]
    agg, reason = flow_window(trades, 7000, prev_last_id=10)
    assert reason == ""
    assert agg["buy_notional"] == pytest.approx(200.0)
    assert agg["sell_notional"] == pytest.approx(101.0)
    assert agg["buy_count"] == 1 and agg["sell_count"] == 1
    assert agg["vwap"] == pytest.approx(301.0 / 3.0)
    assert agg["last_id"] == 12


def test_flow_window_gaps_and_empties_are_missing():
    agg, reason = flow_window([], 7000)
    assert agg is None and reason == "flow:empty-window"
    trades = [{"price": 100.0, "qty": 1.0, "buyer_is_maker": False,
               "first_id": 15, "last_id": 15}]
    agg, reason = flow_window(trades, 7000, prev_last_id=10)
    assert agg is None and reason == "flow:trade-id-gap"
    jumped = [
        {"price": 100.0, "qty": 1.0, "buyer_is_maker": False,
         "first_id": 11, "last_id": 11},
        {"price": 100.0, "qty": 1.0, "buyer_is_maker": False,
         "first_id": 13, "last_id": 13},
    ]
    agg, reason = flow_window(jumped, 7000, prev_last_id=10)
    assert agg is None and reason == "flow:trade-id-gap"


nautilus = pytest.importorskip("nautilus_trader")


def test_to_nautilus_ticks_mapping():
    from nautilus_trader.model.data import OrderBookDeltas, QuoteTick, TradeTick
    records = [
        _ticker_event(1, 1000, 100.0, 101.0),
        _trade_event(2, 1001, 7, 100.5, 0.5, False),
        _depth_event(3, 1002, 51, 52, 50, bids=[(100.5, 1.5)], asks=[(101.0, 0.0)]),
        {"channel": "markPrice", "symbol": "BTCUSDT", "exchange_ts_ms": 1003,
         "local_recv_ms": 1003,
         "payload": {"mark": 100.7, "funding_rate": 0.0001, "next_funding_ms": 2000}},
    ]
    ticks = to_nautilus_ticks(records, {"BTCUSDT": (2, 3)})
    assert isinstance(ticks[0], QuoteTick)
    assert float(ticks[0].bid_price) == 100.0 and float(ticks[0].ask_size) == 2.5
    assert ticks[0].ts_event == 1000 * 1_000_000  # exchange time...
    assert ticks[0].ts_init == 1000 * 1_000_000  # ...and receipt time preserved.
    assert isinstance(ticks[1], TradeTick)
    assert str(ticks[1].trade_id) == "7"
    from nautilus_trader.model.enums import AggressorSide
    assert ticks[1].aggressor_side == AggressorSide.BUYER  # buyer took liquidity.
    assert isinstance(ticks[2], OrderBookDeltas)
    assert len(ticks[2].deltas) == 2
    assert len(ticks) == 3  # markPrice skipped (funding is pump-modeled).


def test_to_nautilus_ticks_rejects_unknowns():
    with pytest.raises(KeyError, match="no precisions"):
        to_nautilus_ticks([_ticker_event(1, 1000, 100.0, 101.0)], {"ETHUSDT": (2, 3)})
    bad = _ticker_event(1, 1000, 100.0, 101.0)
    bad["channel"] = "liquidation"
    with pytest.raises(ValueError, match="unmapped channel"):
        to_nautilus_ticks([bad], {"BTCUSDT": (2, 3)})


def _snap_record(recv_ms=9000, exchange_ms=None):
    return snapshot_record(
        run_id="r", symbol="BTCUSDT", last_update_id=100,
        bids=[["100.0", "1.0"]], asks=[["101.0", "1.0"]],
        rest_recv_ms=recv_ms, rest_mono_ns=1, limit=1000, outcome="synced",
        exchange_ts_ms=exchange_ms)


def test_snapshot_ms_prefers_exchange_clock():
    assert snapshot_ms(_snap_record(9200, 9000)) == 9000
    assert snapshot_ms(_snap_record(9200, None)) == 9200  # legacy fallback.
    legacy = _snap_record(9200, None)
    del legacy["exchange_ts_ms"]  # pre-24H records lack the key entirely.
    assert snapshot_ms(legacy) == 9200


def test_book_features_refuses_future_data():
    book = DepthBook("BTCUSDT")
    assert book.on_snapshot([["100.0", "1.0"]], [["101.0", "1.0"]], 100) == "synced"
    entry = StreamBook(book, last_applied_ms=9000, ever_synced=True)
    feat, reason = book_features(entry, now_ms=1500)
    assert feat is None and reason == "depth:future-data"
    feat, reason = book_features(entry, now_ms=9500)
    assert feat is not None and reason == "" and feat["bid"] == 100.0
