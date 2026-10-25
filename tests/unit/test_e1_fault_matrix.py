"""E1 fault-injection matrix: the REAL BinanceLiveEngine over real sockets
to the in-repo Binance emulator (MockEx), fully offline.

Every test injects one fault on the venue, then asserts an invariant about
the engine and the VENUE'S OWN state (positions, orders, request log), never
only about the engine's belief. Matrix rows (see E1_MATRIX in the PR body):

  a  HTTP 429 / 418 + Retry-After       backoff honoured, no order storm
  b  -1003 request weight               same guard, any HTTP status
  c  -1021 timestamp skew               resync, retry exactly once
  d  5xx / reset / read timeout         lookup-by-clientOrderId, no duplicate
  e  partial fill then cancel/expiry    position == filled, stop resized
  f  websocket drop / listenKey expiry  reconnect heal, no missed fill
  g  process killed mid-entry           restart adopts, no orphan order
  h  venue rejects                      clean refusal, consistent state
  i  -2013 unknown-order race           grace window, never a premature void
  k  clock step during a run            resync, entries halted when absurd

(j, safety rails and the credentialed drill live in sibling files.)
"""
from __future__ import annotations

import time

import pytest

import e1_harness as h
from cryptobot.adapters.binance_live import (
    RateLimitedError,
    UnknownOutcomeError,
    VenueRejectedError,
)
from cryptobot.app.engine import EngineOrder


@pytest.fixture()
def emu(tmp_path):
    e = h.Emu(tmp_path)
    try:
        yield e
    finally:
        e.close()


def _advance(emu: h.Emu, seconds: float) -> None:
    """Move local AND venue clocks together (a quiet passage of time)."""
    emu.clock.step(seconds)
    emu.mock.clock_offset_ms += int(seconds * 1000)


# ---------------------------------------------------------------- a: 429 / 418
@pytest.mark.parametrize("action,status,retry_after", [
    ("rate-limit", 429, 120),
    ("rate-limit-418", 418, 3600),
])
def test_a_retry_after_is_honoured_and_no_order_storm(
        emu, action, status, retry_after):
    """E1-a: the venue's Retry-After sets the refuse-fast window; the
    engine then sends NOTHING (no storm) until it has passed."""
    engine = emu.ready_engine()
    emu.fault("POST:order", action, retry_after_s=retry_after)
    before = len(emu.venue.log)
    with pytest.raises(RateLimitedError) as info:
        engine.submit(h.market_buy())
    assert info.value.status == status
    assert info.value.retry_after_s >= retry_after, \
        "Retry-After shorter than the venue asked for"
    sent_after_first = len(emu.venue.log)
    assert sent_after_first == before + 1  # exactly the one rejected POST
    for _ in range(25):  # a hot loop hammering submit
        with pytest.raises(RateLimitedError):
            engine.submit(h.market_buy())
    assert len(emu.venue.log) == sent_after_first, \
        "requests reached the venue inside the ban window"
    assert emu.order_posts() == 1 and emu.position() == 0.0
    # Reads are refused inside the window too (a 418 ban is extended by
    # probing it).
    cid = engine.journal_client_ids()[0]
    with pytest.raises(RateLimitedError):
        engine.lookup(cid)
    assert len(emu.venue.log) == sent_after_first
    window = [r for r in h.journal(engine, "rate-limited")]
    assert window and window[-1]["backoff_s"] >= retry_after


def test_a_orders_resume_exactly_once_after_the_window(emu):
    """E1-a: once the window has passed one retry succeeds, one position."""
    engine = emu.ready_engine()
    emu.fault("POST:order", "rate-limit", retry_after_s=90)
    with pytest.raises(RateLimitedError):
        engine.submit(h.market_buy())
    _advance(emu, 89)
    with pytest.raises(RateLimitedError):  # still inside Retry-After
        engine.submit(h.market_buy())
    _advance(emu, 2)
    cid = engine.submit(h.market_buy())
    assert emu.position() == pytest.approx(0.002)
    assert engine.order_status(cid).state == "filled"
    assert emu.order_posts() == 2  # one refused (429) + one executed


