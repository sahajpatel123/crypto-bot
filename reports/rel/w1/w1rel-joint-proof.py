"""JOINT Checkpoint-A proof (W1 Session e60efd0 + W2 injected venue).

Normal Session path, no booking shims: submit -> user-stream fill ->
bound Session handler books the ledger once -> protection attaches as
reduce-only venue algos -> restart rebuilds, re-adopts by durable id
with no resubmit and no double-book. SCRATCH-ONLY (overlay dir); the
committed W2 test scripts need the same lookup+trades dialogue added
(W2-owned file; delta reported to manager).
"""
import copy
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "tests")
sys.path.insert(0, "src")

import venue_fixtures as venues
from cryptobot.app.config import load_config
from cryptobot.app.session import Session
from cryptobot.app.store import RunStore
from cryptobot.coordination.exits import encode_exit_rule, ExitPolicy
from cryptobot.coordination.intent import (
    DataQuality, ForecastCost, Intent, Side)
from cryptobot.coordination.selector import Candidate

MECHANICS = "joint-mechanics"


def _config(tmp_path):
    text = open("configs/paper.toml").read()
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    text = text.replace("warmup_bars =", "warmup_bars = 3 #", 1)
    path = tmp_path / "test.toml"
    path.write_text(text)
    return load_config(path)


def _intent(now):
    return Intent(
        strategy="S1", version="0.1.0", instrument="BTCUSDT",
        side=Side.LONG, evidence_ts_utc=now,
        entry_low=100.0, entry_high=100.55,
        entry_expiry_utc=now + timedelta(seconds=60),
        invalidation_price=99.0,
        exit_rule=encode_exit_rule(ExitPolicy(
            stop_price=99.0, target_price=102.0,
            time_exit_utc=now + timedelta(seconds=600),
            policy_id="joint-a")),
        holding_limit_s=600,
        forecast_cost=ForecastCost(5.0, 5.0, 5.0, 1.0),
        evidence_ref=f"{MECHANICS}:1", data_quality=DataQuality.CLEAN)


def _session(tmp_path, engine, run_id):
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    session = Session(_config(tmp_path), store,
                      tmp_path / "runs" / run_id, run_id, engine=engine)
    now = datetime(2026, 10, 12, 6, 0, tzinfo=timezone.utc)
    session.clock.set_ms(int(now.timestamp() * 1000))
    session.policy.reconcile_day(120.0, 0.0)
    store.create_run(run_id, MECHANICS, "fp", str(session.workdir), None)
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


