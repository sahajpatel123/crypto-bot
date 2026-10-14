"""Release Checkpoint-A mechanics fixture (Worker 2).

Injected-venue responses driving the NORMAL Session — labeled
synthetic-mechanics only (not economics, not a venue recording):
fill→ledger→protection, unknown→lookup→no-duplicate-entry, restart
re-adopt without duplicate keys, and the reduce-only exit path.
"""
import copy
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import venue_fixtures as venues
from cryptobot.app.config import load_config
from cryptobot.app.session import Session
from cryptobot.app.store import RunStore
from cryptobot.coordination.exits import encode_exit_rule, ExitPolicy
from cryptobot.coordination.intent import (
    DataQuality, ForecastCost, Intent, Side)
from cryptobot.coordination.selector import Candidate

MECHANICS = "synthetic-mechanics"


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
            policy_id="checkpoint-a")),
        holding_limit_s=600,
        forecast_cost=ForecastCost(5.0, 5.0, 5.0, 1.0),
        evidence_ref=f"{MECHANICS}:1", data_quality=DataQuality.CLEAN)


def _session(tmp_path: Path, engine, run_id: str):
    cfg = load_config(_config(tmp_path))
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    session = Session(cfg, store, tmp_path / "runs" / run_id, run_id,
                      engine=engine)
    now = datetime(2026, 10, 12, 6, 0, tzinfo=timezone.utc)
    session.clock.set_ms(int(now.timestamp() * 1000))
    session.policy.reconcile_day(120.0, 0.0)
    session.store.create_run(run_id, MECHANICS, "fp",
                             str(session.workdir), None)
    session.arm_replay_filters(
        {"BTCUSDT": {"tick_size": 0.10, "step_size": 0.001,
                     "min_qty": 0.001, "min_notional": 5.0}},
        origin=MECHANICS, asof_utc=now)
    from cryptobot.app.session import _SymbolFeed
    feed = _SymbolFeed("BTCUSDT", 0)
    feed.mark = 100.0
    feed.mark_ts = now
    session._feeds["BTCUSDT"] = feed
    return session, store


def _submitted_qty(transport) -> float:
    for method, path, params, _ in transport.requests:
        if method == "POST" and path == "/fapi/v1/order":
            return float(params["quantity"])
    raise AssertionError("no venue submit observed")


def _trade(orders, cid, side, state, last, cum, price, fee, tid):
    event = copy.deepcopy(orders["userStreamTrade"])
    event["o"]["c"] = cid
    event["o"]["S"] = side
    event["o"]["X"] = state
    event["o"]["x"] = "TRADE"
    event["o"]["l"] = f"{last:.3f}"
    event["o"]["z"] = f"{cum:.3f}"
    event["o"]["L"] = event["o"]["ap"] = f"{price:.2f}"
    event["o"]["n"] = f"{fee:.8f}"
    event["o"]["t"] = tid
    return event


def _flat_account(ready):
    view = copy.deepcopy(ready["account"])
    view["positions"] = []
    # A COMPLETE venue view: without totalWalletBalance the adapter
    # reports complete=False and flat is correctly never declared
    # (fail-closed; that leg is proven in test_release_contract.py).
    view["totalWalletBalance"] = "120.75000000"
    return view


