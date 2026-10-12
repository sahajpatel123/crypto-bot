"""Review-2 defect 6: unknown-outcome block lost on restart (W5-24H).

A recorded 503 journals an UNKNOWN entry. Recovery retains its unknown
ID but does not rebuild the reservation mapping: _unknown_for(r1) is
empty and another entry with r1 is accepted. Fills also re-adopt on
replay because _trades_booked is not rebuilt from the journal.

Required: rebuild reservation, role, symbol, order/client identity,
booked fills and terminal/unknown state before reconciliation. Block
all relevant new exposure until unknown state is resolved; replay
fills idempotently.

Fails on base 3cadfca (bug reproduced); passes once fixed.
Strict-xfail marked in tests/audit/conftest.py while open.
"""
import copy
import json
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from cryptobot.adapters.binance_live import (
    BinanceLiveEngine,
    UnknownOutcomeError,
    VenueHttpError,
)
from cryptobot.app.engine import EngineOrder

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "binance_live"
T0MS = 1728720000000
NOW = datetime.fromtimestamp(T0MS / 1000, tz=timezone.utc)


class _Script:
    def __init__(self, steps):
        self.steps = deque(steps)
        self.requests = []

    def append(self, *steps):
        self.steps.extend(steps)

    def request(self, method, path, params, headers):
        assert self.steps, f"unexpected request {method} {path}"
        exp = self.steps.popleft()
        assert (method, path) == (exp[0], exp[1]), (method, path, exp)
        self.requests.append((method, path))
        kind, *rest = exp[2]
        if kind == "ok":
            return copy.deepcopy(rest[0])
        raise VenueHttpError(rest[0], rest[1], rest[2])


def _fixtures():
    return json.loads((FIX / "readiness.json").read_text())


def _ready_steps(ready):
    return [
        ("GET", "/fapi/v1/time", ("ok", ready["time"])),
        ("GET", "/fapi/v1/exchangeInfo", ("ok", ready["exchangeInfo"])),
        ("GET", "/fapi/v1/commissionRate", ("ok", ready["commissionRate"])),
        ("GET", "/fapi/v2/account", ("ok", ready["account"])),
        ("POST", "/fapi/v1/leverage", ("ok", ready["leverage"])),
    ]


def _engine(tmp_path, transport):
    return BinanceLiveEngine(
        api_key="TESTKEY", api_secret="TESTSECRET",
        journal_path=tmp_path / "live.jsonl", expected_leverage=3,
        run_tag="w5d6", live_enable=True, transport=transport,
        now_utc=lambda: NOW)


def _journal(tmp_path):
    return [json.loads(line) for line in
            (tmp_path / "live.jsonl").read_text().splitlines()]


def _submit_503_journaled(tmp_path):
    """Instance 1: entry submit hits HTTP 503 -> UNKNOWN journaled."""
    ready = _fixtures()
    transport = _Script(_ready_steps(ready) + [
        ("POST", "/fapi/v1/order", ("err", 503, -1001, "Service Unavailable")),
    ])
    engine = _engine(tmp_path, transport)
    with pytest.raises(UnknownOutcomeError) as excinfo:
        engine.submit(EngineOrder("BTCUSDT", "BUY", 0.0019, "MARKET",
                                  reservation_id="r1", role="entry"))
    cid = excinfo.value.client_id
    events = [r.get("event") for r in _journal(tmp_path)]
    assert "submit-outcome-unknown" in events, f"setup broken: {events}"
    return cid


def test_recovery_rebuilds_unknown_block(tmp_path):
    """After restart, r1 must stay blocked until lookup resolves UNKNOWN."""
    cid = _submit_503_journaled(tmp_path)
    ready = _fixtures()
    order_ack = json.loads((FIX / "orders.json").read_text())["orderAck"]
    # recover() -> lookup() needs no readiness; the trailing script lets a
    # pre-fix second submit run to acceptance (proving the missing block).
    transport2 = _Script(
        [("GET", "/fapi/v1/order", ("err", 503, -1001, "still unknown"))]
        + _ready_steps(ready)
        + [("POST", "/fapi/v1/order", ("ok", order_ack))])
    engine2 = _engine(tmp_path, transport2)
    engine2.recover(outcome_sink=None)
    assert engine2._unknown_for("r1") == [cid], (
        f"recovery dropped the reservation mapping: _unknown_for(r1)="
        f"{engine2._unknown_for('r1')}, journal keeps UNKNOWN {cid}")
    with pytest.raises(UnknownOutcomeError):
        cid2 = engine2.submit(EngineOrder("BTCUSDT", "BUY", 0.0019, "MARKET",
                                          reservation_id="r1", role="entry"))
        pytest.fail(f"entry {cid2} accepted while {cid} is UNKNOWN")


def test_recovery_replays_fills_idempotently(tmp_path):
    """A journaled fill must not double-adopt when recovery replays tape."""
    ready = _fixtures()
    tape = [{"id": 555, "qty": "0.5", "price": "60000",
             "commission": "0.03", "commissionAsset": "USDT"}]
    query = {"status": "FILLED", "orderId": 4242, "executedQty": "0.5"}
    t1 = _Script(_ready_steps(ready) + [
        ("POST", "/fapi/v1/order",
         ("ok", {"status": "NEW", "orderId": 4242})),
        ("GET", "/fapi/v1/order", ("ok", query)),
        ("GET", "/fapi/v1/userTrades", ("ok", tape)),
    ])
    eng1 = _engine(tmp_path, t1)
    cid = eng1.submit(EngineOrder("BTCUSDT", "BUY", 0.0019, "MARKET",
                                  reservation_id="r9", role="entry"))
    eng1.lookup(cid)
    assert eng1.filled_qty(cid) == 0.5, "setup broken: fill not adopted"
    # recover() -> lookup() needs no readiness: order view + tape only.
    t2 = _Script([
        ("GET", "/fapi/v1/order", ("ok", query)),
        ("GET", "/fapi/v1/userTrades", ("ok", tape)),
    ])
    eng2 = _engine(tmp_path, t2)
    eng2.recover(outcome_sink=None)
    assert eng2.filled_qty(cid) == 0.5, (
        f"recovery double-adopted trade 555: filled={eng2.filled_qty(cid)}")
