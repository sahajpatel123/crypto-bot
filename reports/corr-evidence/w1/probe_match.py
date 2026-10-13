"""Decisive probe: does nautilus match on submit-processing without new data?"""
import sys
from datetime import timedelta

sys.path.insert(0, "/tmp/cryto-bot-w1-corr/src")
sys.path.insert(0, "/tmp/cryto-bot-w1-corr/tests/unit")

from test_ioc_arrival import _engine, _quote, _drain, T0
from cryptobot.app.engine import EngineOrder

# P-A: marketable IOC, advance past latency with NO data — fill or rest?
e = _engine()  # 0 submit delay, 1ms fill latency.
_quote(e, T0, 99.0, 101.0)
c = e.submit(EngineOrder(instrument="BTCUSDT", side="BUY", qty=0.001,
                         kind="LIMIT", price=101.50, role="entry"))
e.advance_to(T0 + timedelta(milliseconds=5))
print("P-A after advance (no data):",
      [(x.kind, getattr(x.payload, "price", None)) for x in _drain(e)],
      "status:", [s.state for s in e.open_orders()
                  if s.client_order_id == c], flush=True)
_quote(e, T0 + timedelta(seconds=10), 89.0, 90.0)
print("P-A after 10s quote:",
      [(x.kind, getattr(x.payload, "price", None)) for x in _drain(e)],
      flush=True)

# P-B: with submit delay (due-stepping question): submit at T0 due T0+50,
# advance to T0+200 with no data — where/when does it match?
e2 = _engine(submit_delay_ms=50, fill_delay_ms=50)
_quote(e2, T0, 99.0, 101.0)
c2 = e2.submit(EngineOrder(instrument="BTCUSDT", side="BUY", qty=0.001,
                           kind="LIMIT", price=101.50, role="entry"))
e2.advance_to(T0 + timedelta(milliseconds=200))
print("P-B at T0+200 (no data):",
      [(x.kind, getattr(x.payload, "price", None)) for x in _drain(e2)],
      flush=True)
_quote(e2, T0 + timedelta(seconds=10), 89.0, 90.0)
print("P-B after 10s quote:",
      [(x.kind, getattr(x.payload, "price", None)) for x in _drain(e2)],
      flush=True)
