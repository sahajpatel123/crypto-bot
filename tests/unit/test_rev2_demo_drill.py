"""REV2 R4: demo-drill truthfulness regressions (Worker 2).

Offline (injected transport + sockets, no network/keys): the exact
documented `full` command returns BLOCKED without keys, never reaches
entry after preflight failure, cannot pass with an omitted leg, and
reports flat only after venue positions, orders, journal, and ledger
agree. A full offline run passes every phase through the normal
Session (entry → protection → exit, stream gap, restart adoption,
authoritative reconcile).
"""
import contextlib
import copy
import hashlib
import io
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "audit"))
import demo_drill  # noqa: E402

import venue_fixtures as venues  # noqa: E402
from cryptobot.accounting.ledger import Ledger  # noqa: E402
from cryptobot.app.store import RunStore  # noqa: E402


def _now_ms():
    return int(time.time() * 1000)


def _ready(acct):
    ready = venues.ready_fixture()
    return [venues.wall_time(),
            ("GET", "/fapi/v1/exchangeInfo", None,
             ("ok", ready["exchangeInfo"])),
            ("GET", "/fapi/v1/commissionRate", {"symbol": "BTCUSDT"},
             ("ok", ready["commissionRate"])),
            ("GET", "/fapi/v2/account", None, ("ok", acct)),
            ("POST", "/fapi/v1/leverage",
             {"symbol": "BTCUSDT", "leverage": 3},
             ("ok", ready["leverage"]))]


def _cancelled(qty="0"):
    return {"orderId": 1, "status": "CANCELED", "executedQty": qty,
            "origQty": "0.064"}


def _algo_cancelled():
    return {"algoId": 101, "algoStatus": "CANCELLED", "executedQty": "0",
            "origQty": "0.064"}


def _algo_working(n):
    return {"algoId": n, "algoStatus": "WORKING"}


def _listen_close():
    return ("DELETE", "/fapi/v1/listenKey", None, ("ok", {}))


def _listen_open():
    return ("POST", "/fapi/v1/listenKey", None,
            ("ok", {"listenKey": "K1"}))


class _FakeTime:
    """UrllibTransport stand-in: wall clock, strict no other network."""

    def __init__(self, *a, **k):
        pass

    def request(self, method, path, params, headers):
        assert (method, path) == ("GET", "/fapi/v1/time"), (method, path)
        return {"serverTime": _now_ms()}


