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
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cryptobot.adapters.binance_live import (  # noqa: E402
    BinanceLiveEngine,
    VenueHttpError,
)

T0MS = 1728720000000
NOW = datetime.fromtimestamp(T0MS / 1000, tz=timezone.utc)
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