def main(tmp_path):
    tmp_path = Path(tmp_path)
    ready, orders = venues.ready_fixture(), venues.orders_fixture()
    engine, transport = venues.make_engine(
        tmp_path, [("GET", "/fapi/v2/account", None,
                    ("ok", ready["account"])),
                   ("GET", "/fapi/v1/openOrders", None, ("ok", [])),
                   ("GET", "/fapi/v1/openAlgoOrders", None, ("ok", []))]
        + venues.ready_script(ready) + [
            ("POST", "/fapi/v1/order", {"type": "LIMIT"},
             ("ok", orders["orderAck"]))])
    session, store = _session(tmp_path, engine, "joint-a")
    # NO booking shim: the Session bound its own _apply_engine_event.
    session._maybe_admit([Candidate("S1", _intent(session.now_utc()))])
    assert session._position is not None
    entry = session._position["entry_pre_id"]
    qty = next(float(p["quantity"]) for m, pa, p, _ in transport.requests
               if m == "POST" and pa == "/fapi/v1/order")
    assert qty * 100.0 >= 5.0
    print(f"admitted entry={entry} qty={qty:.3f}")
    # Post-merge dialogue: the stream push drives supervision
    # synchronously, so protection's lookup+trades+algos come first.
    trade = {"id": 777001, "qty": f"{qty:.3f}", "price": "100.50",
             "commission": "0.03", "commissionAsset": "USDT"}
    transport.append(
        ("GET", "/fapi/v1/order", {"origClientOrderId": entry},
         ("ok", {"orderId": 12345, "status": "FILLED",
                 "executedQty": f"{qty:.3f}", "origQty": f"{qty:.3f}"})),
        ("GET", "/fapi/v1/userTrades", {"orderId": 12345},
         ("ok", [trade])),
        ("POST", "/fapi/v1/algoOrder", {"reduceOnly": "true"},
         ("ok", {"algoId": 11, "algoStatus": "WORKING"})),
        ("POST", "/fapi/v1/algoOrder", {"reduceOnly": "true"},
         ("ok", {"algoId": 12, "algoStatus": "WORKING"})))
    stream = copy.deepcopy(orders["userStreamTrade"])
    stream["o"]["c"] = entry
    stream["o"]["l"] = stream["o"]["z"] = f"{qty:.3f}"
    stream["o"]["L"] = stream["o"]["ap"] = "100.50"
    stream["o"]["t"] = 777001
    engine.note_user_event(stream)
    assert session.ledger.has_position()
    assert abs(session.ledger.position_qty() - qty) < 1e-9
    rows = store._db.execute(
        "SELECT execution_id FROM execution_events WHERE run_id='joint-a'"
        " AND kind='fill'").fetchall()
    assert len(rows) == 1, rows
    assert rows[0][0].startswith("binanceusdm/"), rows
    assert rows[0][0].endswith("/BTCUSDT/777001"), rows
    assert session._position["protected"] is True
    assert len(session._position["legs"]) == 2
    algos = [r for r in transport.requests if r[1] == "/fapi/v1/algoOrder"]
    assert len(algos) == 2, transport.requests
    transport.assert_empty()
    print(f"live: ledger={session.ledger.position_qty():.3f} "
          f"fee={session.ledger.paid_costs():.6f} protected "
          f"legs={session._position['legs']} exec={rows[0][0]}")
    # Restart at exposure: rebuild replays the store anchor; the
    # recovery-adopted event for the same key is a dup no-op; the
    # venue dialogue reconciles by durable id (no resubmit).
    session._persist_local_state()
    store.close()
    stop_leg, tgt_leg = session._position["legs"]
    print(f"legs: {stop_leg} {tgt_leg}")

    def _algo_working(cid):
        row = copy.deepcopy(orders["algoQueryWorking"])
        row["clientAlgoId"] = cid
        row["executedQty"] = "0.000"
        return row

    engine2, transport2 = venues.make_engine(tmp_path, [
        ("GET", "/fapi/v1/algoOrder", {"origClientAlgoId": stop_leg},
         ("ok", _algo_working(stop_leg))),
        ("GET", "/fapi/v1/algoOrder", {"origClientAlgoId": tgt_leg},
         ("ok", _algo_working(tgt_leg)))])
    # Note: the filled entry needs no lookup — the fresh engine replays
    # its filled state from the journal and skips it in recover.
    store2 = RunStore(tmp_path / "runs" / "cryptobot.db")
    session2 = Session(session.config, store2, session.workdir,
                       "joint-a", engine=engine2)
    session2.clock.set_ms(int(session.now_utc().timestamp() * 1000))
    session2.policy.reconcile_day(120.0, 0.0)
    session2._rebuild_booking_state()
    engine2.recover(session2._engine_handler)
    session2._drain_engine()
    assert abs(session2.ledger.position_qty() - qty) < 1e-9
    assert abs(session2.policy.booked_net(
        session._position["reservation_id"]) - qty) < 1e-9
    fills = (session2.workdir / "fills.jsonl").read_text().splitlines()
    assert len(fills) == 1, fills
    posts = [r for r in transport2.requests
             if r[0] == "POST" and r[1] == "/fapi/v1/order"]
    assert posts == []
    transport2.assert_empty()
    assert session2._booking_blocked is None
    print(f"restart: ledger={session2.ledger.position_qty():.3f} "
          f"dup={session2._dup_events} blocked={session2._booking_blocked}")
    print("JOINT-A-OK fill-once protected restart-clean no-resubmit")
    store2.close()


if __name__ == "__main__":
    main(sys.argv[1])