def _full_script(tmp_path):
    """Exact 5-phase dialogue (transcribed from the discovery run)."""
    ready = venues.ready_fixture()
    orders = venues.orders_fixture()
    acct = venues.drill_account(ready)
    script = []
    # Preflight: readiness + margin + fees(local) + mark/quote(monkeypatched).
    script += _ready(acct)
    script += [("GET", "/fapi/v2/account", None, ("ok", acct))]
    # Drill: ready, stream, snapshots, entry, legs, churn, close, ambiguous.
    script += _ready(acct)
    script += [_listen_open(),
               ("GET", "/fapi/v2/account", None, ("ok", acct)),
               ("GET", "/fapi/v1/openOrders", None, ("ok", [])),
               ("GET", "/fapi/v1/openAlgoOrders", None, ("ok", [])),
               ("GET", "/fapi/v2/account", None, ("ok", acct)),
               ("POST", "/fapi/v1/order", {"type": "LIMIT"},
                ("ok", orders["orderAck"])),
               ("GET", "/fapi/v1/order", None,
                ("ok", _cancelled())),
               ("POST", "/fapi/v1/algoOrder", {"type": "STOP_MARKET"},
                ("ok", _algo_working(101))),
               ("POST", "/fapi/v1/algoOrder",
                {"type": "TAKE_PROFIT_MARKET"},
                ("ok", _algo_working(102))),
               ("DELETE", "/fapi/v1/algoOrder", None,
                ("ok", _algo_cancelled())),
               ("DELETE", "/fapi/v1/algoOrder", None,
                ("ok", _algo_cancelled())),
               ("GET", "/fapi/v1/order", None,
                ("ok", _cancelled())),
               ("POST", "/fapi/v1/algoOrder", {"type": "STOP_MARKET"},
                ("ok", _algo_working(103))),
               ("POST", "/fapi/v1/algoOrder",
                {"type": "TAKE_PROFIT_MARKET"},
                ("ok", _algo_working(104))),
               ("POST", "/fapi/v1/order", {"type": "MARKET"},
                ("ok", orders["orderAck"])),
               ("DELETE", "/fapi/v1/algoOrder", None,
                ("ok", _algo_cancelled())),
               ("DELETE", "/fapi/v1/algoOrder", None,
                ("ok", _algo_cancelled())),
               ("GET", "/fapi/v2/account", None, ("ok", acct)),
               ("DELETE", "/fapi/v1/algoOrder", None,
                ("ok", _algo_cancelled()))]
    script += _ready(acct)  # ambiguous-submit engine readiness.
    script += [("POST", "/fapi/v1/order", {"type": "LIMIT"},
                ("ok", orders["orderAck"])),
               ("GET", "/fapi/v1/order", None,
                ("ok", _cancelled())),
               ("GET", "/fapi/v1/openOrders", None, ("ok", [])),
               ("GET", "/fapi/v1/openAlgoOrders", None, ("ok", [])),
               _listen_close()]
    # Gap: attach, exit submit, reheal lookup, close.
    script += [_listen_open()]
    script += _ready(acct)
    script += [("POST", "/fapi/v1/order", {"type": "MARKET"},
                ("ok", orders["orderAck"])),
               ("GET", "/fapi/v1/order", None,
                ("ok", _cancelled())),
               _listen_close()]
    # Resume: heal only (all journaled intents terminal — verified, no
    # lookups); close.
    script += [_listen_open(), _listen_close()]
    # Reconcile: snapshot, opens, per-intent venue truth, ledger file.
    script += [("GET", "/fapi/v2/account", None, ("ok", acct)),
               ("GET", "/fapi/v1/openOrders", None, ("ok", [])),
               ("GET", "/fapi/v1/openAlgoOrders", None, ("ok", []))]
    script += [("GET", "/fapi/v1/order", None,
                ("ok", _cancelled()))]
    script += [("GET", "/fapi/v1/algoOrder", None,
                ("ok", _algo_cancelled()))] * 4
    script += [("GET", "/fapi/v1/order", None,
                ("ok", _cancelled()))] * 3
    return script, orders


def test_full_without_keys_returns_blocked(tmp_path):
    """Review probe 1:1 — no keys => BLOCKED (exit 2), never PASS."""
    with patch.dict(os.environ, {"BINANCE_DEMO_KEY": "",
                                 "BINANCE_DEMO_SECRET": ""}), \
         patch("urllib.request.urlopen",
               side_effect=AssertionError("NETWORK FORBIDDEN")), \
         contextlib.redirect_stdout(io.StringIO()):
        code = demo_drill.main(["--dir", str(tmp_path / "demo"), "full"])
    assert code == 2
    logs = [json.loads(s) for s in
            (tmp_path / "demo/drill_evidence.jsonl").read_text().splitlines()]
    assert logs[-1]["phase"] == "full" and logs[-1]["verdict"] == "BLOCKED"
    assert sum(r["verdict"] == "BLOCKED" for r in logs) >= 4
    # No order POST could have happened without credentials.
    assert "entry-ioc" not in "".join(r["phase"] for r in logs)


def test_failed_preflight_prevents_entry(tmp_path):
    """Review probe 1:1 — failed preflight never reaches the entry phase."""
    phases = []

    def phase(name, rc):
        def call(_):
            phases.append(name)
            return rc
        return call

    with patch.object(demo_drill, "cmd_preflight",
                      phase("preflight", 1)), \
         patch.object(demo_drill, "cmd_drill", phase("entry", 0)), \
         patch.object(demo_drill, "cmd_stream_gap", phase("gap", 0)), \
         patch.object(demo_drill, "cmd_reconcile",
                      phase("reconcile", 0)), \
         contextlib.redirect_stdout(io.StringIO()):
        code = demo_drill.main(["--dir", str(tmp_path / "fp"), "full"])
    assert code == 1
    assert "entry" not in phases
    assert phases[0] == "preflight"


