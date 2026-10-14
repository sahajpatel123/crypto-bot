"""REV2 R1+R2+R3: private-stream ownership regression tests.

R1: the threaded pump is socket-only. Envelopes cross a bounded
queue to the owner; the pump never touches Session, ledger,
SQLite, or engine state. Overflow blocks (never drops) and halts
entries; apply failures park in a ring and halt until
acknowledged; a dead pump is a halt reason, not a silent stall.

R2: streamed fills stay recoverable until the Session confirms
durable booking. Redelivery re-emits (the exec-gate keeps
accounting exact); REST-vs-tape gaps keep orders on the recovery
watch even when terminal.

R3: halt reasons are independent per source. A stream heal
releases only the stream's own reason; Session halts survive it,
and adapter reason sets release per reason.

Converted from the release-review probes (thread-fill defect).
Offline: injected sockets + ReplayTransport, real SQLite store.
"""
import copy
import json
import sys
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import venue_fixtures as venues
from cryptobot.adapters.binance_live import BinanceLiveEngine
from cryptobot.adapters.paper_engine import NautilusPaperEngine
from cryptobot.adapters.user_stream import attach_user_stream
from cryptobot.app.config import load_config
from cryptobot.app.engine import EngineOrder
from cryptobot.coordination.exits import encode_exit_rule, ExitPolicy
from cryptobot.coordination.intent import (DataQuality, ForecastCost,
                                           Intent, Side)
from cryptobot.app.session import Session
from cryptobot.app.store import RunStore
from cryptobot.coordination.selector import Candidate

FIX = venues.FIX
MECHANICS = "mechanic-band"
NOW = datetime(2026, 10, 12, 6, 0, tzinfo=timezone.utc)


class FakeSocket:
    """Scripted envelopes; None = timeout; 'die' kills the socket."""

    def __init__(self, script):
        self.script = deque(script)
        self.closed = False

    def recv(self, timeout_s):
        assert not self.closed
        if not self.script:
            return None
        item = self.script.popleft()
        if item == "die":
            raise ConnectionError("socket died")
        return item

    def close(self):
        self.closed = True


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


def _until(predicate, seconds=5.0):
    end = time.monotonic() + seconds
    while not predicate() and time.monotonic() < end:
        time.sleep(0.005)
    assert predicate(), "bounded wait expired"


def _until_healed(att, seconds=5.0):
    """Drive owner drains until the attachment heals (R1: only the
    owner can connect and heal; the pump never does)."""
    end = time.monotonic() + seconds
    while att.halted and time.monotonic() < end:
        att.drain_owner()
        time.sleep(0.005)
    assert not att.halted, att.halt_reasons()


def _ready():
    return json.loads((FIX / "readiness.json").read_text())


def _orders():
    return json.loads((FIX / "orders.json").read_text())


def _config(tmp_path: Path) -> Path:
    text = open("configs/paper.toml").read()
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    text = text.replace("warmup_bars =", "warmup_bars = 3 #", 1)
    path = tmp_path / "test.toml"
    path.write_text(text)
    return path


def _intent(now: datetime) -> Intent:
    return Intent(
        strategy="S1", version="0.1.0", instrument="BTCUSDT",
        side=Side.LONG, evidence_ts_utc=now,
        entry_low=100.0, entry_high=100.55,
        entry_expiry_utc=now + timedelta(seconds=60),
        invalidation_price=99.0,
        exit_rule=encode_exit_rule(ExitPolicy(
            stop_price=99.0, target_price=102.0,
            time_exit_utc=now + timedelta(seconds=600),
            policy_id="rev2")),
        holding_limit_s=600,
        forecast_cost=ForecastCost(5.0, 5.0, 5.0, 1.0),
        evidence_ref=f"{MECHANICS}:1", data_quality=DataQuality.CLEAN)


