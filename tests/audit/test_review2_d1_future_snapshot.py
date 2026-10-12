"""Review-2 defect 1: future snapshots visible at replay startup (W5-24H).

_prime_replay_books installs every snapshot before any events. Two
snapshots at 1000ms and 9000ms, then a 1500ms query, expose the later
bid 200 with sync_age_ms=-7500 and quality=clean.

Required: interleave snapshots, diffs and availability/sync boundaries
causally. Never publish negative-age data as clean. Future snapshot
mutations must not affect earlier state, signals, fills or equity.

Fails on base 3cadfca (bug reproduced); passes once the causal fix
lands. Strict-xfail marked in tests/audit/conftest.py while open.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.market_data.views import DepthStore


def _snap(symbol, recv_ms, last_update_id, bid, ask):
    return {"symbol": symbol, "bids": [[str(bid), "1.0"]],
            "asks": [[str(ask), "1.0"]],
            "last_update_id": last_update_id, "rest_recv_ms": recv_ms}


def _primed(late_bid=200.0):
    store = DepthStore()
    assert store.apply_snapshot_record(
        _snap("BTCUSDT", 1000, 100, 100.0, 101.0)) == "synced"
    assert store.apply_snapshot_record(
        _snap("BTCUSDT", 9000, 200, late_bid, late_bid + 1.0)) == "synced"
    return store


def test_asof_query_excludes_future_snapshot():
    """1500ms query must not see the 9000ms bid 200 as clean."""
    store = _primed()
    book, _, reason = store.book_flow_for("BTCUSDT", 1500)
    if book is None:
        assert reason, "refusing the query is honest only with a reason"
        return
    assert book.bids[0][0] == 100.0, (
        f"as-of 1500ms shows bid {book.bids[0][0]} from the 9000ms future")
    assert book.sync_age_ms >= 0, (
        f"negative sync age {book.sync_age_ms}ms published")
    assert not (book.quality == "clean" and book.sync_age_ms < 0), (
        "negative-age data published as clean")


def test_future_snapshot_mutation_does_not_affect_earlier_query():
    """Changing the 9000ms snapshot must not move the 1500ms view."""
    early_a = _primed(late_bid=200.0).book_flow_for("BTCUSDT", 1500)
    early_b = _primed(late_bid=300.0).book_flow_for("BTCUSDT", 1500)
    key = lambda got: (None if got[0] is None
                       else (got[0].bids[0][0], got[0].sync_age_ms,
                             got[0].quality))
    assert key(early_a) == key(early_b), (
        f"future mutation changed earlier state: {key(early_a)} vs "
        f"{key(early_b)}")
