"""D2 lifecycle matrix: 13 rows on the real loop (DEEP-W1-D2).

Every threaded proof runs the NORMAL Session.run_live loop (default
threading: BoundedProducer feed pump + user-stream pump thread, owner
drain on the control thread) with the pinned knobs control_tick_s=0.25
and feed_queue_max=1000, a real RunStore(tmp_path), and a live demo
engine on a scripted offline transport. The ONLY scripted signal is
strategy intent (a stub adapter — admission, sizing, submit, booking,
protection, supervision, and flatten are all real).

Transport discipline: background polls (time/account/openOrders/
openAlgoOrders — timing-dependent counts) are canned per-test
fixtures; every order-flow call (submit/lookup/cancel/algo/legs) is
strictly scripted in order, so submit counts, duplicate submits, and
cancel coverage are exact. Set MATRIX_TRANSCRIBE=1 to print the
strict entries a row actually needs (development aid).
"""
import copy
import itertools
import json
import os
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import venue_fixtures as venues
from cryptobot.adapters.binance_live import (
    BinanceLiveEngine, UnknownOutcomeError, VenueHttpError,
    VenueRejectedError)
from cryptobot.adapters.user_stream import attach_user_stream
from cryptobot.app.config import load_config
from cryptobot.app.session import Session, WallClock
from cryptobot.app.store import RunStore
from cryptobot.coordination.exits import ExitPolicy, encode_exit_rule
from cryptobot.coordination.intent import (
    DataQuality, ForecastCost, Intent, Side)
from cryptobot.strategies.runtime import StrategyOutcome

CLASS = "matrix-test"
SYM = "BTCUSDT"
MARK = 100.0
RUN_TAG = "matrix"
ROOT = Path(__file__).resolve().parent.parent.parent

# Venue trade ids are globally unique: a per-rig counter restarting at
# 777001 collides across crash phases, and the cross-phase twin books
# as a duplicate-skip (a close fill silently dropped!). One process
# counter for all rigs. No assertion depends on the values.
_TRADE_IDS = itertools.count(777001)

# Timing-dependent background polls: canned fixtures, counted.
POLL_CALLS = {("GET", "/fapi/v1/time"),
              ("GET", "/fapi/v2/account"),
              ("GET", "/fapi/v1/openOrders"),
              ("GET", "/fapi/v1/openAlgoOrders")}


class ThreadSocket:
    """Thread-safe scripted socket: pump recvs, test thread pushes."""

    def __init__(self):
        self.q = deque()
        self.lock = threading.Lock()
        self.closed = False
        self.die = False

    def recv(self, timeout_s):
        if self.die:
            raise ConnectionError("socket died")
        with self.lock:
            if self.q:
                return self.q.popleft()
        return None

    def push(self, env):
        with self.lock:
            self.q.append(env)

    def close(self):
        self.closed = True


def trade_envelope(orders, cid, side, qty, trade_id, price=MARK,
                   fee="0.03000000"):
    tr = copy.deepcopy(orders["userStreamTrade"])
    tr["o"]["t"] = trade_id
    tr["o"]["c"] = cid
    tr["o"]["S"] = side
    tr["o"]["l"] = tr["o"]["z"] = str(qty)
    tr["o"]["L"] = tr["o"]["ap"] = f"{price:.2f}"
    tr["o"]["n"] = fee
    return tr


class MatrixTransport:
    """Strict order-flow script + canned poll fixtures + POST hook.

    Strict entries are (method, path, params-subset-or-None, response).
    Poll calls return canned fixtures (counts recorded). POSTs invoke
    hook(kind, params) after the ack (kind: order/algo/none).
    """

    def __init__(self, script, *, account, orders, hook=None, tail=None):
        self._strict = list(script)
        # Tolerant tail: after the strict prefix is consumed, calls in
        # `tail` are allowed in any order/count (recorded, echo
        # responses). Used for supervision churn that races fill
        # booking. CHURN_TAIL forbids order submits outright;
        # SUBMIT_TAIL allows them but every such test asserts the
        # exact ordered submit subsequence (duplicates fail there).
        self._tail = set(tail or ())
        self._replay = venues.ReplayTransport(script)
        self._account = account
        self._orders = orders
        self._hook = hook
        self.poll_counts = {}
        self.flow = []  # strict (method, path) in order, for debugging.
        # Venue-truth tape: cid -> [{trade_id, qty, price, fee, side}].
        # Stream pushes and REST lookups describe the SAME tape, so
        # exec-id dedup behaves exactly like the real venue (the same
        # trade seen twice books once; invented fixture trades would
        # double-count exposure and trip risk stops).
        self._tape = {}
        self._last_query_cid = None

    def note_stream_fill(self, cid, trade_id, qty, price, fee, side):
        self._tape.setdefault(cid, []).append({
            "trade_id": trade_id, "qty": float(qty), "price": price,
            "fee": fee, "side": side})
        self._last_tape_cid = cid

    def _tape_qty(self, cid):
        return sum(t["qty"] for t in self._tape.get(cid, []))

    def _echo_order(self, cid):
        o = self._orders
        q = copy.deepcopy(o["orderQueryFilled"])
        q["origClientOrderId"] = cid
        filled = self._tape_qty(cid)
        q["executedQty"] = f"{filled:.3f}" if filled else "0"
        q["status"] = "FILLED" if filled > 0 else "NEW"
        return q

    def _echo_tape(self, cid):
        return [{
            "id": t["trade_id"], "orderId": 12345, "symbol": SYM,
            "qty": f"{t['qty']:.3f}", "price": f"{t['price']:.2f}",
            "commission": t["fee"], "commissionAsset": "USDT",
            "buyer": t["side"] == "BUY",
        } for t in self._tape.get(cid, [])]

    def _tail_response(self, method, path, params):
        o = self._orders
        if path == "/fapi/v1/order" and method == "POST":
            ack = copy.deepcopy(o["orderAck"])
            ack["clientOrderId"] = params.get("newClientOrderId")
            ack["origQty"] = params.get("quantity")
            return ack
        if path == "/fapi/v1/order" and method == "GET":
            cid = params.get("origClientOrderId")
            self._last_query_cid = cid
            return self._echo_order(cid)
        if path == "/fapi/v1/algoOrder" and method == "GET":
            q = copy.deepcopy(o["algoQueryWorking"])
            q["clientAlgoId"] = params.get("origClientAlgoId",
                                           q["clientAlgoId"])
            return q
        if path == "/fapi/v1/userTrades":
            return self._echo_tape(self._last_query_cid)
        if path == "/fapi/v1/algoOrder" and method == "POST":
            ack = copy.deepcopy(o["algoAck"])
            ack["clientAlgoId"] = params.get("clientAlgoId")
            return ack
        if path == "/fapi/v1/algoOrder" and method == "DELETE":
            return copy.deepcopy(algo_deleted())
        if path == "/fapi/v1/listenKey" and method == "DELETE":
            return {}
        raise AssertionError(("tail-unsupported", method, path))

    @property
    def requests(self):
        return self._replay.requests

    def request(self, method, path, params, headers):
        if (method, path) in POLL_CALLS:
            key = (method, path)
            self.poll_counts[key] = self.poll_counts.get(key, 0) + 1
            return self._canned(method, path)
        # READS blocks (recover/churn zones with racy call counts):
        # serve echo reads while the call matches the block's path
        # set; a non-matching call ends the block (lookahead pop)
        # and dispatches normally past it.
        while self._strict and self._strict[0][0] == "READS" \
                and (method, path) not in self._strict[0][1]:
            self._strict.pop(0)
        if os.environ.get("MATRIX_TRANSCRIBE") == "1" and not self._strict:
            print(f"STRICT {method} {path} "
                  f"{json.dumps(params, sort_keys=True)[:200]}", flush=True)
            resp = self._canned_open(method, path, params)
        elif not self._strict:
            if (method, path) in self._tail:
                self.flow.append((method, path))
                resp = self._tail_response(method, path, params)
                self._replay.requests.append(
                    (method, path, dict(params or {}), True))
                if self._hook is not None and method == "POST":
                    kind = ("order" if path == "/fapi/v1/order"
                            else "algo")
                    self._hook(kind, dict(params))
                return resp
            if (method, path) == ("DELETE", "/fapi/v1/listenKey"):
                # Crash-phase teardown tolerance: a crash lands
                # mid-churn with leftovers, so teardown cannot be
                # scripted; full runs script close_key() strictly.
                self._replay.requests.append(
                    (method, path, dict(params or {}), True))
                return {}
            raise AssertionError(
                f"strict script empty at {method} {path} {params}")
        else:
            if self._strict[0][0] == "READS":
                # Echo read inside a READS block (no pop: 0+).
                self.flow.append((method, path))
                resp = self._replay_one(
                    (method, path, None, ("echo", None)),
                    method, path, params, headers)
            else:
                entry = self._strict.pop(0)
                self.flow.append((method, path))
                if os.environ.get("MATRIX_DEBUG") == "1":
                    print(f"CALL {method} {path}", flush=True)
                resp = self._replay_one(entry, method, path, params,
                                        headers)
        if self._hook is not None and method == "POST":
            kind = ("order" if path == "/fapi/v1/order"
                    else "algo" if path == "/fapi/v1/algoOrder"
                    else "none")
            if kind != "none":
                self._hook(kind, dict(params))
        return resp

    def _replay_one(self, entry, method, path, params, headers):
        want_method, want_path, want_params, resp = entry
        assert (method, path) == (want_method, want_path), (
            f"want {want_method} {want_path}, got {method} {path}")
        if want_params:
            for k, v in want_params.items():
                assert params.get(k) == v, (
                    f"{method} {path}: param {k}={params.get(k)!r} "
                    f"!= {v!r}")
        status, payload = resp
        if status == "timeout":
            # Ambiguous submit: venue may or may not have it. Optional
            # payload {"fill": {"qty", "price"}} seeds the tape (the
            # venue filled it; the stream just hasn't delivered), so
            # the resolving lookup adopts instead of voiding.
            fill = (payload or {}).get("fill")
            if fill and path == "/fapi/v1/order":
                self.note_stream_fill(
                    params.get("newClientOrderId"), next(_TRADE_IDS),
                    fill.get("qty", params.get("quantity")),
                    fill.get("price", MARK),
                    "0.03000000", params.get("side", "BUY"))
            raise VenueHttpError(503, None, "probe: gateway timeout")
        if status == "reject404":
            # Venue-never-saw (order voided): lookups return None.
            raise VenueRejectedError(404, -2013, "probe: unknown order")
        if status == "echo":
            # Venue-truth echo: lookups describe the pushed tape.
            assert method == "GET", (method, path)
            if path == "/fapi/v1/order":
                cid = params.get("origClientOrderId")
                self._last_query_cid = cid
                out = self._echo_order(cid)
            elif path == "/fapi/v1/algoOrder":
                out = copy.deepcopy(self._orders["algoQueryWorking"])
                out["clientAlgoId"] = params.get(
                    "origClientAlgoId", out["clientAlgoId"])
            elif path == "/fapi/v1/userTrades":
                out = self._echo_tape(self._last_query_cid)
            else:
                raise AssertionError(("echo-unsupported", method, path))
            self._replay.requests.append(
                (method, path, dict(params or {}), True))
            return out
        assert status == "ok", (method, path, resp)
        out = copy.deepcopy(payload)
        if method == "POST" and path == "/fapi/v1/order":
            out["clientOrderId"] = params.get("newClientOrderId")
            out["origQty"] = params.get("quantity")
        if method == "POST" and path == "/fapi/v1/algoOrder":
            out["clientAlgoId"] = params.get("clientAlgoId")
        if method == "GET" and path == "/fapi/v1/order":
            out["origClientOrderId"] = params.get(
                "origClientOrderId", out.get("origClientOrderId"))
        self._replay.requests.append((method, path, dict(params or {}),
                                      True))
        return out

    def _canned(self, method, path):
        if path == "/fapi/v1/time":
            return {"serverTime": int(time.time() * 1000)}
        if path == "/fapi/v2/account":
            return copy.deepcopy(self._account)
        return []

    def _canned_open(self, method, path, params):
        o = self._orders
        if path == "/fapi/v1/exchangeInfo":
            return copy.deepcopy(
                venues.ready_fixture()["exchangeInfo"])
        if path == "/fapi/v1/commissionRate":
            return copy.deepcopy(
                venues.ready_fixture()["commissionRate"])
        if path == "/fapi/v1/leverage":
            return copy.deepcopy(venues.ready_fixture()["leverage"])
        if path == "/fapi/v1/listenKey" and method == "POST":
            return {"listenKey": "K1"}
        if path == "/fapi/v1/order" and method == "POST":
            ack = copy.deepcopy(o["orderAck"])
            ack["clientOrderId"] = params.get("newClientOrderId")
            ack["origQty"] = params.get("quantity")
            return ack
        if path == "/fapi/v1/order" and method == "GET":
            cid = params.get("origClientOrderId")
            self._last_query_cid = cid
            return self._echo_order(cid)
        if path == "/fapi/v1/algoOrder" and method == "POST":
            ack = copy.deepcopy(o["algoAck"])
            ack["clientAlgoId"] = params.get("clientAlgoId")
            return ack
        if path == "/fapi/v1/algoOrder" and method == "DELETE":
            return {"code": 200, "msg": "success"}
        if path == "/fapi/v1/userTrades":
            return self._echo_tape(self._last_query_cid)
        if path == "/fapi/v1/algoOrder" and method == "GET":
            q = copy.deepcopy(o["algoQueryWorking"])
            q["clientAlgoId"] = params.get("origClientAlgoId",
                                           q["clientAlgoId"])
            return q
        if path == "/fapi/v1/listenKey" and method == "DELETE":
            return {}
        raise AssertionError(("TRANSCRIBE-OPEN", method, path))

    def assert_empty(self):
        assert not self._strict, f"unconsumed strict: {self._strict}"

    def discard(self):
        """Drop leftovers (crash cut the flow short by design)."""
        self._strict.clear()


