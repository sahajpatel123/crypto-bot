"""Depth-book sync tests (Worker 2, E-006). Synthetic books only."""
from cryptobot.market_data.depth import DepthBook


def _diff(u, pu, u_first=None, bids=(), asks=()):
    # Normalized diff shape (validated numerics), as the collector delivers.
    return {"first_update": u_first if u_first is not None else u, "last_update": u,
            "prev_last_update": pu,
            "bids": [[float(p), float(q)] for p, q in bids],
            "asks": [[float(p), float(q)] for p, q in asks]}


def test_buffer_snapshot_drain_applies_in_order():
    book = DepthBook("BTCUSDT")
    assert book.on_diff(_diff(101, 100)) == "buffered"
    assert book.on_diff(_diff(102, 101)) == "buffered"
    assert book.top() == (None, None)  # unsynced: no levels exposed.
    assert book.on_snapshot([["100", "1"]], [["101", "2"]], 100) == "synced"
    assert book.state.applied == 2 and book.state.dropped_stale == 0
    assert book.top() == (100.0, 101.0)


def test_snapshot_discards_stale_buffered():
    book = DepthBook("BTCUSDT")
    book.on_diff(_diff(98, 97))
    book.on_diff(_diff(101, 100))
    assert book.on_snapshot([["100", "1"]], [["101", "1"]], 100) == "synced"
    assert book.state.dropped_stale == 1 and book.state.applied == 1


def test_snapshot_span_violation_forces_resync():
    book = DepthBook("BTCUSDT")
    book.on_diff(_diff(105, 104, u_first=104))  # starts past lastUpdateId + 1.
    assert book.on_snapshot([["100", "1"]], [["101", "1"]], 100) == "resync"
    assert book.resyncs == 1 and not book.state.synced


def test_chain_break_mid_stream_forces_resync():
    book = DepthBook("BTCUSDT")
    assert book.on_snapshot([["100", "1"]], [["101", "1"]], 100) == "synced"
    assert book.on_diff(_diff(101, 100, bids=[(100, 2)])) == "applied"
    assert book.top()[0] == 100.0
    assert book.on_diff(_diff(103, 102)) == "resync"  # pu != last applied u.
    book.request_resync("test")
    assert book.on_snapshot([["99", "1"]], [["102", "1"]], 103) == "synced"
    assert book.top() == (99.0, 102.0)


def test_zero_qty_removes_level_and_spread_math():
    book = DepthBook("BTCUSDT")
    book.on_snapshot([["100", "1"], ["99", "1"]], [["101", "1"]], 50)
    book.on_diff(_diff(51, 50, bids=[(100, 0)]))
    assert book.top() == (99.0, 101.0)
    assert book.spread_bps() is not None and book.spread_bps() > 0
    bid_notional, ask_notional = book.depth_totals(levels=10)
    assert (bid_notional, ask_notional) == (99.0, 101.0)
    assert DepthBook("X").spread_bps() is None  # unsynced: no spread invented.


def test_state_carries_resync_reason_until_synced():
    book = DepthBook("BTCUSDT")
    assert book.state.last_reason == ""
    book.on_diff(_diff(105, 104, u_first=104))
    assert book.on_snapshot([["100", "1"]], [["101", "1"]], 100) == "resync"
    assert book.state.last_reason == "snapshot-span"
    book.request_resync("chain-break")
    assert book.state.last_reason == "chain-break"
    assert book.on_snapshot([["100", "1"]], [["101", "1"]], 100) == "synced"
    assert book.state.last_reason == ""  # synced: no stale reason.


def test_book_dict_round_trip_preserves_levels_and_lifecycle():
    import json

    from cryptobot.market_data.views import DepthStore

    store = DepthStore()
    assert store.apply_snapshot_record(
        {"symbol": "BTCUSDT", "bids": [["100.0", "1.0"]],
         "asks": [["101.0", "1.0"]], "last_update_id": 100,
         "rest_recv_ms": 5000, "exchange_ts_ms": 4999}) == "synced"
    store.apply_diff("BTCUSDT", {"first_update": 101, "last_update": 101,
                                 "prev_last_update": 100,
                                 "bids": [[100.5, 2.0]], "asks": []}, 5100)
    store.apply_trade("BTCUSDT", {"agg_id": 9, "price": 100.5, "qty": 0.5,
                                  "first_id": 9, "last_id": 9,
                                  "trade_ts_ms": 5100,
                                  "buyer_is_maker": False})
    raw = json.loads(json.dumps(store.to_dict()))
    restored = DepthStore.from_dict(raw)
    assert restored.to_dict() == raw
    assert restored.book_flow_for("BTCUSDT", 5200)[0] is not None
    assert restored.book_flow_for("BTCUSDT", 5200)[0].bids[0][0] == 100.5
