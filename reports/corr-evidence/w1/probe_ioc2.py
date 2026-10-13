"""Decisive probe: native IOC remainder handling + cancel-before-accept."""
import sys
sys.path.insert(0, "/tmp/cryto-bot-w1-corr/src")
sys.path.insert(0, "/tmp/cryto-bot-w1-corr/tests/unit")
from datetime import timedelta
from test_ioc_arrival import _engine, _quote, _drain, T0
from cryptobot.app.engine import EngineOrder

print("=== P1: partial IOC — who cancels the remainder? ===")
e = _engine()
_quote(e, T0, 99.0, 101.0, ask_size=0.0005)
c = e.submit(EngineOrder(instrument="BTCUSDT", side="BUY", qty=0.002,
                         kind="LIMIT", price=101.50, role="entry"))
_quote(e, T0 + timedelta(seconds=1), 99.0, 101.0, ask_size=5.0)
for ev in _drain(e):
    print(" ", ev.kind, repr(getattr(ev.payload, "reason", getattr(ev.payload, "price", ""))),
          getattr(ev.payload, "qty", ""))
print("  mirror:", e._status_of(e._orders[c]), "filled:", e.filled_qty(c),
      "stat:", e.stats["ioc_remainder_canceled"],
      "ioc_open:", dict(e._ioc_open), "accepted:", dict(e._ioc_accepted))

print("=== P2: explicit cancel right after submit — what is rejected? ===")
e2 = _engine()
_quote(e2, T0, 99.0, 101.0, ask_size=1.0)
c2 = e2.submit(EngineOrder(instrument="BTCUSDT", side="BUY", qty=0.001,
                           kind="LIMIT", price=101.50, role="entry"))
print("  venue_order_id at cancel time:", e2._orders[c2].venue_order_id,
      "status:", e2._orders[c2].status)
e2.cancel(c2, "test-early-cancel")
_quote(e2, T0 + timedelta(seconds=1), 99.0, 101.0, ask_size=5.0)
for ev in _drain(e2):
    p = ev.payload
    print(" ", ev.kind, repr(getattr(p, "reason", getattr(p, "price", ""))),
          {k: v for k, v in vars(p).items() if "id" in k.lower()})
print("  mirror:", e2._status_of(e2._orders[c2]), "filled:", e2.filled_qty(c2))

print("=== P3: cancel AFTER accept drains (late cancel vs fill race) ===")
e3 = _engine()
_quote(e3, T0, 99.0, 101.0, ask_size=1.0)
c3 = e3.submit(EngineOrder(instrument="BTCUSDT", side="BUY", qty=0.001,
                           kind="LIMIT", price=101.50, role="entry"))
e3.advance_to(T0 + timedelta(milliseconds=200))
print("  drain1:", [(ev.kind, getattr(ev.payload, "reason", "")) for ev in _drain(e3)])
print("  venue_order_id now:", e3._orders[c3].venue_order_id,
      "status:", e3._orders[c3].status)