def market_trade(seq, ts_ms, agg_id, price=MARK):
    return {"v": 1, "format": "cryptobot-events/1",
            "input_class": CLASS, "source": "synthetic", "route": "test",
            "run_id": "matrix", "seq": seq, "channel": "aggTrade",
            "symbol": SYM, "exchange_ts_ms": ts_ms,
            "local_recv_ms": ts_ms + 5, "local_mono_ns": seq,
            "gap_kind": None, "venue_seq": agg_id,
            "payload": {"agg_id": agg_id, "price": price, "qty": 1.0,
                        "first_id": agg_id, "last_id": agg_id,
                        "trade_ts_ms": ts_ms, "buyer_is_maker": False}}


def market_bbo(seq, ts_ms, bid=MARK - 0.01, ask=MARK + 0.01):
    return {"v": 1, "format": "cryptobot-events/1",
            "input_class": CLASS, "source": "synthetic", "route": "test",
            "run_id": "matrix", "seq": seq, "channel": "bookTicker",
            "symbol": SYM, "exchange_ts_ms": ts_ms,
            "local_recv_ms": ts_ms + 5, "local_mono_ns": seq,
            "gap_kind": None, "venue_seq": 0,
            "payload": {"bid": bid, "ask": ask}}


def drill_like_intent(session, mark=MARK, time_exit_s=600):
    now = session.now_utc()
    return Intent(
        strategy="drill", version="0.1.0", instrument=SYM,
        side=Side.LONG, evidence_ts_utc=now,
        entry_low=round(mark * 0.999, 2),
        entry_high=round(mark * 1.001, 2),
        entry_expiry_utc=now + timedelta(seconds=120),
        invalidation_price=round(mark * 0.98, 4),
        exit_rule=encode_exit_rule(ExitPolicy(
            stop_price=round(mark * 0.98, 4),
            target_price=round(mark * 1.05, 2),
            time_exit_utc=now + timedelta(seconds=time_exit_s),
            policy_id="matrix")),
        holding_limit_s=600,
        forecast_cost=ForecastCost(5.0, 5.0, 5.0, 1.0),
        evidence_ref="matrix:1", data_quality=DataQuality.CLEAN)


class ScriptedSignal:
    """Stub strategy adapter: fires `shots` intents, then rejects."""

    def __init__(self, session, shots=1, time_exit_s=600):
        self.strategy_id = "drill"
        self._session = session
        self._shots = shots
        self._time_exit_s = time_exit_s
        self.fired = 0

    def evaluate(self, view):
        if self.fired >= self._shots:
            return StrategyOutcome(intent=None,
                                   reject_reason="script:done")
        self.fired += 1
        return StrategyOutcome(intent=drill_like_intent(
            self._session, time_exit_s=self._time_exit_s))


class GatedSignal(ScriptedSignal):
    """Shots released by threading.Events (test-orchestrated timing).

    Each gate fires AT MOST once (a loop-rejected probe still
    consumes its gate, but never a later one).
    """

    def __init__(self, session, gates, time_exit_s=600):
        super().__init__(session, len(gates), time_exit_s)
        self._gates = gates
        self._done = set()

    def evaluate(self, view):
        for i, gate in enumerate(self._gates):
            if i not in self._done and gate.is_set():
                self._done.add(i)
                self.fired = len(self._done)
                return StrategyOutcome(intent=drill_like_intent(
                    self._session, time_exit_s=self._time_exit_s))
        return StrategyOutcome(intent=None, reject_reason="script:wait")


def wait_until(pred, timeout_s=10.0, label="condition"):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {label}")