def test_full_offline_passes_every_phase(tmp_path, monkeypatch):
    """The exact `full` command passes offline (normal Session, all legs)."""
    monkeypatch.setenv("BINANCE_DEMO_KEY", "k")
    monkeypatch.setenv("BINANCE_DEMO_SECRET", "s")
    monkeypatch.setattr("cryptobot.adapters.binance_live.UrllibTransport",
                        _FakeTime)
    script, orders = _full_script(tmp_path)
    transport = venues.ReplayTransport(script)
    drill = demo_drill.Drill(str(tmp_path / "drill"), "BTCUSDT", None)
    rig = venues.patch_drill_offline(monkeypatch, drill, transport, orders,
                                     fail_redial=True)
    monkeypatch.setattr(demo_drill, "Drill", lambda *a, **k: drill)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            code = demo_drill.main(["--dir", str(tmp_path / "drill"),
                                    "full"])
    finally:
        rig["stop"]()
    assert code == 0
    transport.assert_empty()
    phases = (tmp_path / "drill/drill_evidence.jsonl").read_text()
    for leg in ("drill/entry-ioc", "drill/protection",
                "drill/reduce-only-exit", "drill/ambiguous-submit",
                "stream-gap/reheal", "resume-adopt/durability",
                "reconcile/ledger"):
        assert leg in phases, leg
    assert '"verdict": "FAIL"' not in phases


def test_reconcile_fails_on_venue_position(tmp_path, monkeypatch):
    monkeypatch.setenv("BINANCE_DEMO_KEY", "k")
    monkeypatch.setenv("BINANCE_DEMO_SECRET", "s")
    ready = venues.ready_fixture()
    acct = venues.drill_account(ready)
    acct["positions"] = [{"symbol": "BTCUSDT", "positionAmt": "0.5",
                          "entryPrice": "100.0", "markPrice": "101.0"}]
    transport = venues.ReplayTransport([
        ("GET", "/fapi/v2/account", None, ("ok", acct)),
        ("GET", "/fapi/v1/openOrders", None, ("ok", [])),
        ("GET", "/fapi/v1/openAlgoOrders", None, ("ok", []))])
    drill = demo_drill.Drill(str(tmp_path / "drill"), "BTCUSDT", None)
    rig = venues.patch_drill_offline(monkeypatch, drill, transport,
                                     venues.orders_fixture())
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            assert demo_drill.cmd_reconcile(drill) == 1
    finally:
        rig["stop"]()
    transport.assert_empty()
    phases = (tmp_path / "drill/drill_evidence.jsonl").read_text()
    assert "reconcile/venue-positions" in phases


def test_reconcile_fails_without_ledger(tmp_path, monkeypatch):
    """Flat venue + missing ledger file => FAIL (cannot prove flat)."""
    monkeypatch.setenv("BINANCE_DEMO_KEY", "k")
    monkeypatch.setenv("BINANCE_DEMO_SECRET", "s")
    ready = venues.ready_fixture()
    acct = venues.drill_account(ready)
    transport = venues.ReplayTransport([
        ("GET", "/fapi/v2/account", None, ("ok", acct)),
        ("GET", "/fapi/v1/openOrders", None, ("ok", [])),
        ("GET", "/fapi/v1/openAlgoOrders", None, ("ok", []))])
    drill = demo_drill.Drill(str(tmp_path / "drill"), "BTCUSDT", None)
    rig = venues.patch_drill_offline(monkeypatch, drill, transport,
                                     venues.orders_fixture())
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            assert demo_drill.cmd_reconcile(drill) == 1
    finally:
        rig["stop"]()
    assert "reconcile/ledger" in \
        (tmp_path / "drill/drill_evidence.jsonl").read_text()


def test_reconcile_fails_on_open_orders(tmp_path, monkeypatch):
    """A journaled order still open on the venue => FAIL."""
    monkeypatch.setenv("BINANCE_DEMO_KEY", "k")
    monkeypatch.setenv("BINANCE_DEMO_SECRET", "s")
    ready = venues.ready_fixture()
    acct = venues.drill_account(ready)
    drill = demo_drill.Drill(str(tmp_path / "drill"), "BTCUSDT", None)
    (drill.journal_path).write_text(json.dumps({
        "ts_utc": "2026-10-14T00:00:00+00:00", "event": "submit-intent",
        "client_id": "open-1", "symbol": "BTCUSDT", "side": "BUY",
        "kind": "LIMIT", "qty": 0.010, "role": "entry", "algo": False,
        "reservation_id": "r1"}) + "\n")
    transport = venues.ReplayTransport([
        ("GET", "/fapi/v2/account", None, ("ok", acct)),
        ("GET", "/fapi/v1/openOrders", None, ("ok", [
            {"symbol": "BTCUSDT", "clientOrderId": "open-1",
             "status": "NEW", "origQty": "0.010",
             "executedQty": "0"}])),
        ("GET", "/fapi/v1/openAlgoOrders", None, ("ok", [])),
        ("GET", "/fapi/v1/order", None,
         ("ok", {"orderId": 5, "status": "NEW", "executedQty": "0",
                 "origQty": "0.010"}))])
    rig = venues.patch_drill_offline(monkeypatch, drill, transport,
                                     venues.orders_fixture())
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            assert demo_drill.cmd_reconcile(drill) == 1
    finally:
        rig["stop"]()
    transport.assert_empty()


