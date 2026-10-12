"""Book/flow view tests (W2, E-008; B4). Fixture records only."""
import pytest

from cryptobot.market_data.views import (
    BookView,
    DepthStore,
    FlowView2,
    book_flow_for,
)

T0MS = 1_789_000_000_000


def _snap(symbol="BTCUSDT", last_id=50, recv_ms=T0MS):
    return {"symbol": symbol, "bids": [["60000.00", "1.5"]],
            "asks": [["60000.50", "2.5"]], "last_update_id": last_id,
            "rest_recv_ms": recv_ms}


def _diff(first=51, last=52, prev=50, bids=(), asks=()):
    return {"first_update": first, "last_update": last,
            "prev_last_update": prev,
            "bids": [[p, q] for p, q in bids],
            "asks": [[p, q] for p, q in asks]}


def _trade_payload(agg_id, price, qty=0.5, maker=False, ts_ms=T0MS + 100):
    return {"agg_id": agg_id, "price": price, "qty": qty,
            "first_id": agg_id, "last_id": agg_id,
            "trade_ts_ms": ts_ms, "buyer_is_maker": maker}


def _depth_record(seq, recv_ms, payload):
    return {"channel": "depth", "symbol": "BTCUSDT",
            "exchange_ts_ms": recv_ms, "local_recv_ms": recv_ms, "payload": payload}


def _trade_record(seq, recv_ms, payload):
    return {"channel": "aggTrade", "symbol": "BTCUSDT",
            "exchange_ts_ms": recv_ms, "local_recv_ms": recv_ms, "payload": payload}


def test_synced_book_and_closed_flow_view():
    store = DepthStore()
    assert store.apply_snapshot_record(_snap()) == "synced"
    assert store.apply_diff("BTCUSDT", _diff(bids=[(59999.50, 2.0)]),
                            T0MS + 100) == "applied"
    store.apply_trade("BTCUSDT", _trade_payload(1, 60000.25, maker=False))
    store.apply_trade("BTCUSDT", _trade_payload(2, 60000.75, maker=True))
    store.apply_trade("BTCUSDT", _trade_payload(3, 60001.00, maker=False,
                                                ts_ms=T0MS + 1100))
    book, flow, reason = book_flow_for("BTCUSDT", T0MS + 1100, store)
    assert reason == ""
    assert isinstance(book, BookView) and isinstance(flow, FlowView2)
    assert book.bids[0] == (60000.00, 1.5) and book.asks[0] == (60000.50, 2.5)
    assert book.levels == 10 and book.last_update_id == 52
    assert book.sync_age_ms == 1000 and book.quality == "clean"
    assert book.spread_bps == pytest.approx(0.50 / 60000.25 * 10_000)
    assert flow.window_start_ms == T0MS // 1000 * 1000
    assert flow.window_end_ms == flow.window_start_ms + 1000
    assert flow.buy_notional == pytest.approx(60000.25 * 0.5)
    assert flow.sell_notional == pytest.approx(60000.75 * 0.5)
    assert (flow.buy_count, flow.sell_count) == (1, 1)
    assert flow.last_id == 2 and flow.completeness == "complete"


def test_never_synced_reasons_for_archive_without_depth():
    store = DepthStore()
    book, flow, reason = book_flow_for("BTCUSDT", T0MS, store)
    assert book is None and flow is None
    assert reason == "book:never-synced; flow:no-trades-yet"


def test_chain_break_is_resync_in_flight():
    store = DepthStore()
    store.apply_snapshot_record(_snap())
    assert store.apply_diff("BTCUSDT", _diff(first=60, last=61, prev=59),
                            T0MS + 100) == "resync"
    book, _, reason = book_flow_for("BTCUSDT", T0MS + 100, store)
    assert book is None and reason == "book:resync-in-flight; flow:no-trades-yet"


def test_stale_book_returns_view_with_quality():
    store = DepthStore(stale_after_ms=5_000)
    store.apply_snapshot_record(_snap())
    book, _, reason = book_flow_for("BTCUSDT", T0MS + 60_000, store)
    assert book is not None and book.quality == "stale"
    assert book.sync_age_ms == 60_000
    assert reason == "flow:no-trades-yet"  # only the missing view is named.


def test_book_ticker_never_feeds_the_synced_book():
    store = DepthStore()
    store.apply_record({"channel": "bookTicker", "symbol": "BTCUSDT",
                        "exchange_ts_ms": T0MS, "local_recv_ms": T0MS,
                        "payload": {"bid": 1.0, "ask": 999999.0}})
    store.apply_record({"channel": "markPrice", "symbol": "BTCUSDT",
                        "exchange_ts_ms": T0MS, "local_recv_ms": T0MS,
                        "payload": {"mark": 60000.0}})
    book, _, reason = book_flow_for("BTCUSDT", T0MS, store)
    assert book is None and "book:never-synced" in reason


def test_trade_id_gap_kills_only_its_window():
    store = DepthStore()
    store.apply_trade("BTCUSDT", _trade_payload(1, 60000.0))
    store.apply_trade("BTCUSDT", _trade_payload(5, 60001.0, ts_ms=T0MS + 1100))
    _, flow, _ = book_flow_for("BTCUSDT", T0MS + 1100, store)
    assert flow is not None and flow.last_id == 1  # first window: complete.
    store.apply_trade("BTCUSDT", _trade_payload(6, 60002.0, ts_ms=T0MS + 2100))
    _, flow, reason = book_flow_for("BTCUSDT", T0MS + 2100, store)
    assert flow is None and "flow:trade-id-gap" in reason  # 1 -> 5 skips ids.
    # Next window re-anchors (chain-resync) instead of poisoning forever.
    store.apply_trade("BTCUSDT", _trade_payload(7, 60003.0, ts_ms=T0MS + 3100))
    _, flow, reason = book_flow_for("BTCUSDT", T0MS + 3100, store)
    assert flow is not None and flow.completeness == "chain-resync"
    assert flow.last_id == 6 and "flow:" not in reason


def test_window_incomplete_until_a_later_trade_closes_it():
    store = DepthStore()
    store.apply_trade("BTCUSDT", _trade_payload(1, 60000.0))
    _, flow, reason = book_flow_for("BTCUSDT", T0MS + 100, store)
    assert flow is None and reason == "book:never-synced; flow:window-incomplete"


def test_views_are_frozen_and_store_is_bounded():
    store = DepthStore()
    store.apply_snapshot_record(_snap())
    store.apply_trade("BTCUSDT", _trade_payload(1, 60000.0))
    store.apply_trade("BTCUSDT", _trade_payload(2, 60001.0, ts_ms=T0MS + 1100))
    book, flow, _ = book_flow_for("BTCUSDT", T0MS + 1100, store)
    with pytest.raises(Exception):
        book.ts_ms = 0  # frozen dataclass.
    with pytest.raises(Exception):
        flow.last_id = 0
    # Bounded: one open window + one closed aggregate per symbol.
    state = store._flow["BTCUSDT"]
    assert len(state["trades"]) == 1 and state["closed"] is not None
