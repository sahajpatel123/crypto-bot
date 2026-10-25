"""Live contract-v1 tests (Worker 2, release Checkpoint A)."""
import copy
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

import venue_fixtures as venues
from cryptobot.adapters.binance_live import (
    RateLimitedError,
    UnknownOutcomeError,
    VenueRejectedError,
    caller_action,
)
from cryptobot.app.engine import EngineOrder

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "binance_live"
T0MS = venues.T0MS
NOW = venues.NOW
ReplayTransport = venues.ReplayTransport
_live = venues.make_engine
_ready_script = venues.ready_script
_ready = venues.ready_fixture
_orders = venues.orders_fixture


def _journal_cid(tmp_path):
    for line in (tmp_path / "live.jsonl").read_text(
            encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("event") == "submit-intent":
            return str(record["client_id"])
    raise AssertionError("no submit-intent journaled")


def _submit_market(engine):
    return engine.submit(EngineOrder("BTCUSDT", "BUY", 0.002, "MARKET",
                                     reservation_id="r1"))


def test_order_status_never_seen_is_none(tmp_path):
    engine, _ = _live(tmp_path, [])
    assert engine.order_status("nope") is None
    assert engine.unknown_ids() == ()


def test_order_status_open_then_filled_with_versions(tmp_path):
    ready, orders = _ready(), _orders()
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("ok", orders["orderAck"]))])
    cid = _submit_market(engine)
    opened = engine.order_status(cid)
    assert opened.state == "open"
    assert opened.qty == 0.002 and opened.filled_qty == 0.0
    assert opened.reservation_id == "r1" and opened.role == "entry"
    assert opened.version == 2  # submit-intent + submitted.
    transport.append(
        ("GET", "/fapi/v1/order", {"origClientOrderId": cid},
         ("ok", orders["orderQueryFilled"])),
        ("GET", "/fapi/v1/userTrades", {"orderId": 12345},
         ("ok", orders["userTrades"])))
    looked = engine.lookup(cid)
    assert looked.state == "filled"
    assert looked.filled_qty == 0.002
    assert looked.version > opened.version
    assert engine.order_status(cid).version == looked.version
    transport.assert_empty()


def test_order_status_unknown_and_void_shapes(tmp_path):
    ready = _ready()
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("err", 503, None, "gateway"))])
    with pytest.raises(UnknownOutcomeError):
        _submit_market(engine)
    (cid,) = engine.unknown_ids()
    assert engine.order_status(cid).state == "unknown"
    assert engine.unknown_ids() == (cid,)
    # The -2013 grace window is pinned in test_execution_defects; expire it so
    # this test stays about what a PROVEN void means for the order and blocks.
    engine.VOID_MISS_REQUIRED, engine.VOID_GRACE_MS = 1, 0
    transport.append(
        ("GET", "/fapi/v1/order", {"origClientOrderId": cid},
         ("err", 400, -2013, "Order does not exist.")))
    assert engine.lookup(cid) is None
    voided = engine.order_status(cid)
    assert voided.state == "cancelled"  # void: terminal, zero-fill.
    assert voided.filled_qty == 0.0
    assert engine.unknown_ids() == ()
    transport.assert_empty()


def test_unknown_ids_includes_cancel_unknown(tmp_path):
    ready, orders = _ready(), _orders()
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("ok", orders["orderAck"])),
            ("DELETE", "/fapi/v1/order", {"origClientOrderId": "x"},
             ("err", 503, None, "gateway"))])
    cid = _submit_market(engine)
    script = transport.script
    script[-1] = ("DELETE", "/fapi/v1/order", {"origClientOrderId": cid},
                  ("err", 503, None, "gateway"))
    with pytest.raises(UnknownOutcomeError):
        engine.cancel(cid, "test")
    assert engine.unknown_ids() == (cid,)
    assert engine.order_status(cid).state == "unknown"
    transport.assert_empty()


def test_submit_deterministic_reject_emits_terminal(tmp_path):
    ready = _ready()
    pushed: list = []
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("err", 400, -1111, "Precision is over the maximum"))])
    engine.bind_sink(pushed.append)
    with pytest.raises(VenueRejectedError):
        _submit_market(engine)
    cid = _journal_cid(tmp_path)
    assert engine.order_status(cid).state == "rejected"
    rejects = [e for e in pushed if e.kind == "reject"]
    assert len(rejects) == 1
    assert engine.poll() == []
    transport.assert_empty()