def test_a_cancels_still_reach_the_venue_inside_the_window(emu):
    """E1-a: backing off must never strand a resting order: cancels attempt."""
    engine = emu.ready_engine()
    price = round(emu.venue.book(h.BTC)["bid"] * 0.9, 1)  # rests, no fill
    cid = engine.submit(EngineOrder(h.BTC, "BUY", 0.002, "LIMIT", price=price,
                                    reservation_id="r1"))
    emu.venue.orders[emu.venue.by_client[cid]]["status"] = "NEW"
    emu.fault("POST:order", "rate-limit", retry_after_s=300)
    with pytest.raises(RateLimitedError):
        engine.submit(h.market_buy(reservation="r2"))
    seen = len(emu.requests("DELETE", "/fapi/v1/order"))
    engine.cancel(cid, "test")
    assert len(emu.requests("DELETE", "/fapi/v1/order")) == seen + 1


# ------------------------------------------------------------- b: -1003 weight
def test_b_minus_1003_without_429_is_a_rate_limit(emu):
    """E1-b: -1003 on HTTP 400 (no 429 status) still trips the guard."""
    engine = emu.ready_engine()
    emu.fault("POST:order", "http-error", status=400, code=-1003,
              msg="Too many requests; current limit of IP(s) is 2400 "
                  "requests per minute.")
    with pytest.raises(RateLimitedError) as info:
        engine.submit(h.market_buy())
    assert info.value.code == -1003
    sent = len(emu.venue.log)
    for _ in range(10):
        with pytest.raises(RateLimitedError):
            engine.submit(h.market_buy())
    assert len(emu.venue.log) == sent and emu.position() == 0.0


def test_b_minus_1003_on_a_read_blocks_the_next_submit(emu):
    """E1-b: weight exhaustion seen on a READ also guards submits."""
    engine = emu.ready_engine()
    emu.fault("GET:account", "http-error", status=429, code=-1003,
              msg="Way too many requests", retry_after_s=60)
    with pytest.raises(RateLimitedError):
        engine._signed("GET", "/fapi/v2/account")
    sent = len(emu.venue.log)
    with pytest.raises(RateLimitedError):
        engine.submit(h.market_buy())
    assert len(emu.venue.log) == sent and emu.position() == 0.0


# --------------------------------------------------------------- c: -1021 skew
def test_c_timestamp_skew_resyncs_and_retries_exactly_once(emu):
    """E1-c: the local clock jumps 10s; the order is refused BEFORE
    executing (-1021), the offset is re-read and the retry executes once."""
    engine = emu.ready_engine()
    emu.clock.step(10.0)  # local ahead of the venue by 10s > recvWindow
    cid = engine.submit(h.market_buy())
    refused = [r for r in emu.mock.refusals
               if r["path"] == "/fapi/v1/order" and r["code"] == -1021]
    assert len(refused) == 1, "expected exactly one -1021 refusal"
    assert len(emu.requests("POST", "/fapi/v1/order")) == 1  # the retry
    assert len(emu.venue.orders) == 1, "the refused POST must not execute"
    assert emu.position() == pytest.approx(0.002)
    assert engine.order_status(cid).state == "filled"
    assert abs(engine._offset_ms + 10_000) < 1500
    assert [r for r in h.journal(engine, "clock-resync")]


