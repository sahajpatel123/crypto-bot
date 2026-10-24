"""User-stream live-run wiring tests (Worker 2, Checkpoint-B).

Offline: injected socket + ReplayTransport. Fills flow through the
attachment, gaps halt entries (exits work) via the engine's existing
exit-only flag, reconnect heals and resumes.
"""
import copy
import json
import sys
import time
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import venue_fixtures as venues
from cryptobot.adapters.user_stream import attach_user_stream
from cryptobot.app.engine import EngineOrder

FIX = venues.FIX


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


def _ready():
    return json.loads((FIX / "readiness.json").read_text())


def _orders():
    return json.loads((FIX / "orders.json").read_text())


def _session(store=True):
    seen = []

    class Store:
        def checkpoint(self, run_id, kind, payload):
            seen.append((run_id, kind, payload))

    ns = SimpleNamespace(run_id="stream-t", store=Store() if store else None)
    return ns, seen


def _attach(tmp_path, session, sockets, clock, script, **kw):
    made = []

    def factory(key):
        made.append(key)
        if isinstance(sockets, list):
            return sockets[min(len(made) - 1, len(sockets) - 1)]
        return sockets(key, len(made))

    engine, transport = venues.make_engine(tmp_path, script)
    kw.setdefault("start_thread", False)
    att = attach_user_stream(session, engine, factory, now=clock,
                             sleep=lambda s: clock.advance(s), **kw)
    return att, engine, transport, made


def _entry():
    return EngineOrder("BTCUSDT", "BUY", 0.010, "MARKET",
                       reservation_id="r-entry")


def _exit():
    return EngineOrder("BTCUSDT", "SELL", 0.010, "MARKET",
                       reservation_id="r-exit", role="target",
                       reduce_only=True)


def test_attach_halts_entries_until_first_heal(tmp_path):
    ready, orders = _ready(), _orders()
    session, _ = _session()
    clock = Clock()
    att, engine, transport, _ = _attach(
        tmp_path, session, [FakeSocket([])], clock,
        [("POST", "/fapi/v1/listenKey", None,
          ("ok", {"listenKey": "K1"}))] + venues.ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("ok", orders["orderAck"])),
        ])
    try:
        assert att.halted
        with pytest.raises(ValueError, match="exit-only"):
            engine.submit(_entry())
        assert att.poll_once() == "healed"
        assert not att.halted
        engine.submit(_entry())  # entries flow after the first heal.
        transport.assert_empty()
    finally:
        att.close()


def test_healed_stream_flows_fills(tmp_path):
    ready, orders = _ready(), _orders()
    session, _ = _session()
    clock = Clock()
    stream = copy.deepcopy(orders["userStreamTrade"])
    sock = FakeSocket([])
    att, engine, transport, _ = _attach(
        tmp_path, session, [sock], clock,
        [("POST", "/fapi/v1/listenKey", None,
          ("ok", {"listenKey": "K1"}))] + venues.ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("ok", orders["orderAck"])),
        ])
    try:
        assert att.poll_once() == "healed"
        cid = engine.submit(_entry())
        (method, path, params, _), = [
            r for r in transport.requests
            if r[0] == "POST" and r[1] == "/fapi/v1/order"]
        stream["o"]["c"] = cid
        qty = params["quantity"]
        stream["o"]["l"] = stream["o"]["z"] = qty
        sock.script.append(stream)
        got = []
        engine.bind_sink(got.append)
        assert att.poll_once() == "event"
        (fill,) = [e for e in got if e.kind == "fill"]
        assert fill.payload.client_order_id == cid
        assert fill.payload.execution_id.startswith("binanceusdm/")
        assert not att.halted
    finally:
        att.close()