class Rig:
    """One matrix run: config/engine/session/stream/scripts."""

    def __init__(self, tmp_path, monkeypatch, ready, orders, account,
                 script, *, shots=1, run_id="matrix-1", hook=None,
                 journal_extra=None, time_exit_s=600, tail=None,
                 cooldown_s=None, max_mark_age_ms=None):
        text = (ROOT / "configs" / "demo.toml").read_text()
        text = text.replace('dir = "runs"',
                            f'dir = "{tmp_path / "runs"}"', 1)
        text = text.replace("warmup_bars = 130", "warmup_bars = 3", 1)
        if cooldown_s is not None:
            # Timing compression for multi-position rows: the selector
            # cooldown is orthogonal to the mechanics under test.
            text = text.replace("cooldown_s = 300",
                                f"cooldown_s = {cooldown_s}", 1)
        if max_mark_age_ms is not None:
            # Rig-backlog compensation: the 12-event warmup burst
            # occupies 12 ticks, so queued trickle events arrive
            # 2-3s stale and trip the 1s mark bound ~t=3 every run
            # (the latch never releases, so any second admit would
            # fail — filed, not fixed: latch semantics are a safety
            # decision). Multi-admit rows widen the bound; the
            # mechanics under test never stall marks anywhere near
            # it, so the check stays live, just not tripped by the
            # rig's own warmup.
            text = text.replace("max_mark_age_ms = 1000",
                                f"max_mark_age_ms = {max_mark_age_ms}", 1)
        cfg_path = tmp_path / "matrix.toml"
        cfg_path.write_text(text)
        self.cfg = load_config(cfg_path)
        assert self.cfg.control_tick_s == 0.25
        assert self.cfg.feed_queue_max == 1000
        self.tmp = tmp_path
        self.run_id = run_id
        self.workdir = tmp_path / "runs" / run_id
        self.orders = orders
        self.transport = MatrixTransport(
            script, account=account, orders=orders, hook=hook, tail=tail)
        self.engine = BinanceLiveEngine(
            api_key="k", api_secret="s",
            journal_path=tmp_path / "live.jsonl",
            expected_leverage=3, run_tag=RUN_TAG, live_enable=True,
            demo=True, base_url="https://demo-fapi.binance.com",
            transport=self.transport,
            now_utc=lambda: datetime.now(timezone.utc))
        if journal_extra:
            with open(tmp_path / "live.jsonl", "a") as fh:
                fh.write(journal_extra)
        self.engine._ensure_ready(SYM)
        filt = self.engine._filters[SYM]
        self.store = RunStore(tmp_path / "runs" / "cryptobot.db")
        self.session = Session(
            self.cfg, self.store, self.workdir, run_id,
            pid=os.getpid(), clock=WallClock(), engine=self.engine)
        self.session.arm_replay_filters(
            {SYM: {"tick_size": float(filt["tick"]),
                   "step_size": float(filt["step"]),
                   "min_qty": float(filt["min_qty"]),
                   "min_notional": float(filt["min_notional"])}},
            origin="matrix", asof_utc=self.session.now_utc())
        # Depth prime is a prod-host urllib call: no network in tests.
        # Books stay unsynced (recorded); the scripted signal needs no
        # book views, and every other path stays real.
        monkeypatch.setattr(self.session, "_fetch_depth_snapshots",
                            lambda: {})
        self.signal = ScriptedSignal(self.session, shots=shots,
                                       time_exit_s=time_exit_s)
        monkeypatch.setattr(self.session, "_strategy_adapters",
                            lambda: ({"drill": self.signal}, {}))
        self.current = {}
        self.pending_fills = []
        self.stream = None

    def attach(self, **kw):
        def factory(key):
            # Reuse a test-prefabricated socket (pre-run pushes);
            # otherwise dial fresh (redials replace current["sock"]).
            # Pre-dial fills stashed by the hook drain here, in order:
            # the venue filled at ack time; the stream delivers them
            # once connected.
            if "sock" not in self.current:
                self.current["sock"] = ThreadSocket()
                for env in self.pending_fills:
                    self.current["sock"].push(env)
                self.pending_fills.clear()
            return self.current["sock"]

        kw.setdefault("poll_timeout_s", 0.05)
        kw.setdefault("initial_backoff_s", 0.01)
        self.stream = attach_user_stream(self.session, self.engine,
                                         factory, **kw)
        return self.stream

    def push_fill(self, cid, side, qty, price=MARK, fee="0.03000000"):
        tr = trade_envelope(self.orders, cid, side, qty,
                            next(_TRADE_IDS), price, fee)
        if "sock" in self.current:
            self.current["sock"].push(tr)
        else:
            # Pre-dial (e.g. a resume-retry close): the fill exists at
            # the venue now (tape noted); the stream delivers it once
            # the socket dials.
            self.pending_fills.append(tr)
        self.transport.note_stream_fill(cid, tr["o"]["t"], qty, price,
                                        fee, side)
        return tr

    def events(self, windows=6, trickle_s=0.4, price=MARK,
                 until=None, grace_s=0.0):
        """Burst + trickle; ends (feed-ended) when `until` holds.

        A finite iterator is the faithful crash point: the loop exits
        WITHOUT flattening (flatten is duration-elapsed only), no stop
        flag is written — a real crash writes nothing either. `until`
        is polled on the pump thread (file reads only).
        """
        base = int(time.time() * 1000)
        seq = [0]

        def gen():
            for i in range(windows):
                ts = base + i * 1000
                seq[0] += 1
                yield market_trade(seq[0], ts, i + 1, price + i * 0.01)
                seq[0] += 1
                yield market_bbo(seq[0], ts, price - 0.01,
                                 price + 0.01)
            while True:
                if until is not None:
                    try:
                        done = until()
                    except Exception:
                        done = False
                    if done:
                        if grace_s:
                            time.sleep(grace_s)
                        return
                time.sleep(trickle_s)
                now_ms = int(time.time() * 1000)
                seq[0] += 1
                yield market_trade(seq[0], now_ms, 100000 + seq[0],
                                   price)

        return gen()

    def close_streams(self):
        """Stop stream + engine (strict teardown calls happen here)."""
        for closer in (self.stream, self.engine):
            if closer is None:
                continue
            try:
                closer.close()
            except Exception:
                pass
        self.stream, self.engine = None, None

    def close(self):
        self.close_streams()
        if self.store is not None:
            try:
                self.store.close()
            except Exception:
                pass
            self.store = None


@pytest.fixture
def fixtures():
    ready = venues.ready_fixture()
    orders = venues.orders_fixture()
    return ready, orders, venues.drill_account(ready)


def ready_prefix(ready, key="K1"):
    # NOTE: the dial (listenKey POST) happens on first owner drain,
    # AFTER resume work — resume scripts use ready_nokey + an explicit
    # dial entry in position.
    return ready_nokey(ready) + [
        ("POST", "/fapi/v1/listenKey", None, ("ok", {"listenKey": key})),
    ]


def ready_nokey(ready):
    return [
        ("GET", "/fapi/v1/exchangeInfo", None, ("ok", ready["exchangeInfo"])),
        ("GET", "/fapi/v1/commissionRate", {"symbol": SYM},
         ("ok", ready["commissionRate"])),
        ("POST", "/fapi/v1/leverage", {"symbol": SYM, "leverage": 3},
         ("ok", ready["leverage"])),
    ]


def dial(key="K1"):
    return ("POST", "/fapi/v1/listenKey", None, ("ok", {"listenKey": key}))


def algo_deleted():
    return {"code": 200, "msg": "success"}


def close_key():
    """Strict key teardown: every attach closes its listen key."""
    return ("DELETE", "/fapi/v1/listenKey", None, ("ok", {}))


def reads_block(*paths):
    """Zero or more echo reads (recover zones with racy counts).

    Leg journaling varies with attach churn (0-2 cycles), so resume
    recovery issues a racy number of lookups; the block absorbs
    exactly the read paths given and ends at the first call past
    them (the dial, strictly scripted next).
    """
    return ("READS", frozenset(paths), None, None)


def attach_prefix(orders):
    """Strict prefix: submit + first protection attach.

    Everything after the first attach runs under CHURN_TAIL:
    supervision re-attach cycles race fill booking (0-2 extra
    cycles observed), so exact submit COUNTS and end-state carry
    the proof from here (a duplicate submit cannot hide from the
    request log + journal roles).
    """
    return [
        ("POST", "/fapi/v1/order", {"type": "LIMIT"},
         ("ok", orders["orderAck"])),
        ("GET", "/fapi/v1/order", None, ("echo", None)),
        ("GET", "/fapi/v1/userTrades", None, ("echo", None)),
        ("POST", "/fapi/v1/algoOrder", {"type": "STOP_MARKET"},
         ("ok", orders["algoAck"])),
        ("POST", "/fapi/v1/algoOrder", {"type": "TAKE_PROFIT_MARKET"},
         ("ok", orders["algoAck"])),
    ]


def order_posts(transport):
    return [r for r in transport.requests
            if r[0] == "POST" and r[1] == "/fapi/v1/order"]


def assert_order_posts(transport, expected):
    """Exact submit subsequence: [(type, side), ...] in order.

    Used wherever churn precedes a submit: positional strictness is
    impossible there, but the ordered submit list is just as exact —
    any duplicate or missing submit fails here.
    """
    posts = order_posts(transport)
    got = [(r[2]["type"], r[2]["side"]) for r in posts]
    assert got == expected, got
    return posts


def assert_leg_coverage(transport):
    """Every posted leg was cancelled (no orphan venue orders)."""
    posted = {r[2]["clientAlgoId"] for r in transport.requests
              if r[0] == "POST" and r[1] == "/fapi/v1/algoOrder"}
    cancelled = {r[2]["origClientAlgoId"] for r in transport.requests
                 if r[0] == "DELETE" and r[1] == "/fapi/v1/algoOrder"}
    assert posted, "no legs ever attached"
    assert posted <= cancelled, posted - cancelled


def checkpoint_kinds(store, run_id):
    rows = store._db.execute(
        "SELECT kind FROM checkpoints WHERE run_id=?", (run_id,)).fetchall()
    return {k for (k,) in rows}


CHURN_TAIL = {("GET", "/fapi/v1/order"),
              ("GET", "/fapi/v1/userTrades"),
              ("GET", "/fapi/v1/algoOrder"),
              ("POST", "/fapi/v1/algoOrder"),
              ("DELETE", "/fapi/v1/algoOrder"),
              ("DELETE", "/fapi/v1/listenKey")}
# Post-attach zone: churn may precede the close, so its position is
# not strict — but the SUBMIT SUBSEQUENCE is asserted exactly
# (order + params + count), which no duplicate can hide from.
SUBMIT_TAIL = CHURN_TAIL | {("POST", "/fapi/v1/order")}
# Zero-submit zone: only reads are tolerated; ANY submit raises out
# of the transport (rows 8/9 prove it positionally).
READ_TAIL = {("GET", "/fapi/v1/order"),
             ("GET", "/fapi/v1/userTrades"),
             ("GET", "/fapi/v1/algoOrder")}


def auto_fill_hook(rig):
    """Queue a full fill for every venue order POST (entry + closes)."""
    seen = []

    def hook(kind, params):
        if kind != "order":
            return
        cid = params["newClientOrderId"]
        seen.append(cid)
        rig.push_fill(cid, params.get("side", "BUY"),
                      params["quantity"])

    hook.seen = seen
    return hook


def assert_reconciled_clean(session, store, run_id):
    """Zero unexplained differences: no unbooked/rejected/unknown rows."""
    rows = store._db.execute(
        "SELECT kind, payload FROM checkpoints WHERE run_id=?",
        (run_id,)).fetchall()
    bad = [json.loads(p) for k, p in rows
           if k in ("fill-unbooked", "booking-rejected")]
    assert not bad, bad
    assert session._booking_blocked is None, session._booking_blocked