def test_c_persistent_skew_is_refused_after_exactly_one_retry(emu):
    """E1-c: a second -1021 is a real rejection: no third attempt, no
    position, and the intent is journaled rejected (retry-safe)."""
    engine = emu.ready_engine()
    emu.fault("POST:order", "http-error", status=400, code=-1021,
              msg="Timestamp for this request is outside of the recvWindow.",
              times=2)
    with pytest.raises(VenueRejectedError) as info:
        engine.submit(h.market_buy())
    assert info.value.code == -1021
    assert len(emu.requests("POST", "/fapi/v1/order")) == 2
    assert emu.position() == 0.0 and not emu.venue.orders
    cid = engine.journal_client_ids()[0]
    assert engine.order_status(cid).state == "rejected"
    assert not engine.unknown_ids()


# ------------------------------------------------- d: 5xx / reset / read timeout
@pytest.mark.parametrize("action", ["gateway-502", "gateway-504", "unknown",
                                    "timeout"])
def test_d_executed_then_response_lost_never_duplicates(emu, action):
    """E1-d: the venue EXECUTES the order and the answer is lost (502/504/
    503, or the connection is cut). The engine must resolve by
    clientOrderId lookup; position stays exactly one order's worth."""
    engine = emu.ready_engine()
    emu.fault("POST:order", action, phase="after")
    with pytest.raises(UnknownOutcomeError) as info:
        engine.submit(h.market_buy(reservation="r1"))
    cid = info.value.client_id
    assert emu.position() == pytest.approx(0.002)  # it DID execute
    assert engine.unknown_ids() == (cid,)
    posts = emu.order_posts()
    # a retry for the same reservation is refused without touching the venue
    with pytest.raises(UnknownOutcomeError):
        engine.submit(h.market_buy(reservation="r1"))
    assert emu.order_posts() == posts
    status = engine.lookup(cid)
    assert status.state == "filled" and status.filled_qty == pytest.approx(0.002)
    assert not engine.unknown_ids()
    assert emu.position() == pytest.approx(0.002)
    assert len(emu.venue.orders) == 1
    adopted = h.journal(engine, "fill-adopted")
    assert len(adopted) == 1  # the fill is booked once, from the tape


def test_d_rejected_before_execution_resolves_to_void_then_one_retry(emu):
    """E1-d: a 503 that never reached the matching engine: lookup -2013 is
    graced (not voided on one miss), then voided, then ONE new order."""
    engine = emu.ready_engine()
    emu.fault("POST:order", "unknown")  # raised BEFORE the venue acts
    with pytest.raises(UnknownOutcomeError) as info:
        engine.submit(h.market_buy(reservation="r1"))
    cid = info.value.client_id
    assert emu.position() == 0.0 and not emu.venue.orders
    st = engine.lookup(cid)  # first miss: grace, state kept unknown
    assert st is not None and st.state == "unknown"
    with pytest.raises(UnknownOutcomeError):
        engine.submit(h.market_buy(reservation="r1"))  # still blocked
    _advance(emu, 2)
    engine.lookup(cid)
    _advance(emu, 2)
    assert engine.lookup(cid) is None  # 3 misses over >3s: void proven
    assert not engine.unknown_ids()
    cid2 = engine.submit(h.market_buy(reservation="r1"))
    assert cid2 != cid and emu.position() == pytest.approx(0.002)
    assert len(emu.venue.orders) == 1


def test_d_read_timeout_mid_order_then_late_execution(emu):
    """E1-d: the venue stalls past the client's read timeout and executes
    LATE. Timeout -> UNKNOWN; a lookup that races ahead of the venue is a
    graced miss; after the venue finishes the lookup adopts the fill."""
    engine = emu.ready_engine(timeout_s=0.3)
    emu.fault("POST:order", "stall", delay_s=1.2)
    with pytest.raises(UnknownOutcomeError) as info:
        engine.submit(h.market_buy(reservation="r1"))
    cid = info.value.client_id
    early = engine.lookup(cid)  # venue still stalling: not yet indexed
    assert early is None or early.state == "unknown"
    assert engine.unknown_ids() == (cid,), "one miss must not void"
    time.sleep(1.4)
    status = engine.lookup(cid)
    assert status.state == "filled"
    assert emu.position() == pytest.approx(0.002) and len(emu.venue.orders) == 1


