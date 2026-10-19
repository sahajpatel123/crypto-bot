"""JOINT re-adopt path (scratch-only): stream dies pre-fill; restart
reconciles by durable id via lookup; the adopted fill books through
the normal Session handler and drives protection. Same overlay as
the main joint proof.
"""
import sys
from pathlib import Path

sys.path.insert(0, "tests")
sys.path.insert(0, "src")

sys.path.insert(0, "/tmp")
import importlib.util
spec = importlib.util.spec_from_file_location(
    "joint", "/tmp/w1rel-joint-proof.py")
joint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(joint)
import venue_fixtures as venues


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
    session, store = joint._session(tmp_path, engine, "joint-t3")
    from cryptobot.coordination.selector import Candidate
    session._maybe_admit(
        [Candidate("S1", joint._intent(session.now_utc()))])
    entry_id = session._position["entry_pre_id"]
    qty = next(float(p["quantity"]) for m, pa, p, _ in transport.requests
               if m == "POST" and pa == "/fapi/v1/order")
    trade = {"id": 777001, "qty": f"{qty:.3f}", "price": "100.50",
             "commission": "0.03", "commissionAsset": "USDT"}
    engine2, transport2 = venues.make_engine(tmp_path, [
        ("GET", "/fapi/v1/order", {"origClientOrderId": entry_id},
         ("ok", {"orderId": 12345, "status": "FILLED",
                 "executedQty": f"{qty:.3f}", "origQty": f"{qty:.3f}"})),
        ("GET", "/fapi/v1/userTrades", {"orderId": 12345},
         ("ok", [trade]))])
    adopted = []

    def _tee(event):
        adopted.append(event)
        session._on_engine_event(event)

    # Post-merge: the adopted fill drives protection on the original
    # engine (lookup + trades + 2 reduce-only algos).
    transport.append(
        ("GET", "/fapi/v1/order", {"origClientOrderId": entry_id},
         ("ok", {"orderId": 12345, "status": "FILLED",
                 "executedQty": f"{qty:.3f}", "origQty": f"{qty:.3f}"})),
        ("GET", "/fapi/v1/userTrades", {"orderId": 12345},
         ("ok", [trade])),
        ("POST", "/fapi/v1/algoOrder", {"reduceOnly": "true"},
         ("ok", {"algoId": 11, "algoStatus": "WORKING"})),
        ("POST", "/fapi/v1/algoOrder", {"reduceOnly": "true"},
         ("ok", {"algoId": 12, "algoStatus": "WORKING"})))
    engine2.recover(_tee)
    fills = [e for e in adopted if e.kind == "fill"]
    assert len(fills) == 1
    assert fills[0].payload.execution_id.endswith("/BTCUSDT/777001")
    assert fills[0].payload.client_order_id == entry_id
    posts = [r for r in transport2.requests
             if r[0] == "POST" and r[1] == "/fapi/v1/order"]
    assert posts == []
    assert engine2.order_status(entry_id).state == "filled"
    transport2.assert_empty()
    # And the normal Session booked + protected from the adoption.
    assert abs(session.ledger.position_qty() - qty) < 1e-9
    assert session._position["protected"] is True
    assert len(session._position["legs"]) == 2
    transport.assert_empty()
    print(f"JOINT-T3-OK readopted={fills[0].payload.execution_id} "
          f"ledger={session.ledger.position_qty():.3f} protected "
          f"no-resubmit")
    store.close()


if __name__ == "__main__":
    main(sys.argv[1])
