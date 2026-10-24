"""Shared injected-venue fixtures (Binance USD-M flavor).

Import path for the joint W1/W2 Checkpoint-A proof::

    import venue_fixtures as venues  # tests/ is on sys.path (conftest)

Pattern: build a scripted ``ReplayTransport`` (method/path/params match +
``("ok", payload)`` / ``("err", status, code, msg)``), construct the live
engine with ``_live`` (prefix ``_ready_script`` for the readiness
handshake), drive submits/lookups/stream notes, then
``transport.assert_empty()`` to prove the exact REST dialogue.
"""
import copy
import json
import sys
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cryptobot.adapters.binance_live import (  # noqa: E402
    BinanceLiveEngine,
    VenueHttpError,
)

T0MS = 1728720000000
NOW = datetime.fromtimestamp(T0MS / 1000, tz=UTC)
FIX = Path(__file__).resolve().parent / "fixtures" / "binance_live"


class ReplayTransport:
    """Scripted transport: exact REST dialogue, no network."""

    def __init__(self, script):
        self.script = deque(script)
        self.requests = []

    def append(self, *expectations):
        self.script.extend(expectations)

    def request(self, method, path, params, headers):
        assert self.script, f"unexpected request {method} {path}"
        exp = self.script.popleft()
        assert (method, path) == (exp[0], exp[1]), (method, path, exp)
        for key, value in (exp[2] or {}).items():
            assert params.get(key) == value, (key, params.get(key), value)
        self.requests.append((method, path, dict(params), dict(headers)))
        kind, *rest = exp[3]
        if kind == "ok":
            return copy.deepcopy(rest[0])
        raise VenueHttpError(rest[0], rest[1], rest[2])

    def assert_empty(self):
        assert not self.script, [s[:2] for s in self.script]


def ready_fixture():
    return json.loads((FIX / "readiness.json").read_text())


def orders_fixture():
    return json.loads((FIX / "orders.json").read_text())


def ready_script(ready):
    """Readiness handshake: time + filters + commission + account + leverage."""
    return [
        ("GET", "/fapi/v1/time", None, ("ok", ready["time"])),
        ("GET", "/fapi/v1/exchangeInfo", None, ("ok", ready["exchangeInfo"])),
        ("GET", "/fapi/v1/commissionRate", {"symbol": "BTCUSDT"},
         ("ok", ready["commissionRate"])),
        ("GET", "/fapi/v2/account", None, ("ok", ready["account"])),
        ("POST", "/fapi/v1/leverage", {"symbol": "BTCUSDT", "leverage": 3},
         ("ok", ready["leverage"])),
    ]


def make_engine(tmp_path, script, **kw):
    """Live engine wired to a ReplayTransport (offline, deterministic)."""
    transport = ReplayTransport(script)
    kw.setdefault("now_utc", lambda: NOW)
    engine = BinanceLiveEngine(
        api_key="TESTKEY", api_secret="TESTSECRET",
        journal_path=tmp_path / "live.jsonl", expected_leverage=3,
        run_tag="bl", live_enable=True, transport=transport, **kw)
    return engine, transport


class FakeSocket:
    """Scripted stream socket; None = timeout; 'die' kills (REV2 drill)."""

    def __init__(self, script=()):
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


def drill_account(ready):
    """Account fixture with the wallet leg a complete snapshot needs."""
    view = copy.deepcopy(ready["account"])
    view.setdefault("totalWalletBalance", "10000.00")
    return view


def wall_time():
    """Wall serverTime entry (the skew gate needs a live clock)."""
    import time
    return ("GET", "/fapi/v1/time", None,
            ("ok", {"serverTime": int(time.time() * 1000)}))


class _SyncHookTransport:
    """ReplayTransport + synchronous per-POST stream hook (deterministic).

    Fills queue to the live socket on the CALLING thread right after
    the venue ack — no watcher thread, so the stream/drain interleave
    is fixed and the strict script is stable. Delegates requests,
    append, and assert_empty to the inner replay transport.
    """

    def __init__(self, inner, hook):
        self._inner = inner
        self._hook = hook

    def request(self, method, path, params, headers):
        resp = self._inner.request(method, path, params, headers)
        if method == "POST" and path in ("/fapi/v1/order",
                                         "/fapi/v1/algoOrder"):
            self._hook(method, path, dict(params))
        return resp

    @property
    def requests(self):
        return self._inner.requests

    @property
    def script(self):
        return self._inner.script

    def append(self, *expectations):
        self._inner.append(*expectations)

    def assert_empty(self):
        self._inner.assert_empty()


def patch_drill_offline(monkeypatch, drill, transport, orders, *,
                        mark=100.0, on_post=None, fail_redial=False):
    """Wire a demo Drill fully offline (REV2 R4 rig).

    Shared scripted transport for every phase engine, fresh sockets
    per dial, wall clock quote, shrunk bounds. Each venue POST queues
    stream envelopes SYNCHRONOUSLY per on_post(kind, params, append,
    trade) — kind is 'order'/'algo', append(envelope) queues to the
    live socket, trade is a fresh userStreamTrade copy. Default: full
    fills, distinct trade ids. fail_redial drops the first redial per
    attachment (gap window). Returns rig handles (no threads).
    """
    import time

    engines = []
    hooked = _SyncHookTransport(transport, lambda m, p, pr: _hooked(
        m, p, pr))

    def _engine(transport_override=None, **kw):
        inner = kw.get("transport", transport_override) or hooked
        eng = BinanceLiveEngine(
            api_key="k", api_secret="s",
            journal_path=drill.journal_path, expected_leverage=3,
            run_tag="demo30", live_enable=True, demo=True,
            base_url=None, transport=inner,
            now_utc=lambda: datetime.now(UTC))
        engines.append(eng)
        return eng

    monkeypatch.setattr(drill, "engine", _engine)
    monkeypatch.setattr(drill, "live_quote",
                        lambda: (mark, int(time.time() * 1000)))
    drill.poll_s = 0.001
    drill.heal_wait_s = 5.0
    drill.fill_wait_s = 5.0
    drill.flat_wait_s = 5.0
    drill.gap_wait_s = 5.0
    drill.stream_kwargs = {"start_thread": False,
                           "initial_backoff_s": 0.01}
    current = {}
    dials = [0]

    def _ws_factory(engine):
        per_attach = [0]

        def _factory(key):
            dials[0] += 1
            per_attach[0] += 1
            if fail_redial and per_attach[0] == 2:
                raise ConnectionError("dial refused")
            current["sock"] = FakeSocket([])
            return current["sock"]
        return _factory

    monkeypatch.setattr(drill, "ws_factory", _ws_factory)
    if on_post is None:
        def on_post(kind, params, append, trade):
            if kind == "order":
                trade["o"]["c"] = params.get("newClientOrderId")
                trade["o"]["S"] = params.get("side", "BUY")
                qty = params.get("quantity")
                trade["o"]["l"] = trade["o"]["z"] = qty
                trade["o"]["L"] = trade["o"]["ap"] = f"{mark:.2f}"
                append(trade)

    trade_seq = [777001]

    def _hooked(method, path, params):
        if "sock" not in current:
            return
        trade = copy.deepcopy(orders["userStreamTrade"])
        trade["o"]["t"] = trade_seq[0]
        trade_seq[0] += 1
        on_post("order" if path == "/fapi/v1/order" else "algo", params,
                current["sock"].script.append, trade)

    def _stop():
        pass

    return {"stop": _stop, "engines": engines, "dials": dials,
            "current": current, "transport": hooked}