def booked_client_ids(workdir):
    ids = set()
    path = workdir / "fills.jsonl"
    if not path.exists():
        return ids
    for line in path.read_text().splitlines():
        if line.strip():
            ids.add(json.loads(line)["client_order_id"])
    return ids


def test_row01_happy_path(tmp_path, monkeypatch, fixtures):
    """Row 1: admit -> fill -> verified protect -> time-exit -> flat."""
    ready, orders, account = fixtures
    script = ready_prefix(ready) + attach_prefix(orders)
    rig = Rig(tmp_path, monkeypatch, ready, orders, account, script,
              shots=1, time_exit_s=4, tail=SUBMIT_TAIL)
    rig.transport._hook = auto_fill_hook(rig)
    rig.attach()
    try:
        report = rig.session.run_live(rig.events(), duration_s=9,
                                      expect_class=CLASS)
        rig.close_streams()
        rig.transport.assert_empty()
        assert report["intents_admitted"] == 1, report["reject_counts"]
        assert report["open_position"] is False
        assert report["position_qty"] == 0.0
        assert rig.session.ledger.position_qty() == 0.0
        posts = assert_order_posts(rig.transport, [("LIMIT", "BUY"),
                                                   ("MARKET", "SELL")])
        assert posts[1][2].get("reduceOnly") == "true"
        booked = booked_client_ids(rig.workdir)
        for _, _, params, _ in posts:
            assert params["newClientOrderId"] in booked
        assert "protection-verified" in checkpoint_kinds(
            rig.store, rig.run_id)
        assert_leg_coverage(rig.transport)
        assert ("DELETE", "/fapi/v1/listenKey") in [
            (m, p) for m, p, _, _ in rig.transport.requests], \
            "listen key leaked (no teardown DELETE)"
        assert rig.transport.poll_counts, "margin polling path live"
        assert_reconciled_clean(rig.session, rig.store, rig.run_id)
    finally:
        rig.close()


def journal_rows(tmp_path):
    """All journal records (tolerant of a racing writer)."""
    path = tmp_path / "live.jsonl"
    if not path.exists():
        return []
    try:
        text = path.read_text()
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            break  # torn tail line; retry next poll.
    return out


def journal_intents(tmp_path):
    """submit-intent journal records (tolerant of a racing writer)."""
    return [r for r in journal_rows(tmp_path)
            if r.get("event") == "submit-intent"]


def fills_rows(workdir):
    path = workdir / "fills.jsonl"
    if not path.exists():
        return []
    try:
        text = path.read_text()
    except OSError:
        return []
    rows = []
    for line in text.splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError:
                break
    return rows


class Crasher:
    """Phase A on a worker thread (R1: build/run/close stay together).

    The feed ends itself when `until` holds (feed-ended exit, no
    flatten, no stop flag — a real crash writes nothing). After join,
    in-memory rig state is quiescent and safe to read; sqlite
    assertions use a fresh test-thread store.
    """

    def __init__(self, tmp_path, monkeypatch, fixtures, script, *,
                 shots, run_id, hook, until, exact_teardown=True,
                 time_exit_s=600, grace_s=0.0, tail=None):
        self.tmp_path = tmp_path
        self.monkeypatch = monkeypatch
        self.fixtures = fixtures
        self.script = script
        self.shots = shots
        self.run_id = run_id
        self.hook = hook
        self.until = until
        self.exact_teardown = exact_teardown
        self.time_exit_s = time_exit_s
        self.grace_s = grace_s
        self.tail = tail
        self.rig = None
        self.outcome = {}
        self.worker = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        ready, orders, account = self.fixtures
        try:
            self.rig = Rig(self.tmp_path, self.monkeypatch, ready,
                           orders, account, self.script,
                           shots=self.shots, run_id=self.run_id,
                           time_exit_s=self.time_exit_s, tail=self.tail)
            self.rig.transport._hook = self.hook(self.rig)
            self.rig.attach()
            self.outcome["report"] = self.rig.session.run_live(
                self.rig.events(until=self.until, grace_s=self.grace_s),
                duration_s=30, expect_class=CLASS)
        except Exception as exc:  # noqa: BLE001 - re-raised by caller.
            self.outcome["error"] = exc
        finally:
            if self.rig is not None:
                if not self.exact_teardown:
                    self.rig.transport.discard()
                self.rig.close()

    def start(self):
        self.worker.start()
        return self

    def join(self, timeout_s=25.0):
        self.worker.join(timeout=timeout_s)
        assert not self.worker.is_alive(), "phase A did not end"
        assert "error" not in self.outcome, self.outcome["error"]
        return self.outcome.get("report")


def push_after_resume(tmp_path, run_id, rig, cid, qty, side="BUY"):
    """Push a held fill once phase B's resume checkpoints (own store)."""
    done = {}

    def run():
        store = RunStore(tmp_path / "runs" / "cryptobot.db")
        try:
            deadline = time.monotonic() + 15.0
            while time.monotonic() < deadline:
                rows = store._db.execute(
                    "SELECT kind FROM checkpoints WHERE run_id=?",
                    (run_id,)).fetchall()
                if "live-resume" in {k for (k,) in rows}:
                    # Premise pin: recover ran BEFORE any tape exists,
                    # so the booking below takes the stream path only.
                    assert not rig.transport._tape, rig.transport._tape
                    rig.push_fill(cid, side, qty)
                    done["pushed"] = True
                    return
                time.sleep(0.05)
            done["error"] = "resume never checkpointed"
        finally:
            store.close()

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    return worker, done


def test_row06_restart_with_exposure(tmp_path, monkeypatch, fixtures):
    """Row 6 (W2 case): crash with venue exposure unadopted; the
    post-restart entry fill must book, protect, and flatten to flat."""
    ready, orders, account = fixtures
    script_a = ready_prefix(ready) + [
        ("POST", "/fapi/v1/order", {"type": "LIMIT"},
         ("ok", orders["orderAck"])),
        close_key(),
    ]
    crash = Crasher(tmp_path, monkeypatch, fixtures, script_a,
                    shots=1, run_id="matrix-r6", time_exit_s=8,
                    hook=lambda rig: (lambda k, p: None),
                    until=lambda: any(
                        r.get("event") == "submitted"
                        for r in journal_rows(tmp_path))).start()
    crash.join()
    rig_a = crash.rig
    rig_a.transport.assert_empty()
    assert rig_a.session.ledger.position_qty() == 0.0

    # Phase B: brand-new objects on the same durable paths.
    script_b = [
        ("GET", "/fapi/v1/exchangeInfo", None,
         ("ok", ready["exchangeInfo"])),
        ("GET", "/fapi/v1/commissionRate", {"symbol": SYM},
         ("ok", ready["commissionRate"])),
        ("POST", "/fapi/v1/leverage", {"symbol": SYM, "leverage": 3},
         ("ok", ready["leverage"])),
        # Recover sees the entry open (fill held back): no adopt.
        ("GET", "/fapi/v1/order", None, ("echo", None)),
        ("POST", "/fapi/v1/listenKey", None, ("ok", {"listenKey": "K2"})),
    ]
    rig_b = Rig(tmp_path, monkeypatch, ready, orders, account,
                script_b, shots=0, run_id="matrix-r6",
                tail=SUBMIT_TAIL)
    rig_b.transport._hook = auto_fill_hook(rig_b)
    rig_b.attach()
    [entry_cid] = [r[2]["newClientOrderId"] for r in
                   rig_a.transport.requests
                   if r[0] == "POST" and r[1] == "/fapi/v1/order"]
    entry_qty = [r[2]["quantity"] for r in rig_a.transport.requests
                 if r[0] == "POST" and r[1] == "/fapi/v1/order"][0]
    # The held venue fill arrives strictly after resume checkpoints,
    # so booking takes the stream path only (no recover-adopt race).
    rig_b.current["sock"] = ThreadSocket()
    pusher, pushed = push_after_resume(tmp_path, "matrix-r6", rig_b,
                                       entry_cid, entry_qty)
    try:
        report = rig_b.session.run_live(rig_b.events(), duration_s=12,
                                        expect_class=CLASS, resume=True)
        rig_b.close_streams()
        pusher.join(timeout=5.0)
        assert pushed.get("pushed"), pushed.get("error")
        rig_b.transport.assert_empty()
        assert entry_cid in booked_client_ids(rig_b.workdir), \
            "post-restart entry fill never booked (defect 2)"
        assert_order_posts(rig_b.transport, [("MARKET", "SELL")])
        assert "shell-restored" in checkpoint_kinds(
            rig_b.store, rig_b.run_id)
        assert "protection-verified" in checkpoint_kinds(
            rig_b.store, rig_b.run_id)
        assert_leg_coverage(rig_b.transport)
        assert report["open_position"] is False
        assert rig_b.session.ledger.position_qty() == 0.0
        assert_reconciled_clean(rig_b.session, rig_b.store, rig_b.run_id)
    finally:
        rig_b.close()