def _session(tmp_path: Path, engine, run_id: str):
    cfg = load_config(_config(tmp_path))
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    session = Session(cfg, store, tmp_path / "runs" / run_id, run_id,
                      engine=engine)
    session.clock.set_ms(int(NOW.timestamp() * 1000))
    session.policy.reconcile_day(120.0, 0.0)
    session.store.create_run(run_id, MECHANICS, "fp",
                             str(session.workdir), None)
    session.arm_replay_filters(
        {"BTCUSDT": {"tick_size": 0.10, "step_size": 0.001,
                     "min_qty": 0.001, "min_notional": 5.0}},
        origin=MECHANICS, asof_utc=NOW)
    from cryptobot.app.session import _SymbolFeed
    feed = _SymbolFeed("BTCUSDT", 0)
    feed.mark = 100.0
    feed.mark_ts = NOW
    session._feeds["BTCUSDT"] = feed
    return session, store


def _trade(orders, cid, side, state, last, cum, price, fee, tid):
    trade = copy.deepcopy(orders["userStreamTrade"])
    trade["o"]["c"] = cid
    trade["o"]["S"] = side
    trade["o"]["X"] = state
    trade["o"]["l"] = f"{last:.3f}"
    trade["o"]["z"] = f"{cum:.3f}"
    trade["o"]["L"] = trade["o"]["ap"] = f"{price:.2f}"
    trade["o"]["n"] = f"{fee:.4f}"
    trade["o"]["t"] = tid
    return trade


def _entry():
    return EngineOrder("BTCUSDT", "BUY", 0.010, "MARKET",
                       reservation_id="r-entry")


def _exit():
    return EngineOrder("BTCUSDT", "SELL", 0.010, "MARKET",
                       reservation_id="r-exit", role="target",
                       reduce_only=True)


def _fill_rows(store, run_id):
    return store._db.execute(
        "SELECT execution_id FROM execution_events"
        f" WHERE run_id='{run_id}' AND kind='fill'").fetchall()


def _submitted_qty(transport) -> float:
    for method, path, params, _ in transport.requests:
        if method == "POST" and path == "/fapi/v1/order":
            return float(params["quantity"])
    raise AssertionError("no venue submit observed")


# ---------------------------------------------------------------------------
# R1: the threaded pump never mutates owner state.
# ---------------------------------------------------------------------------

def test_thread_pump_books_nothing_until_owner_drains(tmp_path):
    """Pumped fills sit in the handoff queue unapplied; every handler
    invocation runs on the owner thread; one drain books exactly once."""
    ready, orders = _ready(), _orders()
    engine, transport = venues.make_engine(tmp_path, [
        ("POST", "/fapi/v1/listenKey", None,
         ("ok", {"listenKey": "r1-key"})),
        ("GET", "/fapi/v2/account", None, ("ok", ready["account"])),
        ("GET", "/fapi/v1/openOrders", None, ("ok", [])),
        ("GET", "/fapi/v1/openAlgoOrders", None, ("ok", [])),
    ] + venues.ready_script(ready) + [
        ("POST", "/fapi/v1/order", {"type": "LIMIT"},
         ("ok", orders["orderAck"]))])
    session, store = _session(tmp_path, engine, "r1-pump")
    handler_threads = []
    original_sink = engine._event_handler

    def sink(event):
        handler_threads.append(threading.current_thread().name)
        return original_sink(event)

    engine.bind_sink(sink)
    socket = FakeSocket([])
    att = attach_user_stream(session, engine, lambda _: socket,
                             idle_sleep_s=0.005, poll_timeout_s=0.01,
                             start_thread=True)
    try:
        _until_healed(att)
        session._maybe_admit([Candidate("S1", _intent(session.now_utc()))])
        assert session._position is not None
        qty = _submitted_qty(transport)
        cid = session._position["entry_pre_id"]
        trade = copy.deepcopy(orders["userStreamTrade"])
        trade["o"]["c"] = cid
        trade["o"]["l"] = trade["o"]["z"] = f"{qty:.3f}"
        trade["o"]["L"] = trade["o"]["ap"] = "100.50"
        # Protection dialogue the owner drain will run synchronously
        # inside the stream handler (lookup + tape + algo pair).
        transport.append(
            ("GET", "/fapi/v1/order", {"origClientOrderId": cid},
             ("ok", {"orderId": 7, "status": "FILLED",
                     "executedQty": f"{qty:.3f}"})),
            ("GET", "/fapi/v1/userTrades", {"orderId": 7}, ("ok", [])),
            ("POST", "/fapi/v1/algoOrder", {"reduceOnly": "true"},
             ("ok", {"algoId": 11, "algoStatus": "WORKING"})),
            ("POST", "/fapi/v1/algoOrder", {"reduceOnly": "true"},
             ("ok", {"algoId": 12, "algoStatus": "WORKING"})))
        socket.script.append(trade)
        # The pump receives it (handoff fills) but books nothing.
        _until(lambda: att._queue.qsize() > 0)
        time.sleep(0.05)  # let a rogue pump act if it would.
        rows = store._db.execute(
            "SELECT count(*) FROM execution_events WHERE kind='fill'"
        ).fetchone()[0]
        assert rows == 0
        assert not session.ledger.has_position()
        assert handler_threads == []
        # The owner drain books exactly once, on the owner thread.
        assert att.drain_owner() == "event"
        rows = store._db.execute(
            "SELECT count(*) FROM execution_events WHERE kind='fill'"
        ).fetchone()[0]
        assert rows == 1
        assert set(handler_threads) == {"MainThread"}
        assert att.errors == 0
        assert att.fatal_error is None
    finally:
        att.close()
        store.close()