def test_live_fill_to_ledger_to_protection(tmp_path):
    ready, orders = venues.ready_fixture(), venues.orders_fixture()
    engine, transport = venues.make_engine(
        tmp_path, [("GET", "/fapi/v2/account", None,
                    ("ok", ready["account"])),
                   ("GET", "/fapi/v1/openOrders", None, ("ok", [])),
                   ("GET", "/fapi/v1/openAlgoOrders", None, ("ok", []))] \
            + venues.ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "LIMIT"},
             ("ok", orders["orderAck"]))])
    session, store = _session(tmp_path, engine, "ca-fill")
    try:
        session._maybe_admit([Candidate("S1", _intent(session.now_utc()))])
        assert session._position is not None
        qty = _submitted_qty(transport)
        assert qty * 100.0 >= 5.0  # venue min-notional respected.
        # Venue streams the full fill; the bound handler books it, and
        # Session attaches protection synchronously inside the stream
        # handler (lookup + tape + reduce-only algo pair), so the whole
        # dialogue is scripted before the stream event. Drain-phase
        # presence reads stay last.
        entry = session._position["entry_pre_id"]
        transport.append(
            ("GET", "/fapi/v1/order", {"origClientOrderId": entry},
             ("ok", {"orderId": 7, "status": "FILLED",
                     "executedQty": f"{qty:.3f}"})),
            ("GET", "/fapi/v1/userTrades", {"orderId": 7}, ("ok", [])),
            ("POST", "/fapi/v1/algoOrder", {"reduceOnly": "true"},
             ("ok", {"algoId": 11, "algoStatus": "WORKING"})),
            ("POST", "/fapi/v1/algoOrder", {"reduceOnly": "true"},
             ("ok", {"algoId": 12, "algoStatus": "WORKING"})))
        stream = copy.deepcopy(orders["userStreamTrade"])
        stream["o"]["c"] = entry
        stream["o"]["l"] = stream["o"]["z"] = f"{qty:.3f}"
        stream["o"]["L"] = stream["o"]["ap"] = "100.50"
        engine.note_user_event(stream)
        assert session.ledger.has_position()
        rows = store._db.execute(
            "SELECT execution_id FROM execution_events WHERE run_id='ca-fill'"
            " AND kind='fill'").fetchall()
        assert len(rows) == 1  # fill→ledger exactly once.
        assert rows[0][0].startswith("binanceusdm/")
        # Protection attached synchronously inside the stream handler;
        # the drain only runs presence verification reads.
        session._drain_engine()
        algos = [r for r in transport.requests
                 if r[1] == "/fapi/v1/algoOrder"]
        assert len(algos) == 2
        transport.assert_empty()
    finally:
        store.close()


def test_unknown_blocks_duplicate_entry_until_lookup(tmp_path):
    ready, orders = venues.ready_fixture(), venues.orders_fixture()
    engine, transport = venues.make_engine(
        tmp_path, [("GET", "/fapi/v2/account", None,
                    ("ok", ready["account"])),
                   ("GET", "/fapi/v1/openOrders", None, ("ok", [])),
                   ("GET", "/fapi/v1/openAlgoOrders", None, ("ok", []))] \
            + venues.ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "LIMIT"},
             ("err", 503, None, "gateway"))])
    session, store = _session(tmp_path, engine, "ca-unknown")
    try:
        import pytest
        from cryptobot.adapters.binance_live import UnknownOutcomeError
        # W1-CATCH: Session retains the unknown cid and reconciles by
        # durable client ID before any resubmission (contract §4). Until
        # the merge the error propagates out of admission.
        with pytest.raises(UnknownOutcomeError):
            session._maybe_admit(
                [Candidate("S1", _intent(session.now_utc()))])
        (unknown,) = engine.unknown_ids()
        assert engine.order_status(unknown).state == "unknown"
        assert unknown not in [o.client_order_id
                               for o in engine.open_orders()]
        # During-unknown re-admit is blocked once Session retains the
        # unknown cid (W1 retention; single-position rule then holds).
        sent = len(transport.requests)
        try:
            session._maybe_admit(
                [Candidate("S1", _intent(session.now_utc()))])
        except UnknownOutcomeError:
            pass  # pre-merge: no retention yet; post-merge: blocked.
        assert len(transport.requests) == sent  # no duplicate entry.
        # Lookup resolves; the position then books from the tape.
        transport.append(
            ("GET", "/fapi/v1/order", {"origClientOrderId": unknown},
             ("ok", {"orderId": 7, "status": "FILLED",
                     "executedQty": "0.060", "origQty": "0.060"})),
            ("GET", "/fapi/v1/userTrades", {"orderId": 7},
             ("ok", [{"id": 555, "qty": "0.060", "price": "100.50",
                      "commission": "0.03",
                      "commissionAsset": "USDT"}])))
        engine.lookup(unknown)
        assert engine.unknown_ids() == ()
        # Lookup-adopted fill reaches the Session store with a
        # namespaced execution id (ledger booking follows once W1
        # retains the unknown cid in a position shell).
        rows = store._db.execute(
            "SELECT execution_id FROM execution_events"
            " WHERE run_id='ca-unknown' AND kind='fill'").fetchall()
        assert len(rows) == 1
        assert rows[0][0].startswith("binanceusdm/")
        assert engine.order_status(unknown).state == "filled"
        transport.assert_empty()
    finally:
        store.close()


