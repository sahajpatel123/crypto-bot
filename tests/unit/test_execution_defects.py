"""Execution defects found by auditing the live money path.

Four defects, each pinned by a test that fails on the tree before its fix:

1. A crash between persisting the submit intention and recording the engine
   id left an id-less command row. ``_reconcile_commands`` marked it
   "unknown" and ``_admission_hold`` then blocked every entry for the life of
   the run, even though the adapter journal knew the id it had issued.
2. One -2013 "order does not exist" reply voided a just-accepted order.
   ``order_manager.reconcile`` turns a void into CANCELLED, so a transient
   read miss silently dropped real venue cover.
3. The clock offset was synced once per symbol and never again, so a -1021
   (timestamp outside recvWindow) mapped to reject_intent and every order
   rejected forever with no alert.
4. Protection legs were sized to filled qty only and supervision treated a
   live entry as needing no cover, so a still-fillable remainder was naked —
   and legs were cancelled as "protection-vacuous" while an unbooked fill
   meant the local net read flat.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from tests.unit.test_release_contract import (
    _ContractEngine,
    _position,
    _reservation,
    _session,
)

import venue_fixtures as venues
from cryptobot.adapters.binance_live import VenueRejectedError
from cryptobot.app.engine import EngineOrder, EngineOrderStatus

T0MS = venues.T0MS
NOW = venues.NOW
_live = venues.make_engine
_ready_script = venues.ready_script
_ready = venues.ready_fixture
_orders = venues.orders_fixture


def _submit_market(engine, qty=0.002):
    return engine.submit(EngineOrder("BTCUSDT", "BUY", qty, "MARKET",
                                     reservation_id="r1"))


# -- 1. an id-less command row must be re-linked, not declared unknown -------


def test_idless_command_relinks_from_engine_journal(tmp_path):
    """Crash inside submit: the journal knows the id the row lost."""
    engine = _ContractEngine()
    session, store = _session(tmp_path, engine)
    try:
        cmd = session._new_command("submit", {
            "role": "entry", "instrument": "BTCUSDT", "side": "BUY",
            "qty": 0.05, "reservation_id": "r-1"})
        # The adapter journaled the id it issued before the process died.
        cid = "bl-abcd1234-000001"
        engine.states[cid] = EngineOrderStatus(
            cid, "BTCUSDT", "open", 0.05, 0.0, "r-1", "entry")
        engine.journal_client_ids = lambda: (cid,)
        engine.journal_reservation = lambda c: "r-1" if c == cid else None
        assert store.open_commands("rel")[0]["engine_client_id"] is None

        session._reconcile_commands()

        row = store.open_commands("rel")[0]
        assert row["cmd_id"] == cmd
        assert row["engine_client_id"] == cid, "journal-known id not re-linked"
        assert row["status"] == "submitted", "row stuck unknown blocks entry"
        assert session._admission_hold() is None
    finally:
        store.close()


def test_idless_command_stays_unknown_without_a_journal_match(tmp_path):
    """No journal entry for this reservation: still fail closed."""
    engine = _ContractEngine()
    other = "bl-abcd1234-000009"
    engine.states[other] = EngineOrderStatus(
        other, "BTCUSDT", "open", 0.05, 0.0, "r-OTHER", "entry")
    engine.journal_client_ids = lambda: (other,)
    engine.journal_reservation = lambda c: "r-OTHER"
    session, store = _session(tmp_path, engine)
    try:
        session._new_command("submit", {
            "role": "entry", "instrument": "BTCUSDT", "side": "BUY",
            "qty": 0.05, "reservation_id": "r-1"})
        session._reconcile_commands()
        assert store.open_commands("rel")[0]["status"] == "unknown"
        assert session._admission_hold() == "reconcile:unknown-commands"
    finally:
        store.close()


# -- 2. -2013 voids only after consecutive misses over a grace window -------


def test_single_unknown_order_reply_does_not_void(tmp_path):
    ready, orders = _ready(), _orders()
    clock = {"now": NOW}
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("ok", orders["orderAck"]))],
        now_utc=lambda: clock["now"])
    cid = _submit_market(engine)

    def miss():
        return ("GET", "/fapi/v1/order", {"origClientOrderId": cid},
                ("err", 400, -2013, "Order does not exist."))

    transport.append(miss())
    status = engine.lookup(cid)
    assert status is not None, "a single venue miss voided a live order"
    assert status.state == "open"
    assert engine.order_status(cid).state == "open"

    # Further misses inside the grace window still do not void it.
    transport.append(miss(), miss())
    assert engine.lookup(cid) is not None
    assert engine.lookup(cid) is not None

    # A hit clears the streak: the window restarts.
    transport.append(("GET", "/fapi/v1/order", {"origClientOrderId": cid},
                      ("ok", dict(orders["orderQueryFilled"],
                                  executedQty="0.0", status="NEW",
                                  avgPrice="0.0", cumQuote="0.0"))))
    assert engine.lookup(cid) is not None
    transport.append(miss())
    assert engine.lookup(cid) is not None, "streak survived a successful read"
    transport.assert_empty()


def test_consecutive_misses_over_the_grace_window_void(tmp_path):
    ready, orders = _ready(), _orders()
    clock = {"now": NOW}
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("ok", orders["orderAck"]))],
        now_utc=lambda: clock["now"])
    cid = _submit_market(engine)

    def miss():
        return ("GET", "/fapi/v1/order", {"origClientOrderId": cid},
                ("err", 400, -2013, "Order does not exist."))

    for _ in range(3):
        transport.append(miss())
        assert engine.lookup(cid) is not None
    clock["now"] = clock["now"] + timedelta(seconds=10)
    transport.append(miss())
    assert engine.lookup(cid) is None, "venue never saw it: must void"
    assert engine.order_status(cid).state == "cancelled"
    transport.assert_empty()


# -- 3. -1021 re-syncs the clock offset and retries once --------------------


def test_clock_skew_resyncs_offset_and_retries_once(tmp_path):
    ready, orders = _ready(), _orders()
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("err", 400, -1021,
              "Timestamp for this request is outside of the recvWindow.")),
            ("GET", "/fapi/v1/time", None, ("ok", {"serverTime": T0MS + 9000})),
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("ok", orders["orderAck"]))])
    assert engine._offset_ms == 0

    cid = _submit_market(engine)

    assert cid, "a clock-skew rejection must not reject the intent"
    assert engine._offset_ms == 9000, "offset not refreshed from /fapi/v1/time"
    transport.assert_empty()


def test_persistent_clock_rejection_is_raised_not_retried_forever(tmp_path):
    ready = _ready()
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("err", 400, -1021,
              "Timestamp for this request is outside of the recvWindow.")),
            ("GET", "/fapi/v1/time", None, ("ok", {"serverTime": T0MS + 9000})),
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("err", 400, -1021,
              "Timestamp for this request is outside of the recvWindow."))])
    with pytest.raises(VenueRejectedError) as info:
        _submit_market(engine)
    assert info.value.code == -1021
    transport.assert_empty()


# -- 4. cover the whole live entry; never void cover on an unbooked fill ----

_PARTIAL = {
    "avgPrice": "60000.00", "cumQuote": "60.00", "executedQty": "0.001",
    "orderId": 12345, "origQty": "0.002", "status": "PARTIALLY_FILLED",
    "symbol": "BTCUSDT",
}
_PARTIAL_TRADES = [{
    "buyer": True, "commission": "0.03000000", "commissionAsset": "USDT",
    "id": 999001, "orderId": 12345, "price": "60000.00", "qty": "0.001",
    "symbol": "BTCUSDT",
}]


def test_protection_legs_cover_a_still_fillable_remainder(tmp_path):
    ready, orders = _ready(), _orders()
    engine, transport = _live(
        tmp_path, _ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "MARKET"},
             ("ok", orders["orderAck"]))])
    entry = _submit_market(engine)
    transport.append(
        ("GET", "/fapi/v1/order", {"origClientOrderId": entry},
         ("ok", dict(_PARTIAL, origClientOrderId=entry))),
        ("GET", "/fapi/v1/userTrades", {"orderId": 12345},
         ("ok", _PARTIAL_TRADES)),
        # Half is filled; the leg still covers the full entry qty.
        ("POST", "/fapi/v1/algoOrder",
         {"type": "STOP_MARKET", "quantity": "0.002", "reduceOnly": "true"},
         ("ok", orders["algoAck"])))
    legs = engine.attach_protection(entry, 59990.0, None)
    assert len(legs) == 1
    transport.assert_empty()


def test_protection_need_covers_a_live_entry(tmp_path):
    engine = _ContractEngine()
    session, store = _session(tmp_path, engine)
    try:
        session.policy._state.reservations["r-1"] = _reservation(
            session, qty=0.05)
        session.ledger.record_fill("BUY", 0.02, 100.0, 0.05,
                                   session.now_utc(), "f1", "BTCUSDT")
        statuses = {"e": EngineOrderStatus(
            "e", "BTCUSDT", "open", 0.05, 0.02, "r-1", "entry")}
        pos = {"reservation_id": "r-1", "entry_id": "e", "legs": [],
               "entry_pre_id": "e"}
        assert session._protection_need(pos, statuses) == pytest.approx(0.05)
        # A dead entry retires its remainder: only the booked net is needed.
        statuses["e"] = EngineOrderStatus(
            "e", "BTCUSDT", "cancelled", 0.05, 0.02, "r-1", "entry")
        assert session._protection_need(pos, statuses) == pytest.approx(0.02)
    finally:
        store.close()


def test_unbooked_entry_fill_never_cancels_cover(tmp_path):
    """Entry live with a venue fill the ledger has not booked yet."""
    engine = _ContractEngine()
    session, store = _session(tmp_path, engine)
    try:
        engine.states["e"] = EngineOrderStatus(
            "e", "BTCUSDT", "open", 0.0, 0.05, "r-1", "entry")
        engine.states["stop-1"] = EngineOrderStatus(
            "stop-1", "BTCUSDT", "open", 0.05, 0.0, "r-1", "stop")
        session._position = _position(legs=["stop-1"], approved_qty=0.0,
                                      executable_qty=0.0)
        session._ensure_protection(session._position)
        assert engine.cancelled == [], "cover cancelled while the entry lives"
    finally:
        store.close()


def test_vacuous_cover_is_still_cancelled_for_a_dead_entry(tmp_path):
    engine = _ContractEngine()
    session, store = _session(tmp_path, engine)
    try:
        engine.states["e"] = EngineOrderStatus(
            "e", "BTCUSDT", "cancelled", 0.0, 0.0, "r-1", "entry")
        engine.states["stop-1"] = EngineOrderStatus(
            "stop-1", "BTCUSDT", "open", 0.05, 0.0, "r-1", "stop")
        session._position = _position(legs=["stop-1"], approved_qty=0.0,
                                      executable_qty=0.0)
        session._ensure_protection(session._position)
        assert engine.cancelled == ["stop-1"]
    finally:
        store.close()


# -- 5. one leverage-brackets contract for both admission gates -------------


def test_leverage_brackets_serve_the_tiered_contract(tmp_path):
    """A duplicate definition shadowed the tiered contract the risk gate needs.

    ``_bracket_admission`` requires the F0.4a document (``brackets`` +
    ``observed_ms`` + ``stale``); a second ``leverage_brackets`` defined later
    in the class returned a bare list, so every prod entry was refused with
    ``margin:brackets-unavailable``.
    """
    engine, transport = _live(tmp_path, [
        ("GET", "/fapi/v1/leverageBracket", {"symbol": "BTCUSDT"},
         ("ok", [{"symbol": "BTCUSDT", "brackets": [
             {"bracket": 1, "notionalCap": 50000,
              "maintMarginRatio": 0.004, "cum": 0},
             {"bracket": 2, "notionalCap": 100000,
              "maintMarginRatio": 0.005, "cum": 50}]}])),
    ])
    data = engine.leverage_brackets("BTCUSDT")
    assert isinstance(data, dict), "tiered contract shadowed by a bare list"
    assert [b["notionalCap"] for b in data["brackets"]] == [50000.0, 100000.0]
    assert data["observed_ms"] and data["stale"] is False
    # Inside the TTL the cache answers: no second REST call.
    assert engine.leverage_brackets("BTCUSDT")["brackets"] == data["brackets"]
    transport.assert_empty()


def test_liquidation_gate_unwraps_the_tiered_contract(tmp_path):
    engine = _ContractEngine()
    session, store = _session(tmp_path, engine)
    try:
        rows = [{"notionalCap": 1.0}]
        assert session._bracket_rows({"brackets": rows}) == rows
        assert session._bracket_rows(rows) == rows  # bare list still allowed
        assert session._bracket_rows(None) is None
    finally:
        store.close()