def test_apply_failure_parks_and_holds_until_acknowledged(tmp_path):
    """A poison envelope parks (bounded ring) and halts entries; the
    halt holds until the owner acknowledges; nothing is dropped."""
    ready = _ready()
    engine, _ = venues.make_engine(tmp_path, [
        ("POST", "/fapi/v1/listenKey", None, ("ok", {"listenKey": "K"})),
    ] + venues.ready_script(ready))
    session = SimpleNamespace(run_id="r1-park", store=None)
    socket = FakeSocket([])
    att = attach_user_stream(session, engine, lambda _: socket,
                             idle_sleep_s=0.005, poll_timeout_s=0.01,
                             start_thread=True)
    try:
        _until_healed(att)
        socket.script.append({"e": "BOGUS-EVENT"})
        _until(lambda: att._queue.qsize() > 0)
        att.drain_owner()
        assert att.halted
        assert "user-stream-apply" in att.halt_reasons()
        assert "user-stream" in engine.exit_only_reasons()
        assert att.acknowledge_failures() == 1
        assert "user-stream-apply" not in att.halt_reasons()
        assert not att.halted
        assert engine.exit_only_reasons() == ()
    finally:
        att.close()


def test_park_ring_is_bounded(tmp_path):
    ready = _ready()
    engine, _ = venues.make_engine(tmp_path, [
        ("POST", "/fapi/v1/listenKey", None, ("ok", {"listenKey": "K"})),
    ] + venues.ready_script(ready))
    session = SimpleNamespace(run_id="r1-ring", store=None)
    socket = FakeSocket([])
    att = attach_user_stream(session, engine, lambda _: socket,
                             idle_sleep_s=0.001, poll_timeout_s=0.005,
                             start_thread=True)
    try:
        _until_healed(att)
        for _ in range(150):
            socket.script.append({"e": "BOGUS-EVENT"})
        _until(lambda: att._queue.qsize() > 0)
        for _ in range(60):
            att.drain_owner()
            if att._queue.qsize() == 0 and not socket.script:
                att.drain_owner()
                break
            time.sleep(0.005)
        assert len(att._parked) == 100
        assert att.acknowledge_failures() == 100
    finally:
        att.close()


