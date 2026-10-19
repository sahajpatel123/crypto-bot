"""READY §7: demo-drill kill criteria (credential-free, fully stubbed).

No network, no keys. The stub engine/quote stand in for the venue;
every kill path must FAIL + abort with no further phases.
"""
import copy
import sys
import time
from pathlib import Path

import pytest

import venue_fixtures as venues

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "audit"))
import demo_drill  # noqa: E402


def _rigged(drill, monkeypatch, script, orders, **kw):
    """Session-path rig (REV2): shared strict script + sync stream hook."""
    transport = venues.ReplayTransport(script)
    rig = venues.patch_drill_offline(monkeypatch, drill, transport, orders,
                                     **kw)
    return transport, rig


class _Status:
    def __init__(self, state):
        self.state = state


class FakeEngine:
    def __init__(self, mark=100.0, stop_state="open", out_mult=1.0,
                 unknowns=(), entry_state="filled", entry_fill=None):
        self._filters = {"BTCUSDT": {"step": 0.001, "min_notional": 5.0}}
        self._mark = mark
        self._stop_state = stop_state
        self._out_mult = out_mult
        self._unknowns = list(unknowns)
        self._entry_state = entry_state
        self._entry_fill = entry_fill
        self._transport = self
        self.submitted = []
        self.cancelled = []
        self._cids = 0

    # -- engine surface used by the drill --
    def _ensure_ready(self, symbol):
        pass

    def request(self, method, path, params, headers):
        return {"serverTime": int(time.time() * 1000)}

    def submit(self, order):
        self._cids += 1
        cid = f"stub-{self._cids}"
        self.submitted.append((cid, order))
        return cid

    def lookup(self, cid):
        for sid, order in self.submitted:
            if sid == cid:
                if getattr(order, "role", "") == "stop":
                    return _Status(self._stop_state)
                return _Status(self._entry_state)
        return _Status("cancelled")

    def filled_qty(self, cid):
        for sid, order in self.submitted:
            if sid == cid:
                if getattr(order, "role", "") == "target":
                    return round(order.qty * self._out_mult, 8)
                if self._entry_fill is not None:
                    return self._entry_fill
                return order.qty if self._entry_state == "filled" else 0.0
        return 0.0

    def unknown_ids(self):
        return list(self._unknowns)

    def cancel(self, cid, reason):
        self.cancelled.append(cid)

    def _read_journal(self):
        return []

    def open_orders(self):
        return []


