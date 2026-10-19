"""Causal snapshot/event merge tests (W2, 24H). Fixture streams only."""
from cryptobot.market_data.replayer import replay_events, replay_with_snapshots


def _event(seq, ts_ms):
    return {"seq": seq, "exchange_ts_ms": ts_ms, "local_recv_ms": ts_ms,
            "channel": "aggTrade", "symbol": "BTCUSDT",
            "input_class": "observed-public"}


def _snap(ts_ms, exchange=False):
    snap = {"symbol": "BTCUSDT", "bids": [["100.0", "1.0"]],
            "asks": [["101.0", "1.0"]], "last_update_id": 100,
            "rest_recv_ms": ts_ms}
    if exchange:
        snap["exchange_ts_ms"] = ts_ms
    return snap


def test_snapshot_yielded_before_first_event_at_its_time():
    events = [_event(0, 1000), _event(1, 5000), _event(2, 9000),
              _event(3, 10000)]
    items = list(replay_with_snapshots(events, [_snap(9000, exchange=True)]))
    assert [k for k, _ in items] == ["event", "event", "snapshot",
                                     "event", "event"]
    assert [p for k, p in items if k == "event"] == list(
        replay_events(events))  # event parity: identical subsequence.


def test_future_snapshot_never_yielded():
    events = [_event(0, 1000), _event(1, 2000)]
    items = list(replay_with_snapshots(events, [_snap(99999, exchange=True)]))
    assert [k for k, _ in items] == ["event", "event"]


def test_legacy_snapshot_gets_skew_tolerance_but_views_still_guard():
    # Legacy receipt-clock record 500 ms past the last event still installs
    # (host-skew tolerance); exact-clock records do not.
    events = [_event(0, 1000), _event(1, 2000)]
    legacy = list(replay_with_snapshots(events, [_snap(2500)]))
    # Effective time 1500 (2500 - tol): installs before the t=2000 event.
    assert [k for k, _ in legacy] == ["event", "snapshot", "event"]
    exact = list(replay_with_snapshots(
        events, [_snap(2500, exchange=True)]))
    assert [k for k, _ in exact] == ["event", "event"]


def test_multiple_snapshots_install_in_time_order():
    events = [_event(0, 1000), _event(1, 5000), _event(2, 9000)]
    snaps = [_snap(9000, exchange=True), _snap(1000, exchange=True)]
    items = list(replay_with_snapshots(events, snaps))
    kinds = [k for k, _ in items]
    assert kinds == ["snapshot", "event", "event", "snapshot", "event"]
    snap_times = [p["rest_recv_ms"] for k, p in items if k == "snapshot"]
    assert snap_times == [1000, 9000]
