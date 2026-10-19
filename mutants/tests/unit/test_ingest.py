"""REL-W3-DATA (2): bounded ingest, depth integrity, overload (synthetic)."""
from __future__ import annotations

import pytest

from cryptobot.market_data.depth import MAX_BUFFER, DepthBook
from cryptobot.market_data.ingest import BoundedIngest


def _diff(first, prev, last=None):
    last = prev + 1 if last is None else last
    return {"first_update": first, "prev_last_update": prev,
            "last_update": last, "bids": [[100.0, 1.0]], "asks": []}


def test_market_drop_oldest_is_counted_and_loud():
    ingest = BoundedIngest(["BTCUSDT"], market_max=2)
    assert ingest.publish_market("BTCUSDT", "aggTrade", {"a": 1})
    assert ingest.publish_market("BTCUSDT", "aggTrade", {"a": 2})
    assert ingest.publish_market("BTCUSDT", "aggTrade", "a3-kept")
    stats = ingest.report()["symbols"]["BTCUSDT"]["channels"]["aggTrade"]
    assert stats["received"] == 3
    assert stats["dropped"] == 1
    assert stats["last_drop_reason"] == "market-queue-full"
    assert stats["last_drop_ts_ms"] > 0
    assert ingest.poll_market("BTCUSDT") == ("aggTrade", {"a": 2})
    assert ingest.entries_hold_reason("BTCUSDT") == "ingest:shedding:BTCUSDT"


def test_depth_never_dropped_backpressure_resyncs():
    ingest = BoundedIngest(["BTCUSDT"], depth_max=2)
    assert ingest.publish_diff("BTCUSDT", _diff(1, 0)) == "queued"
    assert ingest.publish_diff("BTCUSDT", _diff(2, 1)) == "queued"
    assert ingest.publish_diff("BTCUSDT", _diff(3, 2)) == "resync-requested"
    rep = ingest.report()["symbols"]["BTCUSDT"]
    assert rep["resyncs_requested"] == 1
    assert rep["resync_pending"] is True
    assert rep["depth_qsize"] == 2  # queued diffs preserved for the drain.
    assert rep["channels"]["depth"]["dropped"] == 0
    assert (ingest.entries_hold_reason()
            == "ingest:depth-resync-pending:BTCUSDT")


def test_chain_break_recorded_with_ids_and_stops_drain():
    ingest = BoundedIngest(["BTCUSDT"])
    assert ingest.install_snapshot("BTCUSDT", [["100.0", "1.0"]], [], 10) == "synced"
    assert ingest.publish_diff("BTCUSDT", _diff(11, 10)) == "queued"
    assert ingest.publish_diff("BTCUSDT", _diff(99, 98)) == "queued"
    outcomes = ingest.drain_depth("BTCUSDT")
    assert outcomes == ["applied", "resync"]
    book = ingest.report()["symbols"]["BTCUSDT"]["book"]
    assert book["chain_breaks"] == 1
    assert book["last_reason"] == "chain-break"
    assert ingest.book_state("BTCUSDT").synced is False
    assert ingest.entries_hold_reason("BTCUSDT") is not None


def test_overload_threshold_and_recovery():
    ingest = BoundedIngest(["BTCUSDT"], market_max=1, overload_after_drops=2)
    ingest.publish_market("BTCUSDT", "bookTicker", "a")
    ingest.publish_market("BTCUSDT", "bookTicker", "b")  # drop 1.
    assert ingest.entries_hold_reason("BTCUSDT") == "ingest:shedding:BTCUSDT"
    ingest.publish_market("BTCUSDT", "bookTicker", "c")  # drop 2.
    assert ingest.entries_hold_reason("BTCUSDT") == "ingest:overloaded:BTCUSDT"
    assert ingest.poll_market("BTCUSDT") == ("bookTicker", "c")
    assert ingest.poll_market("BTCUSDT") is None
    # Queues drained but state recovers only via drain_depth/install path.
    assert ingest.entries_hold_reason("BTCUSDT") == "ingest:overloaded:BTCUSDT"
    ingest.drain_depth("BTCUSDT")  # no-op drain re-evaluates recovery.
    assert ingest.entries_hold_reason("BTCUSDT") is None


def test_exposure_readers_available_under_overload():
    ingest = BoundedIngest(["BTCUSDT"], market_max=1)
    ingest.install_snapshot("BTCUSDT", [["100.0", "2.0"]],
                            [["100.5", "1.0"]], 10)
    ingest.publish_market("BTCUSDT", "aggTrade", "a")
    ingest.publish_market("BTCUSDT", "aggTrade", "b")  # shedding now.
    assert ingest.entries_hold_reason("BTCUSDT") is not None
    state = ingest.book_state("BTCUSDT")  # never gated, never raises.
    assert state.synced is True
    assert ingest.report()["symbols"]["BTCUSDT"]["market_qsize"] == 1


def test_depth_buffer_bound_resyncs_loudly():
    book = DepthBook("BTCUSDT")
    for i in range(MAX_BUFFER):
        assert book.on_diff(_diff(i + 1, i)) == "buffered"
    assert book.on_diff(_diff(MAX_BUFFER + 1, MAX_BUFFER)) == "resync"
    assert book.state.buffer_overflows == 1
    assert book.state.last_reason == "buffer-overflow"


def test_pending_break_clears_on_sync_and_round_trips():
    import json
    book = DepthBook("BTCUSDT")
    book.on_snapshot([["100.0", "1.0"]], [], 10)
    assert book.on_diff(_diff(50, 49)) == "resync"
    assert book.pending_break == {"expected_prev_last_update": 10,
                                  "got_prev_last_update": 49,
                                  "first_update": 50, "last_update": 50}
    raw = json.loads(json.dumps(book.to_dict()))
    assert DepthBook.from_dict(raw).to_dict() == raw
    book.on_snapshot([["100.0", "1.0"]], [], 60)
    assert book.pending_break is None
    # Legacy checkpoint without the new keys still loads.
    legacy = {"symbol": "X", "bids": [], "asks": [], "synced": False,
              "last_update_id": 0, "buffer": [], "resyncs": 0,
              "applied": 0, "dropped_stale": 0, "resync_reason": ""}
    assert DepthBook.from_dict(legacy).state.chain_breaks == 0


def test_bounds_validated():
    with pytest.raises(ValueError):
        BoundedIngest(["BTCUSDT"], market_max=0)
    with pytest.raises(ValueError):
        BoundedIngest(["BTCUSDT"], depth_max=0)
