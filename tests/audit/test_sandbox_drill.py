"""DEEP-W2-D3: sandbox venue + drill audit tests (offline, seed-pinned).

Covers: simulated-response labeling, stream dupe/reorder idempotency,
rate-limit refuse-fast, unknown-then-lookup resolution, partial-fill
legs, filter rejection, reduce-only rules, listenKey lifecycle,
snapshot round-trip, and the full offline drill command.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.adapters.binance_live import (
    BinanceLiveEngine,
    RateLimitedError,
    UnknownOutcomeError,
    VenueHttpError,
    VenueRejectedError,
)
from cryptobot.adapters.sandbox_venue import (
    LABEL_KEY,
    FaultScript,
    SandboxConfig,
    SandboxSocket,
    SandboxTransport,
    SandboxVenue,
)
from cryptobot.app.engine import EngineOrder

SYMBOL = "ETHUSDT"


def _engine(tmp_path, faults=None, seed=7):
    venue = SandboxVenue(SandboxConfig(
        seed=seed, faults=FaultScript(entries=list(faults or []))))
    transport = SandboxTransport(venue)
    engine = BinanceLiveEngine(
        api_key="k", api_secret="s",
        journal_path=tmp_path / "journal.jsonl", expected_leverage=3,
        run_tag="t", live_enable=True, transport=transport)
    engine._ensure_ready(SYMBOL)
    return engine, venue


def _journal(engine):
    return list(engine._read_journal())


def test_all_simulated_dict_responses_labeled(tmp_path):
    engine, venue = _engine(tmp_path)
    transport = engine._transport
    assert transport.request(
        "GET", "/fapi/v1/time", {}, {})[LABEL_KEY] is True
    assert transport.request(
        "GET", "/fapi/v1/exchangeInfo", {}, {})[LABEL_KEY] is True
    assert transport.request(
        "GET", "/fapi/v2/account", {}, {})[LABEL_KEY] is True
    cid = engine.submit(EngineOrder(SYMBOL, "BUY", 0.01, "MARKET",
                                    reservation_id="r"))
    assert engine.lookup(cid) is not None
    env = SandboxSocket(venue).recv(0)
    assert env[LABEL_KEY] is True  # stream envelopes labeled too.


def test_stream_dupe_adopts_once(tmp_path):
    engine, venue = _engine(
        tmp_path, faults=[{"op": "stream", "action": "dupe",
                           "at": "once"}])
    cid = engine.submit(EngineOrder(SYMBOL, "BUY", 0.01, "MARKET",
                                    reservation_id="r"))
    sock = SandboxSocket(venue)
    first, second = sock.recv(0), sock.recv(0)
    assert first is not None and second is not None
    assert first["o"]["t"] == second["o"]["t"]  # same trade id.
    engine.note_user_event(first)
    engine.note_user_event(second)  # duplicate delivery.
    adopts = [r for r in _journal(engine)
              if r.get("event") == "fill-adopted"]
    assert len(adopts) == 1
    fills = [e for e in engine.poll() if e.kind == "fill"]
    assert fills and {f.payload.execution_id for f in fills} == \
        {adopts[0]["exec_id"]}
    assert engine.filled_qty(cid) == pytest.approx(0.01)


def test_stream_reorder_safe(tmp_path):
    engine, venue = _engine(
        tmp_path, faults=[{"op": "stream", "action": "reorder",
                           "at": "once"}])
    c1 = engine.submit(EngineOrder(SYMBOL, "BUY", 0.01, "MARKET",
                                   reservation_id="r1"))
    c2 = engine.submit(EngineOrder(SYMBOL, "BUY", 0.01, "MARKET",
                                   reservation_id="r2"))
    sock = SandboxSocket(venue)
    got = [sock.recv(0), sock.recv(0)]
    assert {g["o"]["c"] for g in got} == {c1, c2}
    for envelope in got:  # arrival order swapped vs submit order.
        engine.note_user_event(envelope)
    assert engine.filled_qty(c1) == pytest.approx(0.01)
    assert engine.filled_qty(c2) == pytest.approx(0.01)
    assert engine.order_status(c1).state == "filled"
    assert engine.order_status(c2).state == "filled"


def test_rate_limit_refuse_fast_no_order(tmp_path):
    engine, venue = _engine(
        tmp_path, faults=[{"op": "order", "action": "rate-limit",
                           "at": "once"}])
    with pytest.raises((RateLimitedError, VenueHttpError)):
        engine.submit(EngineOrder(SYMBOL, "BUY", 0.01, "MARKET",
                                  reservation_id="r"))
    # Refused at the venue edge: intent journaled (honest attempt),
    # but nothing created, nothing filled, nothing on tape.
    assert venue.orders == {}
    assert venue.trades == []
    assert engine.filled_qty(
        [r for r in _journal(engine)
         if r.get("event") == "submit-intent"][0]["client_id"]) == 0.0
    # The engine now refuse-fasts inside its 60s window (no transport
    # call at all); a fresh engine on the same venue recovers.
    calls_before = len(venue.log)
    with pytest.raises(RateLimitedError):
        engine.submit(EngineOrder(SYMBOL, "BUY", 0.01, "MARKET",
                                  reservation_id="r-guard"))
    assert len(venue.log) == calls_before
    engine2, _ = _engine(tmp_path, seed=8)
    engine2._transport.venue = venue  # same venue, fresh guard.
    cid = engine2.submit(EngineOrder(SYMBOL, "BUY", 0.01, "MARKET",
                                     reservation_id="r2"))
    assert engine2.order_status(cid).state == "filled"  # recovers.


def test_unknown_then_lookup_resolves_no_duplicate(tmp_path):
    venue = SandboxVenue(SandboxConfig(seed=7))
    inner = SandboxTransport(venue)

    class _DropOnce:
        def __init__(self):
            self.armed = True

        def request(self, method, path, params, headers):
            if self.armed and method == "POST" \
                    and path == "/fapi/v1/order":
                self.armed = False
                inner.request(method, path, params, headers)  # applied.
                raise VenueHttpError(0, None, "dropped")
            return inner.request(method, path, params, headers)

    engine = BinanceLiveEngine(
        api_key="k", api_secret="s",
        journal_path=tmp_path / "journal.jsonl", expected_leverage=3,
        run_tag="t", live_enable=True, transport=_DropOnce())
    engine._ensure_ready(SYMBOL)
    with pytest.raises(UnknownOutcomeError) as caught:
        engine.submit(EngineOrder(SYMBOL, "BUY", 0.01, "MARKET",
                                  reservation_id="r"))
    cid = caught.value.client_id
    assert engine.lookup(cid).state == "filled"  # resolves via tape.
    intents = [r for r in _journal(engine)
               if r.get("event") == "submit-intent"]
    assert len(intents) == 1  # never resubmitted.


def test_partial_fill_legs_exact_tape(tmp_path):
    engine, venue = _engine(
        tmp_path, faults=[{"op": "order", "action": "partial-legs",
                           "at": "once"}])
    book = venue.book(SYMBOL)
    cid = engine.submit(EngineOrder(
        SYMBOL, "BUY", 0.01, "LIMIT", price=round(book["ask"] * 1.01, 2),
        reservation_id="r"))
    status = engine.lookup(cid)
    assert status.state == "partial"
    assert 0.0 < status.filled_qty < 0.01
    trades = engine._signed("GET", "/fapi/v1/userTrades",
                            {"symbol": SYMBOL,
                             "orderId": venue.by_client[cid]})
    assert len(trades) == 1
    assert float(trades[0]["qty"]) == pytest.approx(status.filled_qty)
    fee = float(trades[0]["commission"])
    assert fee == pytest.approx(
        status.filled_qty * float(trades[0]["price"]) * 0.0005)


def test_filters_reject_below_minimum_void_lookup(tmp_path):
    engine, _venue = _engine(tmp_path)
    # 0.001 passes the client LOT_SIZE step but $2.50 notional fails
    # the venue $5 MIN_NOTIONAL.
    with pytest.raises(VenueRejectedError):
        engine.submit(EngineOrder(SYMBOL, "BUY", 0.001, "MARKET",
                                  reservation_id="r"))
    intents = [r for r in _journal(engine)
               if r.get("event") == "submit-intent"]
    assert len(intents) == 1
    assert engine.lookup(intents[0]["client_id"]) is None  # void.
    assert engine.filled_qty(intents[0]["client_id"]) == 0.0


def test_reduce_only_rules(tmp_path):
    engine, _venue = _engine(tmp_path)
    with pytest.raises(VenueRejectedError, match="-2022"):
        engine.submit(EngineOrder(SYMBOL, "SELL", 0.01, "MARKET",
                                  reservation_id="r0",
                                  reduce_only=True))
    engine.submit(EngineOrder(SYMBOL, "BUY", 0.01, "MARKET",
                              reservation_id="r1"))
    cid = engine.submit(EngineOrder(SYMBOL, "SELL", 0.01, "MARKET",
                                    reservation_id="r2",
                                    reduce_only=True))
    assert engine.order_status(cid).state == "filled"


def test_listen_key_lifecycle_and_expiry(tmp_path):
    engine, venue = _engine(
        tmp_path, faults=[{"op": "stream", "action": "expire-key",
                           "at": "once"}])
    key = engine.open_listen_key()
    assert key.startswith("sandbox-")
    engine.keepalive_listen_key()
    venue._maybe_request_fault("stream")  # scripted expiry inject.
    sock = SandboxSocket(venue)
    env = sock.recv(0)
    assert env is not None and env["e"] == "listenKeyExpired"
    assert env[LABEL_KEY] is True
    engine.close()  # close path tolerates the dead key.


def test_snapshot_roundtrip_preserves_state(tmp_path):
    engine, venue = _engine(tmp_path, seed=11)
    engine.submit(EngineOrder(SYMBOL, "BUY", 0.01, "MARKET",
                              reservation_id="r"))
    snap_path = tmp_path / "venue.json"
    venue.save(snap_path)
    venue2 = SandboxVenue.load(snap_path)
    assert venue2.positions == venue.positions
    assert venue2.wallet == venue.wallet
    assert venue2.trades == venue.trades
    assert venue2._order_seq == venue._order_seq
    book_a = venue.book(SYMBOL)
    book_b = venue2.book(SYMBOL)
    assert book_a["bid"] == pytest.approx(book_b["bid"])


def test_full_offline_drill_passes(tmp_path):
    root = Path(__file__).resolve().parents[2]
    run_dir = tmp_path / "drill"
    proc = subprocess.run(
        [sys.executable, str(root / "tools" / "audit" / "sandbox_drill.py"),
         "--dir", str(run_dir), "--seed", "7", "full"],
        capture_output=True, text=True, timeout=600,
        cwd=str(root), env={"PATH": "/usr/bin:/bin",
                            "PYTHONPATH": str(root / "src")})
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    report = json.loads((run_dir / "report.json").read_text())
    assert report["verdict"] == "PASS"
    assert report["sandbox_stamp"] == "SANDBOX VALIDATED"
    assert report["demo_stamp"] == "BINANCE DEMO VALIDATION PENDING"
    assert (run_dir / "report.md").stat().st_size > 0
    assert (run_dir / "sandbox_evidence.jsonl").stat().st_size > 0