def test_queue_overflow_blocks_pump_without_dropping(tmp_path):
    """Backpressure, not loss: a full queue blocks the pump (the
    overflow latch proves it), and every envelope is delivered in
    order once the owner drains. A drain that observes residue
    with the latch set engages the overflow halt; a drained queue
    releases it."""
    ready = _ready()
    engine, _ = venues.make_engine(tmp_path, [
        ("POST", "/fapi/v1/listenKey", None, ("ok", {"listenKey": "K"})),
    ] + venues.ready_script(ready))
    session = SimpleNamespace(run_id="r1-overflow", store=None)
    socket = FakeSocket([])
    att = attach_user_stream(session, engine, lambda _: socket,
                             start_thread=True, queue_maxsize=4,
                             idle_sleep_s=0.001, poll_timeout_s=0.005)
    try:
        _until_healed(att)
        # Owner-side accounting: residue + latch engages the halt.
        att._queue.put_nowait(
            ("envelope", {"e": "ACCOUNT_UPDATE", "E": 0}, att._now()))
        att._overflow_latch = True
        att._owner_backlog(None)
        assert "user-stream-overflow" in att.halt_reasons()
        assert att.halted
        att.drain_owner()  # queue empties -> halt releases.
        assert "user-stream-overflow" not in att.halt_reasons()
        assert not att.halted
        # Pump-side backpressure: the pump blocks on a full queue
        # (latch set) instead of dropping.
        for i in range(10):
            socket.script.append({"e": "ACCOUNT_UPDATE", "E": i,
                                  "seq": i})
        _until(lambda: att._overflow_latch)
        assert att._queue.qsize() == 4
        seen = []
        original = engine.note_user_event

        def spy(payload):
            if payload.get("e") == "ACCOUNT_UPDATE" and "seq" in payload:
                seen.append(payload["seq"])
            return original(payload)

        engine.note_user_event = spy
        for _ in range(100):
            att.drain_owner()
            if len(seen) == 10:
                break
            time.sleep(0.005)
        assert seen == list(range(10))
        assert not att._overflow_latch
        assert "user-stream-overflow" not in att.halt_reasons()
        assert not att.halted
    finally:
        att.close()


def test_dead_pump_is_a_halt_reason_not_a_silent_stall(tmp_path):
    ready = _ready()
    engine, _ = venues.make_engine(tmp_path, [
        ("POST", "/fapi/v1/listenKey", None, ("ok", {"listenKey": "K"})),
    ] + venues.ready_script(ready))
    session = SimpleNamespace(run_id="r1-dead", store=None)

    def killer(key):
        raise ConnectionError("dial refused")

    att = attach_user_stream(session, engine, killer,
                             start_thread=True, idle_sleep_s=0.005,
                             poll_timeout_s=0.005,
                             initial_backoff_s=60.0, max_backoff_s=60.0)
    try:
        att.drain_owner()  # connect fails -> latched backoff.
        assert att.halted
        assert "user-stream-gap" in att.halt_reasons()
        assert att.fatal_error is None  # venue failure, not a crash.
        assert att.errors >= 1
    finally:
        att.close()


# ---------------------------------------------------------------------------
# R2: fills stay recoverable until the durable booking ack.
# ---------------------------------------------------------------------------

def _admitted(tmp_path, run_id, orders):
    """Engine + session with one submitted entry; returns
    (engine, transport, session, store, cid, qty)."""
    ready = _ready()
    engine, transport = venues.make_engine(tmp_path, [
        ("GET", "/fapi/v2/account", None, ("ok", ready["account"])),
        ("GET", "/fapi/v1/openOrders", None, ("ok", [])),
        ("GET", "/fapi/v1/openAlgoOrders", None, ("ok", [])),
    ] + venues.ready_script(ready) + [
        ("POST", "/fapi/v1/order", {"type": "LIMIT"},
         ("ok", orders["orderAck"]))])
    session, store = _session(tmp_path, engine, run_id)
    session._maybe_admit([Candidate("S1", _intent(session.now_utc()))])
    assert session._position is not None
    qty = _submitted_qty(transport)
    cid = session._position["entry_pre_id"]
    transport.append(
        ("GET", "/fapi/v1/order", {"origClientOrderId": cid},
         ("ok", {"orderId": 7, "status": "FILLED",
                 "executedQty": f"{qty:.3f}"})),
        ("GET", "/fapi/v1/userTrades", {"orderId": 7}, ("ok", [])),
        ("POST", "/fapi/v1/algoOrder", {"reduceOnly": "true"},
         ("ok", {"algoId": 11, "algoStatus": "WORKING"})),
        ("POST", "/fapi/v1/algoOrder", {"reduceOnly": "true"},
         ("ok", {"algoId": 12, "algoStatus": "WORKING"})))
    return engine, transport, session, store, cid, qty