def test_row06b_restart_booked_exposure_flattens(tmp_path, monkeypatch,
                                                 fixtures):
    """Row 6b (defect 1): crash with booked exposure; the resume
    pending-flatten retry must submit a TRACKED close (entry
    reservation), whose fill books the ledger flat."""
    ready, orders, account = fixtures
    script_a = ready_prefix(ready) + attach_prefix(orders)
    # Crash after the first pair attaches plus a grace beat so
    # verification settles: booked exposure + live protected legs.
    crash = Crasher(tmp_path, monkeypatch, fixtures, script_a,
                    shots=1, run_id="matrix-r6b", exact_teardown=False,
                    until=lambda: sum(
                        1 for r in journal_intents(tmp_path)
                        if r.get("algo")) >= 2,
                    grace_s=2.0, tail=CHURN_TAIL,
                    hook=auto_fill_hook).start()
    crash.join()
    rig_a = crash.rig
    assert rig_a.session.ledger.position_qty() != 0.0

    script_b = ready_nokey(ready) + [
        # Reconcile shell legs, cancel them, adopt entry (dup-skip),
        # re-attach in the retry drain, submit the ONE retry close,
        # then the first-drain dial.
        ("GET", "/fapi/v1/algoOrder", None, ("echo", None)),
        ("GET", "/fapi/v1/algoOrder", None, ("echo", None)),
        ("DELETE", "/fapi/v1/algoOrder", None, ("ok", algo_deleted())),
        ("DELETE", "/fapi/v1/algoOrder", None, ("ok", algo_deleted())),
        ("GET", "/fapi/v1/order", None, ("echo", None)),
        ("GET", "/fapi/v1/userTrades", None, ("echo", None)),
        ("POST", "/fapi/v1/algoOrder", {"type": "STOP_MARKET"},
         ("ok", orders["algoAck"])),
        ("POST", "/fapi/v1/algoOrder", {"type": "TAKE_PROFIT_MARKET"},
         ("ok", orders["algoAck"])),
        ("POST", "/fapi/v1/order", {"type": "MARKET"},
         ("ok", orders["orderAck"])),
        dial("K2"),
    ]
    rig_b = Rig(tmp_path, monkeypatch, ready, orders, account,
                script_b, shots=0, run_id="matrix-r6b",
                tail=SUBMIT_TAIL)
    rig_b.transport._hook = auto_fill_hook(rig_b)
    # Same venue, new connection: the tape carries over.
    rig_b.transport._tape = copy.deepcopy(rig_a.transport._tape)
    rig_b.attach()
    try:
        report = rig_b.session.run_live(rig_b.events(), duration_s=6,
                                        expect_class=CLASS, resume=True)
        rig_b.close_streams()
        rig_b.transport.assert_empty()
        posts = assert_order_posts(rig_b.transport, [("MARKET", "SELL")])
        assert posts[0][2].get("reduceOnly") == "true"
        intents = [json.loads(line) for line in
                   (tmp_path / "live.jsonl").read_text().splitlines()
                   if line.strip()]
        intents = [r for r in intents if r.get("event") == "submit-intent"]
        entries = [r for r in intents if r.get("role") == "entry"]
        # Closes journal as role=target/kind=MARKET (session.py:2264);
        # TP legs share the role but are TAKE_PROFIT_MARKET kind.
        closes = [r for r in intents if r.get("role") == "target"
                  and r.get("kind") == "MARKET"]
        assert entries and len(closes) == 1, \
            "resume must submit exactly one retry close"
        assert closes[0]["reservation_id"], \
            "retry close submitted reservation-None (defect 1)"
        assert (closes[0]["reservation_id"]
                == entries[0]["reservation_id"])
        assert "shell-restored" in checkpoint_kinds(
            rig_b.store, rig_b.run_id)
        assert_leg_coverage(rig_b.transport)
        assert rig_b.session.ledger.position_qty() == 0.0, \
            "close fill never booked; ledger keeps exposure (defect 1)"
        assert report["open_position"] is False
        assert_reconciled_clean(rig_b.session, rig_b.store, rig_b.run_id)
    finally:
        rig_b.close()


def dupe_push_hook(rig):
    """Redeliver every venue order fill twice (same trade id).

    The stream replays the identical envelope; exec-id dedup must
    book it once (row 2).
    """

    def hook(kind, params):
        if kind != "order":
            return
        tr = rig.push_fill(params["newClientOrderId"],
                           params.get("side", "BUY"),
                           params["quantity"])
        rig.current["sock"].push(tr)  # identical redelivery

    return hook


def test_row02_duplicate_stream_events(tmp_path, monkeypatch, fixtures):
    """Row 2: the same fill delivered twice books once, flat, clean."""
    ready, orders, account = fixtures
    script = ready_prefix(ready) + attach_prefix(orders)
    rig = Rig(tmp_path, monkeypatch, ready, orders, account, script,
              shots=1, time_exit_s=4, tail=SUBMIT_TAIL)
    rig.transport._hook = dupe_push_hook(rig)
    rig.attach()
    try:
        report = rig.session.run_live(rig.events(), duration_s=13,
                                      expect_class=CLASS)
        rig.close_streams()
        rig.transport.assert_empty()
        assert report["intents_admitted"] == 1, report["reject_counts"]
        assert report["open_position"] is False
        assert rig.session.ledger.position_qty() == 0.0
        rows = [json.loads(line) for line in
                (rig.workdir / "fills.jsonl").read_text().splitlines()
                if line.strip()]
        # Entry + close, each booked exactly once despite redelivery.
        assert len(rows) == 2, [r["client_order_id"] for r in rows]
        posts = assert_order_posts(rig.transport, [("LIMIT", "BUY"),
                                                   ("MARKET", "SELL")])
        assert {r["client_order_id"] for r in rows} == {
            p[2]["newClientOrderId"] for p in posts}
        assert "protection-verified" in checkpoint_kinds(
            rig.store, rig.run_id)
        assert_leg_coverage(rig.transport)
        assert_reconciled_clean(rig.session, rig.store, rig.run_id)
    finally:
        rig.close()


def push_delayed(rig, delay_s):
    """Deliver the first order's fill `delay_s` after its submit.

    The helper polls the (in-memory, GIL-appended) request log for the
    entry POST — no store touches from this thread (R1 ownership).
    """

    stamp = {}

    def worker():
        cid = qty = side = None
        deadline = time.time() + 30
        while time.time() < deadline:
            for r in list(rig.transport.requests):
                if r[0] == "POST" and r[1] == "/fapi/v1/order":
                    cid = r[2]["newClientOrderId"]
                    qty = r[2]["quantity"]
                    side = r[2].get("side", "BUY")
                    break
            if cid is not None:
                break
            time.sleep(0.05)
        assert cid is not None, "entry submit never seen"
        stamp["submit_seen"] = time.time()
        time.sleep(delay_s)
        stamp["pushed"] = time.time()
        rig.push_fill(cid, side, qty)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.stamp = stamp
    return t


def fill_after_first_hook(rig):
    """Auto-fill every order POST except the first (row 3).

    The entry fill arrives late via push_delayed; the close (and any
    later order) fills immediately on POST.
    """
    seen = []

    def hook(kind, params):
        if kind != "order":
            return
        cid = params["newClientOrderId"]
        seen.append(cid)
        if len(seen) == 1:
            return
        rig.push_fill(cid, params.get("side", "BUY"),
                      params["quantity"])

    hook.seen = seen
    return hook


def test_row03_delayed_ack(tmp_path, monkeypatch, fixtures):
    """Row 3: a 3s ack gap books late, submits once, exits flat."""
    ready, orders, account = fixtures
    # Strict only through the submit ack: with the fill 3s out,
    # supervision takes an unfilled path (extra reads/churn), so
    # everything after the submit runs under SUBMIT_TAIL with the
    # exact submit subsequence asserted at the end.
    script = ready_prefix(ready) + attach_prefix(orders)[:1]
    rig = Rig(tmp_path, monkeypatch, ready, orders, account, script,
              shots=1, time_exit_s=8, tail=SUBMIT_TAIL)
    rig.transport._hook = fill_after_first_hook(rig)
    seen_posts = rig.transport._hook.seen
    rig.attach()
    pusher = push_delayed(rig, 3.0)
    try:
        report = rig.session.run_live(rig.events(), duration_s=16,
                                      expect_class=CLASS)
        pusher.join(timeout=10)
        assert (pusher.stamp["pushed"] - pusher.stamp["submit_seen"]
                >= 2.5), pusher.stamp
        rig.close_streams()
        rig.transport.assert_empty()
        assert report["intents_admitted"] == 1, report["reject_counts"]
        assert report["open_position"] is False
        assert rig.session.ledger.position_qty() == 0.0
        # The late entry fill landed exactly once: no duplicate
        # submit was issued while the ack was outstanding.
        assert_order_posts(rig.transport, [("LIMIT", "BUY"),
                                           ("MARKET", "SELL")])
        assert len(seen_posts) == 2, seen_posts
        assert "protection-verified" in checkpoint_kinds(
            rig.store, rig.run_id)
        assert_leg_coverage(rig.transport)
        assert_reconciled_clean(rig.session, rig.store, rig.run_id)
    finally:
        rig.close()


def burst_events(n, gap_ms=5):
    """An n-event instant burst, then a live wall-clock trickle.

    The pump enqueues the burst far faster than control drains it,
    so the bounded queue overflows (drop-oldest, counted); the
    trickle proves the loop keeps flowing after the overflow.
    """
    base = int(time.time() * 1000)
    seq = [0]

    def gen():
        for i in range(n):
            seq[0] += 1
            yield market_trade(seq[0], base + i * gap_ms, i + 1)
        while True:
            time.sleep(0.4)
            now = int(time.time() * 1000)
            seq[0] += 1
            yield market_trade(seq[0], now, n + seq[0])
            seq[0] += 1
            yield market_bbo(seq[0], now)

    return gen()


def test_row08_queue_pressure(tmp_path, monkeypatch, fixtures):
    """Row 8: a 20000-event burst drops (counted); loop ticks on, zero submits.

    Control drains one event per tick, so it can only ever see ~30
    events in 6s; the burst must overflow LOUDLY (counted drops),
    not stall, halt, or submit.
    """
    ready, orders, account = fixtures
    script = ready_prefix(ready)
    rig = Rig(tmp_path, monkeypatch, ready, orders, account, script,
              shots=0, time_exit_s=600, tail=READ_TAIL)
    rig.attach()
    try:
        report = rig.session.run_live(burst_events(20000), duration_s=6,
                                      expect_class=CLASS)
        rig.close_streams()
        rig.transport.assert_empty()
        assert report["intents_admitted"] == 0, report["reject_counts"]
        assert report["dropped_feed_events"] > 1000, report[
            "dropped_feed_events"]
        assert report["events_seen"] >= 20, report["events_seen"]
        assert report["latency_ms"]["control_step"]["n"] >= 20
        # Zero submits, positionally: READ_TAIL raises on any order/
        # algo POST, and the request log must show none either way
        # (setup POSTs — leverage, listenKey — excluded).
        assert not [r for r in rig.transport.requests
                    if r[0] == "POST" and r[1] in (
                        "/fapi/v1/order", "/fapi/v1/algoOrder")]
        assert report["open_position"] is False
        assert rig.session.ledger.position_qty() == 0.0
        assert_reconciled_clean(rig.session, rig.store, rig.run_id)
    finally:
        rig.close()