@pytest.fixture
def drill(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    d = demo_drill.Drill(str(tmp_path / "drill"), "BTCUSDT", None)
    monkeypatch.setattr(d, "live_quote",
                        lambda: (100.0, int(time.time() * 1000)))
    return d


@pytest.fixture
def creds(monkeypatch):
    monkeypatch.setenv("BINANCE_DEMO_KEY", "k")
    monkeypatch.setenv("BINANCE_DEMO_SECRET", "s")


def _phases(drill):
    return [ln for ln in
            drill.evidence_path.read_text().splitlines() if ln]


def test_no_creds_blocked(drill, monkeypatch):
    monkeypatch.delenv("BINANCE_DEMO_KEY", raising=False)
    monkeypatch.delenv("BINANCE_DEMO_SECRET", raising=False)
    assert demo_drill.cmd_drill(drill) == 2
    assert demo_drill.cmd_preflight(drill) == 2


def test_non_demo_host_refused(drill, creds):
    drill.base_url = "https://fapi.binance.com"
    assert demo_drill.cmd_drill(drill) == 2


def test_stale_quote_kills_drill(drill, creds, monkeypatch):
    monkeypatch.setattr(drill, "live_quote",
                        lambda: (100.0, int(time.time() * 1000) - 60000))
    assert demo_drill.cmd_drill(drill) == 1
    assert "drill/quote-fresh" in _phases(drill)[-1]
    assert "KILL" in _phases(drill)[-1]


def test_unknown_quote_time_fails_closed(drill, creds, monkeypatch):
    monkeypatch.setattr(drill, "live_quote", lambda: (100.0, None))
    assert demo_drill.cmd_drill(drill) == 1


def test_exposure_cap_breach_kills(drill, creds, monkeypatch):
    eng = FakeEngine()
    eng._filters["BTCUSDT"]["min_notional"] = 100000.0
    monkeypatch.setattr(drill, "engine", lambda transport=None: eng)
    assert demo_drill.cmd_drill(drill) == 1
    assert eng.submitted == []


def test_unknowns_at_gate_kill(drill, creds, monkeypatch):
    eng = FakeEngine(unknowns=["abc"])
    monkeypatch.setattr(drill, "engine", lambda transport=None: eng)
    assert demo_drill.cmd_drill(drill) == 1
    assert eng.submitted == []


def test_protection_miss_aborts_before_later_phases(drill, creds,
                                                    monkeypatch):
    from test_rev2_demo_drill import (_algo_cancelled, _algo_working,
                                      _cancelled, _listen_close,
                                      _listen_open, _ready)
    ready, orders = venues.ready_fixture(), venues.orders_fixture()
    acct = venues.drill_account(ready)
    script = _ready(acct) + [
        _listen_open(),
        ("GET", "/fapi/v2/account", None, ("ok", acct)),
        ("GET", "/fapi/v1/openOrders", None, ("ok", [])),
        ("GET", "/fapi/v1/openAlgoOrders", None, ("ok", [])),
        ("GET", "/fapi/v2/account", None, ("ok", acct)),
        ("POST", "/fapi/v1/order", {"type": "LIMIT"},
         ("ok", orders["orderAck"])),
        # Legs never cover (venue-side attach failure, raised before
        # any lookup/POST); the drill's emergency close flattens the
        # naked exposure.
        ("POST", "/fapi/v1/order", {"type": "MARKET"},
         ("ok", orders["orderAck"])),
        _listen_close(),
    ]
    from cryptobot.adapters.binance_live import BinanceLiveEngine

    def _no_legs(self, entry_client_id, stop_price, target_price=None):
        raise ValueError("venue rejected legs")

    monkeypatch.setattr(BinanceLiveEngine, "attach_protection", _no_legs)
    transport, rig = _rigged(drill, monkeypatch, script, orders)
    drill.flat_wait_s = 0.5
    try:
        assert demo_drill.cmd_drill(drill) == 1
    finally:
        rig["stop"]()
    transport.assert_empty()
    phases = "\n".join(_phases(drill))
    assert "drill/protection" in phases and "KILL" in phases
    assert "ambiguous-submit" not in phases
    assert "restart-adopt" not in phases


def test_exit_mismatch_aborts(drill, creds, monkeypatch):
    """Session path: the exit half-fills => KILL (emergency completes)."""
    from test_rev2_demo_drill import (_algo_cancelled, _algo_working,
                                      _cancelled, _listen_close,
                                      _listen_open, _ready)
    ready, orders = venues.ready_fixture(), venues.orders_fixture()
    acct = venues.drill_account(ready)
    script = _ready(acct) + [
        _listen_open(),
        ("GET", "/fapi/v2/account", None, ("ok", acct)),
        ("GET", "/fapi/v1/openOrders", None, ("ok", [])),
        ("GET", "/fapi/v1/openAlgoOrders", None, ("ok", [])),
        ("GET", "/fapi/v2/account", None, ("ok", acct)),
        ("POST", "/fapi/v1/order", {"type": "LIMIT"},
         ("ok", orders["orderAck"])),
        ("GET", "/fapi/v1/order", None, ("ok", _cancelled())),
        ("POST", "/fapi/v1/algoOrder", {"type": "STOP_MARKET"},
         ("ok", _algo_working(101))),
        ("POST", "/fapi/v1/algoOrder", {"type": "TAKE_PROFIT_MARKET"},
         ("ok", _algo_working(102))),
        ("DELETE", "/fapi/v1/algoOrder", None,
         ("ok", _algo_cancelled())),
        ("DELETE", "/fapi/v1/algoOrder", None,
         ("ok", _algo_cancelled())),
        ("POST", "/fapi/v1/order", {"type": "MARKET"},
         ("ok", orders["orderAck"])),
        ("POST", "/fapi/v1/order", {"type": "MARKET"},
         ("ok", orders["orderAck"])),
        _listen_close(),
    ]
    closes = []

    def _on_post(kind, params, append, trade):
        if kind != "order":
            return
        trade["o"]["c"] = params.get("newClientOrderId")
        trade["o"]["S"] = params.get("side", "BUY")
        qty = float(params.get("quantity"))
        if params.get("side") == "SELL" and not closes:
            # First close half-fills: exit mismatch.
            closes.append(qty)
            trade["o"]["l"] = trade["o"]["z"] = f"{qty / 2:.8f}"
        else:
            trade["o"]["l"] = trade["o"]["z"] = params.get("quantity")
        trade["o"]["L"] = trade["o"]["ap"] = "100.00"
        append(trade)

    transport, rig = _rigged(drill, monkeypatch, script, orders,
                             on_post=_on_post)
    drill.flat_wait_s = 0.5
    try:
        assert demo_drill.cmd_drill(drill) == 1
    finally:
        rig["stop"]()
    transport.assert_empty()
    phases = "\n".join(_phases(drill))
    assert "reduce-only-exit" in phases and "KILL" in phases
    assert "ambiguous-submit" not in phases


def test_honest_no_trade_blocks_protection(drill, creds, monkeypatch):
    """Session path: IOC cancels with no fill => BLOCKED, no KILL, rc 0."""
    from test_rev2_demo_drill import (_cancelled, _listen_close,
                                      _listen_open, _ready)
    ready, orders = venues.ready_fixture(), venues.orders_fixture()
    acct = venues.drill_account(ready)
    script = _ready(acct) + [
        _listen_open(),
        ("GET", "/fapi/v2/account", None, ("ok", acct)),
        ("GET", "/fapi/v1/openOrders", None, ("ok", [])),
        ("GET", "/fapi/v1/openAlgoOrders", None, ("ok", [])),
        ("GET", "/fapi/v2/account", None, ("ok", acct)),
        ("POST", "/fapi/v1/order", {"type": "LIMIT"},
         ("ok", orders["orderAck"])),
        # _tiny_qty re-fetches account for balance sizing before the
        # ambiguous-submit engine's own readiness sequence.
        ("GET", "/fapi/v2/account", None, ("ok", acct)),
    ] + _ready(acct) + [
        ("POST", "/fapi/v1/order", {"type": "LIMIT"},
         ("ok", orders["orderAck"])),
        ("GET", "/fapi/v1/order", None, ("ok", _cancelled())),
        ("GET", "/fapi/v1/openOrders", None, ("ok", [])),
        ("GET", "/fapi/v1/openAlgoOrders", None, ("ok", [])),
        _listen_close(),
    ]
    seen = []

    def _on_post(kind, params, append, trade):
        if kind != "order":
            return
        seen.append(params.get("newClientOrderId"))
        if len(seen) == 1:
            # The entry IOC-cancels with zero fill: honest no-trade.
            trade["o"]["c"] = params.get("newClientOrderId")
            trade["o"]["S"] = params.get("side", "BUY")
            trade["o"]["x"] = trade["o"]["X"] = "CANCELED"
            trade["o"]["l"] = trade["o"]["z"] = "0"
            trade["o"]["L"] = trade["o"]["ap"] = "100.00"
            append(trade)
        else:
            trade["o"]["c"] = params.get("newClientOrderId")
            trade["o"]["S"] = params.get("side", "BUY")
            qty = params.get("quantity")
            trade["o"]["l"] = trade["o"]["z"] = qty
            trade["o"]["L"] = trade["o"]["ap"] = "100.00"
            append(trade)

    transport, rig = _rigged(drill, monkeypatch, script, orders,
                             on_post=_on_post)
    try:
        assert demo_drill.cmd_drill(drill) == 0
    finally:
        rig["stop"]()
    transport.assert_empty()
    phases = "\n".join(_phases(drill))
    assert "protection-exit" in phases
    assert "KILL" not in phases
    assert "ambiguous-submit" in phases
    assert [r for r in transport.requests
            if r[1] == "/fapi/v1/algoOrder"] == []