def test_restart_readopts_same_keys_without_resubmit(tmp_path):
    ready, orders = venues.ready_fixture(), venues.orders_fixture()
    engine, transport = venues.make_engine(
        tmp_path, [("GET", "/fapi/v2/account", None,
                    ("ok", ready["account"])),
                   ("GET", "/fapi/v1/openOrders", None, ("ok", [])),
                   ("GET", "/fapi/v1/openAlgoOrders", None, ("ok", []))] \
            + venues.ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "LIMIT"},
             ("ok", orders["orderAck"]))])
    session, store = _session(tmp_path, engine, "ca-restart")
    try:
        session._maybe_admit([Candidate("S1", _intent(session.now_utc()))])
        entry_id = session._position["entry_pre_id"]
        qty = _submitted_qty(transport)
        # Stream dies before any fill: the order is possibly-executed
        # in the journal. Restart reconciles by durable client ID via
        # lookup (contract §4) — no resubmit, no new keys.
        engine2, transport2 = venues.make_engine(
            tmp_path, [
                ("GET", "/fapi/v1/order",
                 {"origClientOrderId": entry_id},
                 ("ok", {"orderId": 12345, "status": "FILLED",
                         "executedQty": f"{qty:.3f}",
                         "origQty": f"{qty:.3f}"})),
                ("GET", "/fapi/v1/userTrades", {"orderId": 12345},
                 ("ok", [{"id": 777001, "qty": f"{qty:.3f}",
                          "price": "100.50", "commission": "0.03",
                          "commissionAsset": "USDT"}]))])
        adopted: list = []

        def _tee(event):
            adopted.append(event)
            session._on_engine_event(event)

        # Session still points at the original engine, so the
        # recovery-adopted fill drives its synchronous protection
        # attach there: the original engine replays the tape via its
        # own lookup and adopts trade 777001 (same execution_id, so
        # the Session books it once and the re-adopt is a no-op).
        transport.append(
            ("GET", "/fapi/v1/order",
             {"origClientOrderId": entry_id},
             ("ok", {"orderId": 12345, "status": "FILLED",
                     "executedQty": f"{qty:.3f}",
                     "origQty": f"{qty:.3f}"})),
            ("GET", "/fapi/v1/userTrades", {"orderId": 12345},
             ("ok", [{"id": 777001, "qty": f"{qty:.3f}",
                      "price": "100.50", "commission": "0.03",
                      "commissionAsset": "USDT"}])),
            ("POST", "/fapi/v1/algoOrder", {"reduceOnly": "true"},
             ("ok", {"algoId": 21, "algoStatus": "WORKING"})),
            ("POST", "/fapi/v1/algoOrder", {"reduceOnly": "true"},
             ("ok", {"algoId": 22, "algoStatus": "WORKING"})))
        engine2.recover(_tee)  # rebinds the sink to the recovery handler.
        fills = [e for e in adopted if e.kind == "fill"]
        assert len(fills) == 1
        assert fills[0].payload.execution_id.startswith("binanceusdm/")
        assert fills[0].payload.execution_id.endswith("/BTCUSDT/777001")
        assert fills[0].payload.client_order_id == entry_id
        posts = [r for r in transport2.requests
                 if r[0] == "POST" and r[1] == "/fapi/v1/order"]
        assert posts == []  # reconciled, never resubmitted.
        assert engine2.order_status(entry_id).state == "filled"
        # Single attach: the lookup-adopted fill must not nest a second
        # stop/target pair (reentrancy guard regression).
        algos = [r for r in transport.requests
                 if r[1] == "/fapi/v1/algoOrder"]
        assert len(algos) == 2
        transport.assert_empty()
        transport2.assert_empty()
    finally:
        store.close()