def test_gap_halts_entries_while_exits_work(tmp_path):
    ready, orders = _ready(), _orders()
    session, seen = _session()
    clock = Clock()
    live = {"up": True}
    made_socks = []

    def factory(key, n):
        if not live["up"]:
            raise ConnectionError("dial refused")
        sock = FakeSocket([])
        made_socks.append(sock)
        return sock

    att, engine, transport, _ = _attach(
        tmp_path, session, factory, clock,
        [("POST", "/fapi/v1/listenKey", None,
          ("ok", {"listenKey": "K1"}))] + venues.ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("ok", orders["orderAck"])),
        ])
    try:
        assert att.poll_once() == "healed"  # connect + first heal.
        live["up"] = False
        made_socks[-1].script.append("die")
        assert att.poll_once() == "backoff"  # socket died, redial fails.
        assert att.halted
        with pytest.raises(ValueError, match="exit-only"):
            engine.submit(_entry())
        engine.submit(_exit())  # exits still reach the venue.
        assert [k for _, k, _ in seen].count("user-stream-gap") >= 1
        # The heal reconciles the gap-submitted exit via lookup.
        transport.append(
            ("GET", "/fapi/v1/order", None,
             ("ok", {"orderId": 12345, "status": "FILLED",
                     "executedQty": "0.010", "origQty": "0.010"})),
            ("GET", "/fapi/v1/userTrades", None,
             ("ok", [{"id": 888001, "qty": "0.010", "price": "100.50",
                      "commission": "0.03",
                      "commissionAsset": "USDT"}])))
        live["up"] = True
        clock.advance(61.0)  # outlast the reconnect backoff.
        assert att.poll_once() == "healed"
        assert not att.halted
        # R3 rationale: healed checkpoints now carry the canonical
        # released reason plus the phase detail (same evidence, more
        # precise: which reason cleared and at which step).
        assert ("stream-t", "user-stream-healed",
                {"reason": "user-stream-gap",
                 "phase": "healed"}) in seen
        transport.assert_empty()
    finally:
        att.close()


def test_reconnect_heal_adopts_before_resuming(tmp_path):
    orders = _orders()
    session, _ = _session()
    clock = Clock()
    # A journaled non-terminal order from before the gap.
    (tmp_path / "live.jsonl").write_text(json.dumps({
        "ts_utc": venues.NOW.isoformat(), "event": "submit-intent",
        "client_id": "bl-old-9", "symbol": "BTCUSDT", "side": "BUY",
        "qty": 0.010, "reservation_id": "r-old"}) + "\n")
    stream = copy.deepcopy(orders["userStreamTrade"])
    stream["o"]["c"] = "bl-old-9"
    stream["o"]["l"] = stream["o"]["z"] = "0.010"
    att, engine, transport, _ = _attach(
        tmp_path, session, [FakeSocket([]), FakeSocket([stream])], clock,
        [("POST", "/fapi/v1/listenKey", None,
          ("ok", {"listenKey": "K1"})),
         ("GET", "/fapi/v1/order", None,
          ("ok", orders["orderQueryFilled"])),
         ("GET", "/fapi/v1/userTrades", None,
          ("ok", orders["userTrades"]))])
    try:
        got = []
        engine.bind_sink(got.append)
        assert att.poll_once() == "healed"  # heal adopts via lookup.
        adopted = [e for e in got if e.kind == "fill"]
        assert len(adopted) == 2  # one per venue trade in the tape.
        assert {e.payload.client_order_id for e in adopted} == {"bl-old-9"}
        assert len({e.payload.execution_id for e in adopted}) == 2
        assert not att.halted
        transport.assert_empty()
    finally:
        att.close()


def test_attach_rejects_engine_without_stream(tmp_path):
    from cryptobot.adapters.paper_engine import NautilusPaperEngine
    session, _ = _session()
    paper = NautilusPaperEngine(taker_bps=5.0)
    with pytest.raises(TypeError, match="live engine"):
        attach_user_stream(session, paper, lambda key: FakeSocket([]),
                           start_thread=False)


def test_close_stops_pump_thread(tmp_path):
    ready = _ready()
    session, _ = _session(store=False)
    att, engine, transport, _ = _attach(
        tmp_path, session, [FakeSocket([])], Clock(),
        [("POST", "/fapi/v1/listenKey", None,
          ("ok", {"listenKey": "K1"}))] + venues.ready_script(ready) + [
        ],
        start_thread=True, poll_timeout_s=0.01, idle_sleep_s=0.01)
    deadline = time.monotonic() + 5.0
    while att.halted and time.monotonic() < deadline:
        # R1 rationale: the pump owns the socket ONLY and can never
        # heal alone (healing touches the engine); the owner thread
        # must drain. The old "pump heals by itself" encoded the
        # cross-thread defect this release closes.
        att.drain_owner()
        time.sleep(0.01)
    assert not att.halted  # healed via owner drain.
    thread = att._thread
    assert thread is not None and thread.is_alive()
    att.close()
    assert not thread.is_alive()
    with pytest.raises(RuntimeError, match="closed"):
        att.poll_once()