def test_redelivered_fill_books_exactly_once(tmp_path):
    """First delivery books + acks; redelivery is dropped before the
    handler (never re-emitted); the ledger holds one credit."""
    orders = _orders()
    engine, _, session, store, cid, qty = _admitted(
        tmp_path, "r2-dedup", orders)
    calls, outcomes = [], []
    original_sink = engine._event_handler

    def sink(event):
        calls.append(event)
        outcome = original_sink(event)
        outcomes.append(outcome)
        return outcome

    engine.bind_sink(sink)
    try:
        trade = _trade(orders, cid, "BUY", "FILLED", qty, qty,
                       100.50, 0.0300, "t-dedup-1")
        engine.note_user_event(trade)
        assert outcomes == ["applied"]
        (exec_id,) = engine._acked_exec
        assert exec_id not in engine._unacked
        assert len(_fill_rows(store, "r2-dedup")) == 1
        # Venue redelivers the identical execution: the engine drops
        # it (durably booked) without invoking the handler.
        engine.note_user_event(copy.deepcopy(trade))
        assert len(calls) == 1
        assert len(_fill_rows(store, "r2-dedup")) == 1
        assert session.ledger.has_position()
    finally:
        store.close()


def test_unbooked_fill_stays_recoverable_until_recorded(tmp_path):
    """A fill for an unknown reservation is recorded but NOT
    booking-acked: it stays in the recoverable set, blocks booking,
    and redelivery re-emits (transport dedup never consumes an
    unbooked execution)."""
    ready = _ready()
    engine, _ = venues.make_engine(tmp_path, [])
    session, store = _session(tmp_path, engine, "r2-unbooked")
    calls, outcomes = [], []
    original_sink = engine._event_handler

    def sink(event):
        calls.append(event)
        outcome = original_sink(event)
        outcomes.append(outcome)
        return outcome

    engine.bind_sink(sink)
    try:
        trade = _trade(_orders(), "ghost-1", "BUY", "FILLED",
                       0.060, 0.060, 100.50, 0.0300, "t-ghost-1")
        engine.note_user_event(trade)
        assert outcomes == ["unbooked"]
        (exec_id,) = engine._unacked
        assert exec_id not in engine._acked_exec
        assert engine._unacked[exec_id] == "ghost-1"
        assert len(_fill_rows(store, "r2-unbooked")) == 1  # recorded.
        assert not session.ledger.has_position()  # not credited.
        assert session._booking_blocked == "unknown-fill:ghost-1"
        # Redelivery re-emits (handler invoked again); the store
        # exec-gate turns it into a duplicate (no double row), and
        # only then — with durability proven — is it acked.
        engine.note_user_event(copy.deepcopy(trade))
        assert len(calls) == 2
        assert outcomes == ["unbooked", "duplicate"]
        assert len(_fill_rows(store, "r2-unbooked")) == 1
        assert exec_id in engine._acked_exec
        assert exec_id not in engine._unacked
    finally:
        store.close()