def test_preflight_clock_skew_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("BINANCE_DEMO_KEY", "k")
    monkeypatch.setenv("BINANCE_DEMO_SECRET", "s")

    class _Skewed(_FakeTime):
        def request(self, method, path, params, headers):
            return {"serverTime": _now_ms() - 60000}

    monkeypatch.setattr("cryptobot.adapters.binance_live.UrllibTransport",
                        _Skewed)
    ready = venues.ready_fixture()
    acct = venues.drill_account(ready)
    transport = venues.ReplayTransport(
        _ready(acct) + [("GET", "/fapi/v2/account", None, ("ok", acct))])
    drill = demo_drill.Drill(str(tmp_path / "drill"), "BTCUSDT", None)
    rig = venues.patch_drill_offline(monkeypatch, drill, transport,
                                     venues.orders_fixture())
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            assert demo_drill.cmd_preflight(drill) == 1
    finally:
        rig["stop"]()
    transport.assert_empty()


def test_resume_adopt_open_exposure_books_closes_flat(tmp_path,
                                                  monkeypatch):
    """Restart with exposure: adopt (deduped), verify legs, close flat."""
    import hashlib
    from datetime import datetime, timezone
    monkeypatch.setenv("BINANCE_DEMO_KEY", "k")
    monkeypatch.setenv("BINANCE_DEMO_SECRET", "s")
    ready = venues.ready_fixture()
    acct = venues.drill_account(ready)
    tag = hashlib.sha256(b"k").hexdigest()[:12]
    exec_id = f"binanceusdm/{tag}/BTCUSDT/903"
    drill = demo_drill.Drill(str(tmp_path / "drill"), "BTCUSDT", None)
    ts = "2026-10-14T00:00:00+00:00"
    journal = [
        {"ts_utc": ts, "event": "submit-intent", "client_id": "e1",
         "symbol": "BTCUSDT", "side": "BUY", "kind": "LIMIT", "qty": 0.010,
         "role": "entry", "algo": False, "reservation_id": "r1"},
        {"ts_utc": ts, "event": "submit-intent", "client_id": "leg-stop",
         "symbol": "BTCUSDT", "side": "SELL", "kind": "STOP_MARKET",
         "qty": 0.010, "role": "stop", "algo": True,
         "reservation_id": "r1"},
        {"ts_utc": ts, "event": "submit-intent", "client_id": "leg-target",
         "symbol": "BTCUSDT", "side": "SELL",
         "kind": "TAKE_PROFIT_MARKET", "qty": 0.010, "role": "target",
         "algo": True, "reservation_id": "r1"},
        {"ts_utc": ts, "event": "fill-adopted", "client_id": "e1",
         "symbol": "BTCUSDT", "qty": 0.010, "execution_id": exec_id},
    ]
    drill.journal_path.write_text(
        "\n".join(json.dumps(r) for r in journal) + "\n")
    store = RunStore(drill.store_path)
    store.create_run("demo-drill", "paper", "fp", str(drill.session_dir),
                     None)
    assert store.record_event("demo-drill", exec_id, "fill",
                              {"client_order_id": "e1",
                               "instrument": "BTCUSDT", "side": "BUY",
                               "qty": 0.010, "price": 100.0, "fee": 0.0,
                               "liquidity": "taker"}, ts)
    store.close()
    ledger = Ledger(120.0)
    assert ledger.record_fill(
        "BUY", 0.010, 100.0, 0.0,
        datetime(2026, 10, 14, tzinfo=timezone.utc), exec_id,
        symbol="BTCUSDT")
    drill.session_dir.mkdir(parents=True, exist_ok=True)
    ledger.save(drill.session_dir / "ledger.json")
    from cryptobot.risk.state import Reservation, RiskState, save_state
    save_state(drill.session_dir / "risk_state.json", RiskState(
        current_day="2026-10-14", day_start_equity=120.0,
        needs_reconciliation=False, open_position=True,
        unresolved={"r1": {
            "reservation": Reservation(
                reservation_id="r1", intent_ref="drill:1",
                instrument="BTCUSDT", side="LONG", notional=1.0,
                reserved_risk=0.15,
                created_utc="2026-10-14T00:00:00+00:00",
                expires_utc="2026-10-15T00:00:00+00:00",
                qty=0.010).to_dict(),
            "unresolved_since_utc": "2026-10-14T00:00:00+00:00"}},
        booked={"r1": {"net_qty": 0.010, "exec_ids": [exec_id],
                       "symbol": "BTCUSDT"}}))
    working = {"algoId": 201, "algoStatus": "WORKING",
               "executedQty": "0", "origQty": "0.010"}
    filled = {"orderId": 77, "status": "FILLED", "executedQty": "0.010",
              "origQty": "0.010"}
    tape = [{"id": 903, "qty": "0.010", "price": "100.00",
             "commission": "0.005", "commissionAsset": "USDT"}]
    transport = venues.ReplayTransport(
        [_listen_open(),
         # Attach heal: adopt every journaled non-terminal order.
         ("GET", "/fapi/v1/order", None, ("ok", dict(filled))),
         ("GET", "/fapi/v1/userTrades", None, ("ok", tape)),
         ("GET", "/fapi/v1/algoOrder", None, ("ok", dict(working))),
         ("GET", "/fapi/v1/algoOrder", None, ("ok", dict(working)))]
        + _ready(acct) + [
            # Legs verify (pre-resume, cover still in place).
            ("GET", "/fapi/v1/algoOrder", None, ("ok", dict(working))),
            ("GET", "/fapi/v1/algoOrder", None, ("ok", dict(working))),
            # Resume recover: entry terminal-skipped, legs re-resolved.
            ("GET", "/fapi/v1/algoOrder", None, ("ok", dict(working))),
            ("GET", "/fapi/v1/algoOrder", None, ("ok", dict(working))),
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("ok", venues.orders_fixture()["orderAck"])),
            # Post-flat journaled-leg cleanup (no orphaned venue legs).
            ("DELETE", "/fapi/v1/algoOrder", None,
             ("ok", _algo_cancelled())),
            ("DELETE", "/fapi/v1/algoOrder", None,
             ("ok", _algo_cancelled())),
            _listen_close()])
    rig = venues.patch_drill_offline(monkeypatch, drill, transport,
                                     venues.orders_fixture())
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            assert demo_drill.cmd_resume_adopt(drill) == 0
    finally:
        rig["stop"]()
    transport.assert_empty()
    phases = (tmp_path / "drill/drill_evidence.jsonl").read_text()
    assert "resume-adopt/protection" in phases
    assert "resume-adopt/close" in phases
    assert Ledger.from_dict(json.loads(
        (drill.session_dir / "ledger.json").read_text())).position_qty() \
        == 0


def test_entry_cutoff_blocks_without_submit(tmp_path, monkeypatch):
    """Past the entry window: BLOCKED before any submit."""
    monkeypatch.setenv("BINANCE_DEMO_KEY", "k")
    monkeypatch.setenv("BINANCE_DEMO_SECRET", "s")
    ready = venues.ready_fixture()
    acct = venues.drill_account(ready)
    transport = venues.ReplayTransport(_ready(acct))
    drill = demo_drill.Drill(str(tmp_path / "drill"), "BTCUSDT", None)
    drill.start_mono -= 3600.0  # deep past the entry window.
    rig = venues.patch_drill_offline(monkeypatch, drill, transport,
                                     venues.orders_fixture())
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            assert demo_drill.cmd_drill(drill) == 2
    finally:
        rig["stop"]()
    transport.assert_empty()
    assert [r for r in transport.requests if r[0] == "POST"
            and r[1] == "/fapi/v1/order"] == []