def test_live_partial_exit_resize_final_exit_and_flat(tmp_path):
    """Live exit legs on the injected venue (REL-W1-EXIT, §9-A).

    Partial entry → small pair; more entry fills → pair REPLACED
    (sibling resize-up, old legs cancelled, never duplicated);
    partial target fill → partial exit with the stop re-verified over
    the shrunken need (reduce-only over-cover: no churn, no
    over-close); final target fill → full exit with sibling
    termination; then 7-leg reconciled flatness (venue snapshot +
    fills + ledger + risk + reservations + commands + children).
    Split sizes are step multiples that net to exactly 0.0 in float
    (brute-force verified for qty 0.083, asserted below).
    """
    ready, orders = venues.ready_fixture(), venues.orders_fixture()
    engine, transport = venues.make_engine(
        tmp_path, [("GET", "/fapi/v2/account", None,
                    ("ok", ready["account"])),
                   ("GET", "/fapi/v1/openOrders", None, ("ok", [])),
                   ("GET", "/fapi/v1/openAlgoOrders", None, ("ok", []))]
        + venues.ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "LIMIT"},
             ("ok", orders["orderAck"]))])
    session, store = _session(tmp_path, engine, "ca-exit")
    try:
        session._maybe_admit([Candidate("S1", _intent(session.now_utc()))])
        assert session._position is not None
        rid = session._position["reservation_id"]
        qty = _submitted_qty(transport)
        assert qty == 0.083  # sizing guard: splits below net exactly.
        entry = session._position["entry_pre_id"]
        seen_nets = []

        def _algos():
            return [r for r in transport.requests
                    if r[0] == "POST" and r[1] == "/fapi/v1/algoOrder"]

        def _deletes():
            return [r for r in transport.requests
                    if r[0] == "DELETE" and r[1] == "/fapi/v1/algoOrder"]

        # -- partial entry 0.050: small pair attaches. -----------------
        transport.append(
            ("GET", "/fapi/v1/order", {"origClientOrderId": entry},
             ("ok", {"orderId": 7, "status": "PARTIALLY_FILLED",
                     "executedQty": "0.050"})),
            ("GET", "/fapi/v1/userTrades", {"orderId": 7}, ("ok", [])),
            ("POST", "/fapi/v1/algoOrder", {"reduceOnly": "true"},
             ("ok", {"algoId": 11, "algoStatus": "WORKING"})),
            ("POST", "/fapi/v1/algoOrder", {"reduceOnly": "true"},
             ("ok", {"algoId": 12, "algoStatus": "WORKING"})))
        engine.note_user_event(_trade(
            orders, entry, "BUY", "PARTIALLY_FILLED", 0.050, 0.050,
            100.50, 0.030, 771001))
        assert session.ledger.position_qty() == 0.050
        assert session._position["protected"] is True
        stop1, tgt1 = session._position["legs"]
        assert engine.order_status(stop1).qty == 0.050
        assert len(_algos()) == 2
        seen_nets.append(session.ledger.position_qty())

        # -- entry remainder 0.033: pair REPLACED (resize-up). ---------
        transport.append(
            ("DELETE", "/fapi/v1/algoOrder",
             {"origClientAlgoId": stop1}, ("ok", {})),
            ("DELETE", "/fapi/v1/algoOrder",
             {"origClientAlgoId": tgt1}, ("ok", {})),
            ("GET", "/fapi/v1/order", {"origClientOrderId": entry},
             ("ok", {"orderId": 7, "status": "FILLED",
                     "executedQty": "0.083"})),
            ("GET", "/fapi/v1/userTrades", {"orderId": 7}, ("ok", [])),
            ("POST", "/fapi/v1/algoOrder", {"reduceOnly": "true"},
             ("ok", {"algoId": 13, "algoStatus": "WORKING"})),
            ("POST", "/fapi/v1/algoOrder", {"reduceOnly": "true"},
             ("ok", {"algoId": 14, "algoStatus": "WORKING"})))
        engine.note_user_event(_trade(
            orders, entry, "BUY", "FILLED", 0.033, 0.083,
            100.50, 0.020, 771002))
        assert session.ledger.position_qty() == 0.083
        assert session._position["protected"] is True
        stop2, tgt2 = session._position["legs"]
        assert (stop2, tgt2) != (stop1, tgt1)  # replaced, not duplicated.
        assert engine.order_status(stop1).state == "cancelled"
        assert engine.order_status(stop2).qty == 0.083
        assert len(_algos()) == 4 and len(_deletes()) == 2
        seen_nets.append(session.ledger.position_qty())

        # -- partial target exit 0.050: no churn, no over-close. -------
        engine.note_user_event(_trade(
            orders, tgt2, "SELL", "PARTIALLY_FILLED", 0.050, 0.050,
            101.50, 0.015, 772001))
        assert session.ledger.position_qty() == pytest.approx(0.033)
        assert session._position["protected"] is True
        assert session._position["legs"] == [stop2, tgt2]  # unchanged.
        assert len(_algos()) == 4 and len(_deletes()) == 2  # no churn.
        assert engine.order_status(tgt2).state == "partial"
        seen_nets.append(session.ledger.position_qty())

        # -- final target exit 0.033: sibling terminates, flat. --------
        transport.append(
            ("DELETE", "/fapi/v1/algoOrder",
             {"origClientAlgoId": stop2}, ("ok", {})),
            ("GET", "/fapi/v2/account", None,
             ("ok", _flat_account(ready))))
        engine.note_user_event(_trade(
            orders, tgt2, "SELL", "FILLED", 0.033, 0.083,
            101.50, 0.010, 772002))
        assert session.ledger.position_qty() == 0.0  # exact, never over.
        seen_nets.append(session.ledger.position_qty())
        assert all(net >= 0.0 for net in seen_nets)  # LONG never flips.
        assert session._position is None  # released on full agreement.
        assert engine.order_status(tgt2).state == "filled"
        assert engine.order_status(stop2).state == "cancelled"
        assert len(_deletes()) == 3

        # -- 7-leg reconciled flatness. ---------------------------------
        transport.append(
            ("GET", "/fapi/v2/account", None,
             ("ok", _flat_account(ready))))
        snapshot = engine.account_snapshot()
        assert snapshot is not None and snapshot.complete is True
        assert snapshot.positions == ()
        fills = store._db.execute(
            "SELECT execution_id FROM execution_events"
            " WHERE run_id='ca-exit' AND kind='fill'").fetchall()
        assert len(fills) == 4  # 2 entry partials + 2 exit partials.
        assert all(r[0].startswith("binanceusdm/") for r in fills)
        assert len({r[0] for r in fills}) == 4
        from cryptobot.reporting.schemas import load_fills
        strict = load_fills(session.workdir / "fills.jsonl")
        assert len(strict) == 4  # strict schema: no dup/foreign rows.
        assert session.ledger.has_position() is False
        assert session.policy.booked_net(rid) == 0.0
        assert session.policy._state.open_position is False
        assert session.policy._state.reservations == {}
        assert store.open_commands("ca-exit") == []
        transport.assert_empty()
    finally:
        store.close()