def stale_events(stale_ms=60000):
    """Burst + trickle frozen `stale_ms` in the past (row 9)."""
    base = int(time.time() * 1000) - stale_ms
    seq = [0]

    def gen():
        for i in range(6):
            ts = base + i * 1000
            seq[0] += 1
            yield market_trade(seq[0], ts, i + 1)
            seq[0] += 1
            yield market_bbo(seq[0], ts)
        frozen = base + 6000
        while True:
            time.sleep(0.4)
            seq[0] += 1
            yield market_trade(seq[0], frozen, 100 + seq[0])
            seq[0] += 1
            yield market_bbo(seq[0], frozen)

    return gen()


def test_row04_ambiguous_submit(tmp_path, monkeypatch, fixtures):
    """Row 4: a 503 entry submit kills loudly; resume adopts, books, flattens.

    Phase A: the submit raises UnknownOutcomeError out of run_live
    (fail-loud); teardown still closes the key, and the durable
    residue is a journaled submit-intent + submit-outcome-unknown
    with an open (eid-less) submit command — no admit, no shell.
    Phase B: resume recovers via lookup, books the adopted fill
    under its journaled reservation (the submit never returned, so
    no command row carries the cid), and flattens the orphan to
    flat. No entry is ever re-submitted (no double exposure);
    entries stay blocked on the unknown command (fail-closed).
    """
    ready, orders, account = fixtures
    script_a = ready_prefix(ready) + [
        ("POST", "/fapi/v1/order", {"type": "LIMIT"},
         ("timeout", {"fill": {"price": MARK}})),
        close_key(),
    ]
    rig_a = Rig(tmp_path, monkeypatch, ready, orders, account,
                script_a, shots=1, run_id="matrix-r4",
                time_exit_s=4, tail=SUBMIT_TAIL)
    rig_a.attach()
    try:
        with pytest.raises(UnknownOutcomeError):
            rig_a.session.run_live(rig_a.events(), duration_s=9,
                                   expect_class=CLASS)
        rig_a.close_streams()
        rig_a.transport.assert_empty()
        assert rig_a.transport.flow == [
            ("GET", "/fapi/v1/exchangeInfo"),
            ("GET", "/fapi/v1/commissionRate"),
            ("POST", "/fapi/v1/leverage"),
            ("POST", "/fapi/v1/listenKey"),
            ("POST", "/fapi/v1/order"),
            ("DELETE", "/fapi/v1/listenKey")]
        kinds_a = checkpoint_kinds(rig_a.store, "matrix-r4")
        assert "admit" not in kinds_a, kinds_a
        assert not (rig_a.workdir / "position.json").exists()
        assert rig_a.session.ledger.position_qty() == 0.0
        cmds_a = rig_a.store.open_commands("matrix-r4")
        assert len(cmds_a) == 1 and cmds_a[0]["status"] == "intended"
        assert cmds_a[0].get("engine_client_id") is None
        [(amb_cid, amb_fills)] = list(rig_a.transport._tape.items())
        assert len(amb_fills) == 1
        journal = journal_rows(tmp_path)
        assert any(r.get("event") == "submit-intent"
                   and r.get("client_id") == amb_cid
                   for r in journal), "submit-intent not journaled"
        assert any(r.get("event") == "submit-outcome-unknown"
                   and r.get("client_id") == amb_cid
                   for r in journal), "unknown outcome not journaled"
    finally:
        rig_a.close()

    # Phase B: brand-new objects on the same durable paths. The venue
    # truth (the fill) persists across the restart: reseed the fresh
    # transport's tape with the same trade.
    amb_fill = amb_fills[0]
    script_b = ready_nokey(ready) + [
        ("GET", "/fapi/v1/order", None, ("echo", None)),
        ("GET", "/fapi/v1/userTrades", None, ("echo", None)),
        # Resume flatten fires pre-dial (the adopted exposure books
        # during recover): the close ack precedes the dial.
        ("POST", "/fapi/v1/order", {"type": "MARKET"},
         ("ok", orders["orderAck"])),
        ("POST", "/fapi/v1/listenKey", None,
         ("ok", {"listenKey": "K2"})),
    ]
    rig_b = Rig(tmp_path, monkeypatch, ready, orders, account,
                script_b, shots=0, run_id="matrix-r4",
                tail=SUBMIT_TAIL)
    rig_b.transport._hook = auto_fill_hook(rig_b)
    rig_b.transport.note_stream_fill(
        amb_cid, amb_fill["trade_id"], amb_fill["qty"],
        amb_fill["price"], amb_fill["fee"], amb_fill["side"])
    rig_b.attach()
    try:
        report = rig_b.session.run_live(
            rig_b.events(), duration_s=8, expect_class=CLASS,
            resume=True)
        rig_b.close_streams()
        rig_b.transport.assert_empty()
        assert report["intents_admitted"] == 0, report["reject_counts"]
        assert report["open_position"] is False
        assert report["position_qty"] == 0.0
        assert rig_b.session.ledger.position_qty() == 0.0
        rows = [json.loads(line) for line in
                (rig_b.workdir / "fills.jsonl").read_text().splitlines()
                if line.strip()]
        assert len(rows) == 2, rows
        assert rows[0]["client_order_id"] == amb_cid
        assert rows[0]["side"] == "BUY"
        assert rows[1]["side"] == "SELL"
        # Exactly one close; the entry is NEVER re-submitted.
        assert_order_posts(rig_b.transport, [("MARKET", "SELL")])
        kinds_b = checkpoint_kinds(rig_b.store, "matrix-r4")
        assert "flatten" in kinds_b, kinds_b
        assert "resume-blocked" in kinds_b, kinds_b
        assert "fill-unbooked" not in kinds_b, kinds_b
        cmds_b = rig_b.store.open_commands("matrix-r4")
        assert len(cmds_b) == 1 and cmds_b[0]["status"] == "unknown"
        assert_reconciled_clean(rig_b.session, rig_b.store,
                                rig_b.run_id)
    finally:
        rig_b.close()


def wait_for_fills(workdir, n, timeout_s=30):
    """Poll fills.jsonl (file-based: safe from any thread)."""
    path = workdir / "fills.jsonl"
    deadline = time.time() + timeout_s
    rows = []
    while time.time() < deadline:
        if path.exists():
            rows = [ln for ln in path.read_text().splitlines()
                    if ln.strip()]
            if len(rows) >= n:
                return rows
        time.sleep(0.1)
    raise AssertionError(f"only {len(rows)} fills in {timeout_s}s")


def test_row05_disconnect(tmp_path, monkeypatch, fixtures):
    """Row 5: socket death blocks entries, reconnect heals, loop resumes.

    Position 1 trades fully, then the orchestrator kills the stream
    socket: the dead window rejects the gate-2 probe with a stream:
    reason (entries blocked, loop alive), a fresh socket redials on
    the retained key (no new listenKey), and gate 3 admits position
    2 on the healed stream. Both flatten via time exit.
    """
    ready, orders, account = fixtures
    script = ready_prefix(ready) + attach_prefix(orders)
    rig = Rig(tmp_path, monkeypatch, ready, orders, account, script,
              shots=1, run_id="matrix-r5", time_exit_s=4,
              tail=SUBMIT_TAIL, cooldown_s=3, max_mark_age_ms=30000)
    gates = [threading.Event() for _ in range(3)]
    gated = GatedSignal(rig.session, gates, time_exit_s=4)
    monkeypatch.setattr(rig.session, "_strategy_adapters",
                        lambda: ({"drill": gated}, {}))
    rig.signal = gated
    rig.transport._hook = auto_fill_hook(rig)
    rig.attach()
    gates[0].set()
    stamp = {}

    def orchestrate():
        # Kill only once position 1 is fully booked (both fills on
        # disk): nothing is stuck in the dying socket's queue.
        wait_for_fills(rig.workdir, 2)
        stamp["flat1"] = time.time()
        rig.current["sock"].die = True
        stamp["killed"] = time.time()
        deadline = time.time() + 10
        while not rig.stream.halted and time.time() < deadline:
            time.sleep(0.05)
        assert rig.stream.halted, "dead socket never halted entries"
        stamp["dead_seen"] = time.time()
        gates[1].set()
        time.sleep(2.5)  # let stream: rejects accumulate.
        rig.current["sock"] = ThreadSocket()
        stamp["swapped"] = time.time()
        deadline = time.time() + 15
        while rig.stream.halted and time.time() < deadline:
            time.sleep(0.05)
        assert not rig.stream.halted, "redial never healed"
        stamp["healed"] = time.time()
        # Past the compressed cooldown from either anchor (admit or
        # close of position 1): gate 3 must test the healed stream,
        # not the selector.
        while time.time() < stamp["flat1"] + 8:
            time.sleep(0.2)
        gates[2].set()

    orch = threading.Thread(target=orchestrate, daemon=True)
    orch.start()
    try:
        report = rig.session.run_live(rig.events(), duration_s=26,
                                      expect_class=CLASS)
        orch.join(timeout=10)
        assert not orch.is_alive(), "orchestrator stuck"
        rig.close_streams()
        rig.transport.assert_empty()
        assert report["intents_admitted"] == 2, report["reject_counts"]
        stream_rejects = {r: c for r, c in report["reject_counts"].items()
                          if r.startswith("stream:")}
        assert sum(stream_rejects.values()) >= 1, report["reject_counts"]
        assert stamp["dead_seen"] - stamp["killed"] < 5, stamp
        assert stamp["healed"] - stamp["swapped"] < 10, stamp
        assert report["open_position"] is False
        assert rig.session.ledger.position_qty() == 0.0
        assert_order_posts(rig.transport, [("LIMIT", "BUY"),
                                           ("MARKET", "SELL"),
                                           ("LIMIT", "BUY"),
                                           ("MARKET", "SELL")])
        rows = [json.loads(line) for line in
                (rig.workdir / "fills.jsonl").read_text().splitlines()
                if line.strip()]
        assert len(rows) == 4, [r["client_order_id"] for r in rows]
        kinds = checkpoint_kinds(rig.store, rig.run_id)
        assert "user-stream-gap" in kinds, kinds
        assert "user-stream-healed" in kinds, kinds
        assert "protection-verified" in kinds, kinds
        assert_leg_coverage(rig.transport)
        assert_reconciled_clean(rig.session, rig.store, rig.run_id)
    finally:
        rig.close()