def test_d_resending_an_executed_client_id_is_idempotent_at_the_venue(emu):
    """E1-d: even a blind re-POST of the journaled params cannot add
    exposure: the venue dedups by newClientOrderId (-2013 duplicate)."""
    engine = emu.ready_engine()
    cid = engine.submit(h.market_buy())
    intent = h.journal(engine, "submit-intent")[0]
    with pytest.raises(Exception) as info:
        engine._signed("POST", "/fapi/v1/order", intent["params"])
    assert getattr(info.value, "code", None) == -2013
    assert emu.position() == pytest.approx(0.002)
    assert engine.order_status(cid).state == "filled"


# ------------------------------------------- e: partial fill, cancel / expiry
def _partial_entry(emu, engine, reservation="r1"):
    """A marketable IOC limit that the book can only half fill."""
    emu.venue.set_size(h.BTC, 0.001)  # harness restores module state
    ask = emu.venue.book(h.BTC)["ask"]
    return engine.submit(EngineOrder(
        h.BTC, "BUY", 0.002, "LIMIT", price=round(ask * 1.01, 1),
        reservation_id=reservation, role="entry"))


def _working_algos(emu):
    return [r for r in emu.venue.algos.values() if r["status"] == "WORKING"]


def test_e_partial_fill_then_expiry_protects_exactly_the_filled_qty(emu):
    """E1-e: 0.001 of 0.002 fills, the venue expires the remainder. The
    position is the FILLED qty and both reduce-only legs cover exactly it."""
    engine = emu.ready_engine()
    cid = _partial_entry(emu, engine)
    emu.venue.expire_order(cid)
    status = engine.lookup(cid)
    assert status.state == "expired"
    assert status.filled_qty == pytest.approx(0.001)
    assert emu.position() == pytest.approx(0.001)
    legs = engine.attach_protection(cid, 59_000.0, 61_000.0)
    algos = _working_algos(emu)
    assert len(legs) == 2 and len(algos) == 2
    assert {round(a["qty"], 6) for a in algos} == {0.001}, \
        "protective legs must be sized to the filled qty, not the order"
    assert all(a["reduce_only"] for a in algos)
    assert [a["kind"] for a in algos][0] == "STOP_MARKET"  # stop first


def test_e_partial_fill_then_cancel_adopts_fill_and_resizes_cover(emu):
    """E1-e: cancel of a part-filled entry; the fill is adopted from the
    tape and an oversized stop is replaced by one sized to the position."""
    engine = emu.ready_engine()
    cid = _partial_entry(emu, engine)
    # The entry is still live, so cover was first sized to the whole order
    # (the venue accepts it: clipped at trigger).
    big = engine.submit(EngineOrder(
        h.BTC, "SELL", 0.002, "STOP_MARKET", stop_price=59_000.0,
        reduce_only=True, reservation_id="r1", role="stop"))
    assert _working_algos(emu)[0]["qty"] == pytest.approx(0.002)
    engine.cancel(cid, "remainder-cancel")
    status = engine.lookup(cid)
    assert status.state == "cancelled"
    assert status.filled_qty == pytest.approx(0.001) == pytest.approx(
        emu.position())
    engine.cancel(big, "resize")  # algo rail cancel
    assert not _working_algos(emu)
    legs = engine.attach_protection(cid, 59_000.0, None)
    algos = _working_algos(emu)
    assert len(legs) == 1 and len(algos) == 1
    assert algos[0]["qty"] == pytest.approx(emu.position()) == pytest.approx(0.001)


# ------------------------------------------- f: websocket drop / listenKey expiry
class _ScriptSocket:
    """Deterministic socket boundary; REST reconcile still hits MockEx."""

    def __init__(self):
        self.events = []
        self.closed = False

    def recv(self, timeout_s):
        if not self.events:
            return None
        item = self.events.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self):
        self.closed = True