def test_fill_gap_tracked_once_and_closed_on_catchup(tmp_path):
    """executedQty above the adopted tape records a gap (journaled
    once per transition, never per lookup); tape catch-up closes it."""
    ready, orders = _ready(), _orders()
    engine, transport = venues.make_engine(tmp_path,
                                           venues.ready_script(ready) + [
        ("POST", "/fapi/v1/order", {"type": "MARKET"},
         ("ok", orders["orderAck"]))])
    journal = tmp_path / "live.jsonl"
    engine.bind_sink(lambda event: None)  # consuming: adoptions ack.

    def gap_events():
        return [json.loads(line) for line in
                journal.read_text().splitlines()
                if json.loads(line).get("event") in (
                    "fill-gap", "fill-gap-closed")]
    cid = engine.submit(_entry())
    assert engine._recovery_watch() == set()
    transport.append(
        ("GET", "/fapi/v1/order", {"origClientOrderId": cid},
         ("ok", {"orderId": 7, "status": "FILLED",
                 "executedQty": "0.060", "origQty": "0.060"})),
        ("GET", "/fapi/v1/userTrades", {"orderId": 7}, ("ok", [])))
    engine.lookup(cid)
    assert engine._recovery_watch() == {cid}
    assert engine._gap_orders == {cid}  # watched via gap, not unacked.
    assert engine._unacked == {}
    assert [e["event"] for e in gap_events()] == ["fill-gap"]
    # A second identical lookup does not re-journal the gap.
    transport.append(
        ("GET", "/fapi/v1/order", {"origClientOrderId": cid},
         ("ok", {"orderId": 7, "status": "FILLED",
                 "executedQty": "0.060", "origQty": "0.060"})),
        ("GET", "/fapi/v1/userTrades", {"orderId": 7}, ("ok", [])))
    engine.lookup(cid)
    assert [e["event"] for e in gap_events()] == ["fill-gap"]
    # The tape catches up: gap closes, exactly once.
    transport.append(
        ("GET", "/fapi/v1/order", {"origClientOrderId": cid},
         ("ok", {"orderId": 7, "status": "FILLED",
                 "executedQty": "0.060", "origQty": "0.060"})),
        ("GET", "/fapi/v1/userTrades", {"orderId": 7},
         ("ok", [{"id": "t-gap-1", "qty": "0.060", "price": "100.50",
                "commission": "0.03",
                "commissionAsset": "USDT"}])))
    engine.lookup(cid)
    assert engine._recovery_watch() == set()
    assert [e["event"] for e in gap_events()] == ["fill-gap",
                                                  "fill-gap-closed"]
    transport.assert_empty()


def test_crash_rebuild_restores_unacked_and_revisits_terminal(tmp_path):
    """Crash boundary: a journal-rebuilt engine restores the unacked
    set (adopted but never booking-acked); the terminal order stays
    on the recovery watch; reconnect re-emits without double-adopting
    the tape."""
    ready, orders = _ready(), _orders()
    journal_path = tmp_path / "live.jsonl"
    engine, transport = venues.make_engine(tmp_path,
                                           venues.ready_script(ready) + [
        ("POST", "/fapi/v1/order", {"type": "MARKET"},
         ("ok", orders["orderAck"]))])
    outcomes1 = []
    engine.bind_sink(lambda event: outcomes1.append("unbooked") or
                     "unbooked")
    cid = engine.submit(_entry())
    trade = _trade(orders, cid, "BUY", "FILLED", 0.010, 0.010,
                   100.50, 0.0050, "t-crash-1")
    engine.note_user_event(trade)
    (exec_id,) = engine._unacked
    assert outcomes1 == ["unbooked"]
    # Crash + rebuild on the same journal: the unacked execution
    # survives; the terminal order is watched.
    rebuilt = BinanceLiveEngine(
        api_key="TESTKEY", api_secret="TESTSECRET",
        journal_path=journal_path, expected_leverage=3,
        run_tag="bl", live_enable=True,
        transport=venues.ReplayTransport([
            ("GET", "/fapi/v1/order", {"origClientOrderId": cid},
             ("ok", {"orderId": 7, "status": "FILLED",
                     "executedQty": "0.010", "origQty": "0.010"})),
            ("GET", "/fapi/v1/userTrades", {"orderId": 7},
             ("ok", [{"id": "t-crash-1", "qty": "0.010",
                    "price": "100.50", "commission": "0.005",
                    "commissionAsset": "USDT"}]))]),
        now_utc=lambda: venues.NOW)
    assert rebuilt._unacked == {exec_id: cid}
    assert exec_id in rebuilt._adopted_exec
    assert rebuilt._adopted_qty[cid] == pytest.approx(0.010)
    assert rebuilt._recovery_watch() == {cid}
    got = []
    rebuilt.bind_sink(got.append)  # None outcome = consumed + acked.
    rebuilt.stream_reconnected()  # revisits the terminal order.
    fills = [e for e in got if e.kind == "fill"]
    assert [f.payload.execution_id for f in fills] == [exec_id]
    assert rebuilt._adopted_qty[cid] == pytest.approx(0.010)
    assert exec_id in rebuilt._acked_exec
    assert rebuilt._recovery_watch() == set()