def poison_first_close_hook(rig):
    """Auto-fill, but the first close reports a malformed fee (row 7).

    The engine accepts the envelope; the policy rejects the booking
    (fail-closed flagging, not a phantom fill).
    """
    seen = []

    def hook(kind, params):
        if kind != "order":
            return
        cid = params["newClientOrderId"]
        seen.append(cid)
        fee = "-1.00" if len(seen) == 2 else "0.03000000"
        rig.push_fill(cid, params.get("side", "BUY"),
                      params["quantity"], fee=fee)

    hook.seen = seen
    return hook


def test_row07_booking_failure(tmp_path, monkeypatch, fixtures):
    """Row 7: a malformed close fill is rejected loudly, exit self-heals.

    The first close books nothing (booking-rejected + booking block,
    entries stop); the position stays open, so the time-exit re-fires
    and the second close books normally. The run ends flat with the
    failure VISIBLE (rejected checkpoint + block), never silently
    absorbed: the poisoned close's cid is absent from fills.
    """
    ready, orders, account = fixtures
    script = ready_prefix(ready) + attach_prefix(orders)
    rig = Rig(tmp_path, monkeypatch, ready, orders, account, script,
              shots=1, run_id="matrix-r7", time_exit_s=4,
              tail=SUBMIT_TAIL)
    rig.transport._hook = poison_first_close_hook(rig)
    rig.attach()
    try:
        report = rig.session.run_live(rig.events(), duration_s=12,
                                      expect_class=CLASS)
        rig.close_streams()
        rig.transport.assert_empty()
        assert report["intents_admitted"] == 1, report["reject_counts"]
        posts = assert_order_posts(rig.transport, [("LIMIT", "BUY"),
                                                   ("MARKET", "SELL"),
                                                   ("MARKET", "SELL")])
        rows = [json.loads(line) for line in
                (rig.workdir / "fills.jsonl").read_text().splitlines()
                if line.strip()]
        assert len(rows) == 2, rows
        assert rows[0]["client_order_id"] == posts[0][2][
            "newClientOrderId"]
        assert rows[0]["side"] == "BUY"
        # The booked SELL is the SECOND close; the poisoned first
        # close's cid never booked.
        assert rows[1]["side"] == "SELL"
        assert rows[1]["client_order_id"] == posts[2][2][
            "newClientOrderId"]
        assert rows[1]["client_order_id"] != posts[1][2][
            "newClientOrderId"]
        kinds = checkpoint_kinds(rig.store, rig.run_id)
        assert "booking-rejected" in kinds, kinds
        assert "fill-unbooked" not in kinds, kinds
        assert (rig.session._booking_blocked or "").startswith(
            "booking-rejected:"), rig.session._booking_blocked
        assert report["open_position"] is False
        assert rig.session.ledger.position_qty() == 0.0
        assert_leg_coverage(rig.transport)
        # No assert_reconciled_clean: the booking-rejected checkpoint
        # is the row's proof, not dirt.
    finally:
        rig.close()


def test_row10_halt_independence(tmp_path, monkeypatch, fixtures):
    """Row 10: supervision proceeds while the stream is halted.

    The socket dies with position 1 open: the time-exit close is
    still submitted (REST is independent of the stream halt), its
    stream push dies with the old socket, and the post-heal
    reconnect lookup adopts the close fill from venue truth. Flat.
    """
    ready, orders, account = fixtures
    script = ready_prefix(ready) + attach_prefix(orders)
    rig = Rig(tmp_path, monkeypatch, ready, orders, account, script,
              shots=1, run_id="matrix-r10", time_exit_s=4,
              tail=SUBMIT_TAIL)
    rig.transport._hook = auto_fill_hook(rig)
    rig.attach()
    stamp = {}

    def orchestrate():
        wait_for_fills(rig.workdir, 1)
        time.sleep(1.0)
        rig.current["sock"].die = True
        stamp["killed"] = time.time()
        deadline = time.time() + 10
        while not rig.stream.halted and time.time() < deadline:
            time.sleep(0.05)
        assert rig.stream.halted, "dead socket never halted entries"
        stamp["dead_seen"] = time.time()
        # The close must submit DURING the outage (halt-independent
        # supervision) — not after the heal.
        deadline = time.time() + 15
        while time.time() < deadline:
            if any(r[0] == "POST" and r[1] == "/fapi/v1/order"
                   and r[2].get("type") == "MARKET"
                   for r in list(rig.transport.requests)):
                break
            time.sleep(0.05)
        else:
            raise AssertionError("close never submitted while halted")
        stamp["close_seen"] = time.time()
        time.sleep(1.0)
        rig.current["sock"] = ThreadSocket()
        stamp["swapped"] = time.time()
        deadline = time.time() + 15
        while rig.stream.halted and time.time() < deadline:
            time.sleep(0.05)
        assert not rig.stream.halted, "redial never healed"
        stamp["healed"] = time.time()

    orch = threading.Thread(target=orchestrate, daemon=True)
    orch.start()
    try:
        report = rig.session.run_live(rig.events(), duration_s=14,
                                      expect_class=CLASS)
        orch.join(timeout=10)
        assert not orch.is_alive(), "orchestrator stuck"
        rig.close_streams()
        rig.transport.assert_empty()
        assert report["intents_admitted"] == 1, report["reject_counts"]
        assert stamp["close_seen"] < stamp["swapped"], stamp
        assert report["open_position"] is False
        assert rig.session.ledger.position_qty() == 0.0
        assert_order_posts(rig.transport, [("LIMIT", "BUY"),
                                           ("MARKET", "SELL")])
        rows = [json.loads(line) for line in
                (rig.workdir / "fills.jsonl").read_text().splitlines()
                if line.strip()]
        assert len(rows) == 2, [r["client_order_id"] for r in rows]
        kinds = checkpoint_kinds(rig.store, rig.run_id)
        assert "user-stream-gap" in kinds, kinds
        assert "user-stream-healed" in kinds, kinds
        assert "protection-verified" in kinds, kinds
        assert_leg_coverage(rig.transport)
        assert_reconciled_clean(rig.session, rig.store, rig.run_id)
    finally:
        rig.close()


def test_row13_foreign_positions(tmp_path, monkeypatch, fixtures):
    """Row 13: a fill for a never-submitted id books nothing, blocks entries.

    The venue reports a fill for FOREIGN-1 (manual trade, another
    strategy — not ours): the engine relays it, the session flags it
    foreign (fill-unbooked + booking block), books nothing, submits
    nothing, and rejects the gated shot on the block.
    """
    ready, orders, account = fixtures
    script = ready_prefix(ready)
    rig = Rig(tmp_path, monkeypatch, ready, orders, account, script,
              shots=1, run_id="matrix-r13", time_exit_s=600,
              tail=READ_TAIL)
    rig.transport._hook = auto_fill_hook(rig)
    # Pre-dial stash: delivered on dial, before any strategy shot.
    rig.push_fill("FOREIGN-1", "BUY", 1.0)
    gates = [threading.Event()]
    gated = GatedSignal(rig.session, gates, time_exit_s=600)
    monkeypatch.setattr(rig.session, "_strategy_adapters",
                        lambda: ({"drill": gated}, {}))
    rig.signal = gated
    rig.attach()
    stamp = {}

    def orchestrate():
        # The shot must post-date the block deterministically.
        deadline = time.time() + 10
        while rig.session._booking_blocked is None \
                and time.time() < deadline:
            time.sleep(0.05)
        assert rig.session._booking_blocked is not None, \
            "foreign fill never blocked booking"
        stamp["blocked"] = time.time()
        gates[0].set()

    orch = threading.Thread(target=orchestrate, daemon=True)
    orch.start()
    try:
        report = rig.session.run_live(rig.events(), duration_s=8,
                                      expect_class=CLASS)
        orch.join(timeout=10)
        assert not orch.is_alive(), "orchestrator stuck"
        rig.close_streams()
        rig.transport.assert_empty()
        assert report["intents_admitted"] == 0, report["reject_counts"]
        assert report["reject_counts"].get(
            "booking:unknown-fill:FOREIGN-1", 0) >= 1, report[
                "reject_counts"]
        assert rig.session._booking_blocked == \
            "unknown-fill:FOREIGN-1"
        kinds = checkpoint_kinds(rig.store, rig.run_id)
        assert "fill-unbooked" in kinds, kinds
        assert "booking-rejected" not in kinds, kinds
        # No booked rows (the empty file itself is pre-created).
        assert [ln for ln in
                (rig.workdir / "fills.jsonl").read_text().splitlines()
                if ln.strip()] == []
        assert not [r for r in rig.transport.requests
                    if r[0] == "POST" and r[1] in (
                        "/fapi/v1/order", "/fapi/v1/algoOrder")]
        assert report["open_position"] is False
        assert rig.session.ledger.position_qty() == 0.0
    finally:
        rig.close()