def _stream(emu, engine):
    from cryptobot.adapters.user_stream import attach_user_stream
    sockets = []

    def factory(key):
        sock = _ScriptSocket()
        sockets.append((key, sock))
        return sock

    attachment = attach_user_stream(
        None, engine, factory, start_thread=False, initial_backoff_s=0.0,
        max_backoff_s=0.0)
    return attachment, sockets


def test_f_fill_lost_while_the_socket_was_down_is_adopted_on_heal(emu):
    """E1-f: the TRADE event is lost; reconnect REST-reconciles the
    terminal order and adopts exactly once before entries are re-enabled."""
    engine = emu.ready_engine()
    cid = engine.submit(h.market_buy())
    emu.venue.stream_queue.clear()
    assert engine.filled_qty(cid) == 0.0
    stream, sockets = _stream(emu, engine)
    try:
        assert stream.halted
        with pytest.raises(ValueError, match="exit-only"):
            engine.submit(h.market_buy(reservation="r2"))
        assert stream.poll_once() == "healed"
        assert len(sockets) == 1 and not stream.halted
        assert engine.filled_qty(cid) == pytest.approx(emu.position()) \
            == pytest.approx(0.002)
        assert len(h.journal(engine, "fill-adopted")) == 1
        engine.stream_reconnected()
        assert len(h.journal(engine, "fill-adopted")) == 1
    finally:
        stream.close()


def test_f_stream_and_rest_report_the_same_fill_once(emu):
    """E1-f: same trade via socket and REST heal is deduped by trade id."""
    engine = emu.ready_engine()
    cid = engine.submit(h.market_buy())
    event = emu.venue.stream_queue.pop(0)
    stream, sockets = _stream(emu, engine)
    try:
        stream.poll_once()  # connection performs REST heal first
        sockets[0][1].events.append(event)
        assert stream.poll_once() == "event"
        engine.lookup(cid)
        assert engine.filled_qty(cid) == pytest.approx(0.002)
        assert len(h.journal(engine, "fill-adopted")) == 1
        assert sum(float(t["qty"]) for t in emu.trades()) == pytest.approx(0.002)
    finally:
        stream.close()


def test_f_socket_drop_reconnects_and_heals_a_fill_gap(emu):
    """E1-f: socket death redials, REST-reconciles a lost fill and keeps
    the stream halt until the reconnect heal is complete."""
    engine = emu.ready_engine()
    stream, sockets = _stream(emu, engine)
    try:
        stream.poll_once()
        assert not stream.halted
        cid = engine.submit(h.market_buy())
        emu.venue.stream_queue.clear()
        sockets[0][1].events.append(ConnectionError("scripted socket drop"))
        assert stream.poll_once() == "healed"
        assert len(sockets) == 2
        assert not stream.halted
        assert engine.filled_qty(cid) == pytest.approx(emu.position())
        assert len(h.journal(engine, "fill-adopted")) == 1
    finally:
        stream.close()


def test_f_listen_key_expiry_reopens_a_key_and_heals(emu):
    """E1-f: expiry drops the dead key; reconnect creates a fresh key and
    heals a fill missed during the outage."""
    engine = emu.ready_engine()
    stream, sockets = _stream(emu, engine)
    try:
        stream.poll_once()
        first_key = engine.listen_key
        assert first_key and not stream.halted
        cid = engine.submit(h.market_buy())
        emu.venue.stream_queue.clear()
        sockets[0][1].events.append({"e": "listenKeyExpired", "E": 1})
        assert stream.poll_once() == "event"
        assert stream.halted and engine.listen_key is None
        assert stream.poll_once() == "healed"
        assert len(sockets) == 2 and engine.listen_key != first_key
        assert not stream.halted
        assert engine.filled_qty(cid) == pytest.approx(emu.position())
        assert len(h.journal(engine, "fill-adopted")) == 1
    finally:
        stream.close()