def test_cancel_acked_emits_cancel_once(tmp_path):
    ready, orders = _ready(), _orders()
    pushed: list = []
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("ok", orders["orderAck"]))])
    engine.bind_sink(pushed.append)
    cid = _submit_market(engine)
    transport.append(
        ("DELETE", "/fapi/v1/order", {"origClientOrderId": cid},
         ("ok", {"status": "CANCELED"})))
    engine.cancel(cid, "test")
    assert [e.kind for e in pushed] == ["cancel"]
    assert engine.order_status(cid).state == "cancelled"
    # A later lookup observing the same terminal emits nothing new.
    transport.append(
        ("GET", "/fapi/v1/order", {"origClientOrderId": cid},
         ("ok", {"orderId": 1, "status": "CANCELED", "executedQty": "0.0",
                 "origQty": "0.002"})))
    engine.lookup(cid)
    assert [e.kind for e in pushed] == ["cancel"]
    transport.assert_empty()


def test_rate_limit_backoff_protects_cancel_capacity(tmp_path):
    ready, orders = _ready(), _orders()
    now_ms = [T0MS]
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("err", 429, -1003, "rate limited"))],
        now_utc=lambda: datetime.fromtimestamp(now_ms[0] / 1000,
                                               tz=UTC))
    with pytest.raises(RateLimitedError) as exc:
        _submit_market(engine)
    assert exc.value.retry_after_s == 60.0
    assert caller_action(exc.value) == "retry_safe"
    assert engine.order_status(_journal_cid(tmp_path)).state == "rejected"
    # Inside the window, submits AND reads refuse WITHOUT sending...
    with pytest.raises(RateLimitedError):
        engine.submit(EngineOrder("BTCUSDT", "BUY", 0.002, "MARKET"))
    with pytest.raises(RateLimitedError):
        engine.open_orders()
    assert transport.requests and len(transport.requests) == 6  # ready + 1 POST
    # ...while cancels still attempt the venue.
    transport.append(
        ("POST", "/fapi/v1/order", {"type": "MARKET"},
         ("ok", orders["orderAck"])))
    now_ms[0] += 61_000  # window passes: submits flow again.
    cid = _submit_market(engine)
    transport.append(
        ("DELETE", "/fapi/v1/order", {"origClientOrderId": cid},
         ("err", 429, -1003, "rate limited")))
    with pytest.raises(RateLimitedError):
        engine.cancel(cid, "test")  # attempted: DELETE was sent.
    assert transport.requests[-1][1] == "/fapi/v1/order"
    transport.assert_empty()


def test_versions_rebuild_across_restart(tmp_path):
    ready, orders = _ready(), _orders()
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("ok", orders["orderAck"]))])
    cid = _submit_market(engine)
    v0 = engine.order_status(cid).version
    engine2, _ = _live(tmp_path, [])
    assert engine2.order_status(cid).version == v0
    assert engine2.order_status(cid).state == "open"


def test_bind_sink_rejects_direct_booking_sinks(tmp_path):
    class Sink:
        def note_fill_delta(self, *args):
            raise AssertionError("must never be invoked")

    engine, _ = _live(tmp_path, [])
    with pytest.raises(TypeError, match="EngineEvent callable"):
        engine.bind_sink(Sink())
    with pytest.raises(TypeError, match="EngineEvent callable"):
        engine.bind_sink(object())
    with pytest.raises(TypeError, match="EngineEvent callable"):
        engine.recover(Sink())


def test_stream_fill_pushes_through_bound_handler(tmp_path):
    ready, orders = _ready(), _orders()
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("ok", orders["orderAck"]))])
    pushed: list = []
    engine.bind_sink(pushed.append)
    cid = _submit_market(engine)
    stream = copy.deepcopy(orders["userStreamTrade"])
    stream["o"]["c"] = cid
    engine.note_user_event(stream)
    assert len([e for e in pushed if e.kind == "fill"]) == 1
    assert engine.poll() == []
    transport.assert_empty()


def test_user_stream_url_pinned_per_host(tmp_path):
    from cryptobot.adapters.binance_live import PROD_FAPI_URL
    demo, _ = _live(tmp_path, [], demo=True)
    assert demo.user_stream_url("K1") == \
        "wss://demo-fstream.binance.com/ws/K1"
    prod, _ = _live(tmp_path, [], base_url=PROD_FAPI_URL)
    assert prod.user_stream_url("K1") == \
        "wss://fstream.binance.com/ws/K1"  # fstream, not fapi.
    testnet, _ = _live(tmp_path, [])
    assert testnet.user_stream_url("K1") == \
        "wss://stream.binancefuture.com/ws/K1"
    with pytest.raises(ValueError, match="non-empty"):
        demo.user_stream_url("")
    custom, _ = _live(tmp_path, [], base_url="https://example.com")
    with pytest.raises(ValueError, match="no user-stream host"):
        custom.user_stream_url("K1")