def test_row12_emergency_flatten(tmp_path, monkeypatch, fixtures):
    """Row 12: an emergency latch cancels, flattens, alerts, recovers.

    The latch input is white-box (the latch MATH is policy-unit
    territory, and no market path in the matrix config can move a
    risk-sized position 1% of equity); everything after the latch —
    halt, cancel, reduce, alert, adopt, recover — runs the real loop.
    No time exit: the emergency is the only exit driver.
    """
    ready, orders, account = fixtures
    script = ready_prefix(ready) + attach_prefix(orders)
    rig = Rig(tmp_path, monkeypatch, ready, orders, account, script,
              shots=1, run_id="matrix-r12", time_exit_s=600,
              tail=SUBMIT_TAIL)
    rig.transport._hook = auto_fill_hook(rig)
    rig.attach()
    stamp = {}

    def orchestrate():
        wait_for_fills(rig.workdir, 1)
        time.sleep(1.0)
        rig.session.policy._state.emergency_latched = True
        stamp["poked"] = time.time()

    orch = threading.Thread(target=orchestrate, daemon=True)
    orch.start()
    try:
        report = rig.session.run_live(rig.events(), duration_s=14,
                                      expect_class=CLASS)
        orch.join(timeout=10)
        assert not orch.is_alive(), "orchestrator stuck"
        assert stamp.get("poked"), "latch never poked"
        rig.close_streams()
        rig.transport.assert_empty()
        assert report["intents_admitted"] == 1, report["reject_counts"]
        assert report["open_position"] is False
        assert rig.session.ledger.position_qty() == 0.0
        assert_order_posts(rig.transport, [("LIMIT", "BUY"),
                                           ("MARKET", "SELL")])
        rows = [json.loads(line) for line in
                (rig.workdir / "fills.jsonl").read_text().splitlines()
                if line.strip()]
        assert len(rows) == 2, [r["client_order_id"] for r in rows]
        kinds = checkpoint_kinds(rig.store, rig.run_id)
        assert "flatten" in kinds, kinds
        flattens = [json.loads(p) for k, p in rig.store._db.execute(
            "SELECT kind, payload FROM checkpoints WHERE run_id=?",
            (rig.run_id,)).fetchall() if k == "flatten"]
        assert any(f.get("reason") == "stop-action" for f in flattens), \
            flattens
        alerts = [json.loads(line) for line in
                  (rig.workdir / "risk.jsonl").read_text().splitlines()
                  if line.strip()]
        assert any(a.get("kind") == "operator-alert" and a.get(
            "reason") == "halt:emergency:exposure-reduction"
            for a in alerts), alerts
        # Reconciled flat clears the latch and lifts exit-only.
        assert rig.session.policy._state.emergency_latched is False
        assert "halt:emergency" not in rig.session._exit_only_reasons
        assert_leg_coverage(rig.transport)
        assert_reconciled_clean(rig.session, rig.store, rig.run_id)
    finally:
        rig.close()


def test_row11_operator_stop(tmp_path, monkeypatch, fixtures):
    """Row 11: operator stop flattens promptly; resume adopts the close.

    Phase A: with position 1 open, an operator handle (its own
    RunStore, the real CLI path) requests flatten-stop: the loop
    submits the close and exits promptly with the flag sticky. The
    close fill lands post-shutdown (threaded drain stops on the
    exit tick), so the ledger honestly reports open.
    Phase B: after the explicit clear_stop, resume recovers via
    lookup — the close adopts and books, the entry is NOT
    double-booked (exec gate), nothing re-submits, flat. The run
    serves its full duration (no re-stop).
    """
    ready, orders, account = fixtures
    db_path = tmp_path / "runs" / "cryptobot.db"
    script_a = ready_prefix(ready) + attach_prefix(orders)
    rig_a = Rig(tmp_path, monkeypatch, ready, orders, account,
                script_a, shots=1, run_id="matrix-r11",
                time_exit_s=600, tail=SUBMIT_TAIL)
    rig_a.transport._hook = auto_fill_hook(rig_a)
    rig_a.attach()
    stamp = {}

    def stopper():
        wait_for_fills(rig_a.workdir, 1)
        time.sleep(2.0)
        own = RunStore(db_path)
        try:
            own.request_stop("matrix-r11", "flatten")
        finally:
            own.close()
        stamp["stopped_at"] = time.time()

    stop = threading.Thread(target=stopper, daemon=True)
    stop.start()
    try:
        t0 = time.time()
        report_a = rig_a.session.run_live(
            rig_a.events(), duration_s=20, expect_class=CLASS)
        stamp["elapsed_a"] = time.time() - t0
        stop.join(timeout=10)
        assert not stop.is_alive(), "stopper stuck"
        rig_a.close_streams()
        rig_a.transport.assert_empty()
        assert report_a["intents_admitted"] == 1, report_a[
            "reject_counts"]
        posts_a = assert_order_posts(
            rig_a.transport, [("LIMIT", "BUY"), ("MARKET", "SELL")])
        # Prompt exit: far short of the 20s budget.
        assert stamp["elapsed_a"] < 12, stamp
        # Sticky flag: resume would re-stop without clear_stop.
        assert rig_a.store.stop_requested("matrix-r11") == "flatten"
        assert "flatten" in checkpoint_kinds(rig_a.store, "matrix-r11")
        rows_a = [json.loads(line) for line in
                  (rig_a.workdir / "fills.jsonl").read_text().splitlines()
                  if line.strip()]
        assert len(rows_a) == 1 and rows_a[0]["side"] == "BUY", rows_a
        assert report_a["open_position"] is True
        assert rig_a.session.ledger.position_qty() > 0.0
        close_cid = posts_a[1][2]["newClientOrderId"]
        close_side = posts_a[1][2].get("side", "SELL")
        [close_fill] = rig_a.transport._tape[close_cid]
        close_cmds = [c for c in rig_a.store.open_commands("matrix-r11")
                      if c.get("engine_client_id") == close_cid]
        assert len(close_cmds) == 1
        assert close_cmds[0]["status"] == "submitted", close_cmds[0]
    finally:
        rig_a.close()

    # Phase B: brand-new objects on the same durable paths. Venue
    # truth (the close fill) persists across the restart.
    rig_b = Rig(tmp_path, monkeypatch, ready, orders, account,
                ready_nokey(ready) + [
                    reads_block(("GET", "/fapi/v1/order"),
                                ("GET", "/fapi/v1/userTrades"),
                                ("GET", "/fapi/v1/algoOrder")),
                    ("POST", "/fapi/v1/listenKey", None,
                     ("ok", {"listenKey": "K2"})),
                ],
                shots=0, run_id="matrix-r11", tail=SUBMIT_TAIL)
    rig_b.transport._hook = auto_fill_hook(rig_b)
    rig_b.transport.note_stream_fill(
        close_cid, close_fill["trade_id"], close_fill["qty"],
        close_fill["price"], close_fill["fee"], close_side)
    rig_b.attach()
    rig_b.store.clear_stop("matrix-r11")
    try:
        t0 = time.time()
        report_b = rig_b.session.run_live(
            rig_b.events(), duration_s=8, expect_class=CLASS,
            resume=True)
        stamp["elapsed_b"] = time.time() - t0
        rig_b.close_streams()
        rig_b.transport.assert_empty()
        assert report_b["intents_admitted"] == 0, report_b[
            "reject_counts"]
        # Full duration served: the clear held, no re-stop.
        assert stamp["elapsed_b"] > 6, stamp
        assert report_b["open_position"] is False
        assert rig_b.session.ledger.position_qty() == 0.0
        # Nothing re-submitted on resume.
        assert order_posts(rig_b.transport) == []
        rows_b = [json.loads(line) for line in
                  (rig_b.workdir / "fills.jsonl").read_text().splitlines()
                  if line.strip()]
        # Entry once (exec gate: recover did NOT double-book it) +
        # the adopted close.
        assert len(rows_b) == 2, rows_b
        assert rows_b[0]["side"] == "BUY"
        assert rows_b[1]["side"] == "SELL"
        assert rows_b[1]["client_order_id"] == close_cid
        kinds_b = checkpoint_kinds(rig_b.store, "matrix-r11")
        assert "live-resume" in kinds_b, kinds_b
        assert "resume-blocked" not in kinds_b, kinds_b
        assert rig_b.session._reconciled is True
        assert_reconciled_clean(rig_b.session, rig_b.store,
                                rig_b.run_id)
    finally:
        rig_b.close()


def test_row09_stale_data(tmp_path, monkeypatch, fixtures):
    """Row 9: 60s-stale marks admit nothing, submit nothing, end clean."""
    ready, orders, account = fixtures
    script = ready_prefix(ready)
    rig = Rig(tmp_path, monkeypatch, ready, orders, account, script,
              shots=1, time_exit_s=600, tail=READ_TAIL)
    rig.attach()
    try:
        report = rig.session.run_live(stale_events(), duration_s=6,
                                      expect_class=CLASS)
        rig.close_streams()
        rig.transport.assert_empty()
        assert report["intents_admitted"] == 0, report["reject_counts"]
        assert any("stale" in reason
                   for reason in report["reject_counts"]), report[
                       "reject_counts"]
        assert not [r for r in rig.transport.requests
                    if r[0] == "POST" and r[1] in (
                        "/fapi/v1/order", "/fapi/v1/algoOrder")]
        assert report["open_position"] is False
        assert rig.session.ledger.position_qty() == 0.0
        assert_reconciled_clean(rig.session, rig.store, rig.run_id)
    finally:
        rig.close()