# ---------------------------------------------------------------------------
# R3: halt independence — a heal clears only its own reason.
# ---------------------------------------------------------------------------

def test_stream_heal_preserves_session_halt(tmp_path):
    """Session halt + stream halt coexist; the stream heal releases
    only the stream reason; the Session halt still refuses entries
    while exits work; releasing the Session reason lifts fully."""
    ready, orders = _ready(), _orders()
    engine, transport = venues.make_engine(tmp_path, [
        ("POST", "/fapi/v1/listenKey", None,
         ("ok", {"listenKey": "r3-key"})),
    ] + venues.ready_script(ready) + [
        ("POST", "/fapi/v1/order", {"type": "MARKET"},
         ("ok", orders["orderAck"])),
        ("POST", "/fapi/v1/order", {"type": "MARKET"},
         ("ok", orders["orderAck"])),
    ])
    session, store = _session(tmp_path, engine, "r3-halt")
    session._halt_entries("risk:halt")
    assert engine.exit_only_reasons() == ("risk:halt",)
    socket = FakeSocket([])
    att = attach_user_stream(session, engine, lambda _: socket,
                             idle_sleep_s=0.005, poll_timeout_s=0.01,
                             start_thread=True)
    try:
        _until_healed(att)
        # The stream heal cleared only its own reason.
        assert engine.exit_only_reasons() == ("risk:halt",)
        assert session._exit_only_reasons == {"risk:halt"}
        with pytest.raises(ValueError, match="exit-only"):
            engine.submit(_entry())
        engine.submit(_exit())  # exits work under a Session halt.
        session._release_exit_only("risk:halt")
        assert engine.exit_only_reasons() == ()
        engine.submit(_entry())  # entries flow once fully lifted.
        transport.assert_empty()
    finally:
        att.close()
        store.close()


def test_adapter_reasons_release_independently(tmp_path):
    """Live reason set: each release clears only its own reason; the
    halt holds until the last reason lifts. (Paper intentionally
    keeps bool semantics — a sim switch, not a coordinated halt —
    pinned by test_adapters_paper_engine.py.)"""
    ready, orders = _ready(), _orders()
    engine, transport = venues.make_engine(
        tmp_path, venues.ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("ok", orders["orderAck"]))])
    engine.set_exit_only(True, "a-risk")
    engine.set_exit_only(True, "b-stream")
    assert engine.exit_only_reasons() == ("a-risk", "b-stream")
    with pytest.raises(ValueError, match="exit-only"):
        engine.submit(_entry())
    engine.set_exit_only(False, "b-stream")
    assert engine.exit_only_reasons() == ("a-risk",)
    with pytest.raises(ValueError, match="exit-only"):
        engine.submit(_entry())
    engine.set_exit_only(False, "a-risk")
    assert engine.exit_only_reasons() == ()
    engine.submit(_entry())
    transport.assert_empty()
    paper = NautilusPaperEngine(journal_path=tmp_path / "paper.jsonl")
    paper.set_exit_only(True, "halt:test")
    paper.set_exit_only(False, "cleared")
    assert paper._exit_only is False  # bool lift, any label.
