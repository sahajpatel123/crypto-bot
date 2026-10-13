"""Fixup probe: does bare-advance matching natively cancel a partial IOC remainder?"""
import sys
sys.path.insert(0, "/tmp/cryto-bot-w1-corr/src")
from datetime import datetime, timedelta, timezone
from cryptobot.adapters import NautilusPaperEngine
from cryptobot.app.engine import EngineOrder
from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.objects import Price, Quantity

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)

def eng(sub=0, fill=1):
    e = NautilusPaperEngine(taker_bps=5.0, now_utc=lambda: T0,
                            submit_delay_ms=sub, fill_delay_ms=fill)
    e.add_instrument("BTCUSDT", price_precision=2, size_precision=3,
                     tick_size=0.01, step_size=0.001, ts_utc=T0)
    return e

def qt(e, ms, bid=99.0, ask=101.0, bs=1.0, asz=1.0):
    ns = int((T0 + timedelta(milliseconds=ms)).timestamp() * 1e9)
    e.feed(QuoteTick(e.instrument_id("BTCUSDT"), Price(bid, 2), Price(ask, 2),
                     Quantity(bs, 3), Quantity(asz, 3), ts_event=ns, ts_init=ns))

def drain(e):
    out = []
    for _ in range(10):
        b = e.poll()
        if not b:
            break
        out.extend(b)
    return out

print("F1 partial IOC (qty 0.002, ask 0.001) + bare advance:")
e = eng()
qt(e, 0, asz=0.001)
c = e.submit(EngineOrder(instrument="BTCUSDT", side="BUY", qty=0.002,
                         kind="LIMIT", price=101.50, role="entry"))
e.advance_to(T0 + timedelta(milliseconds=200))
for ev in drain(e):
    p = ev.payload
    print("  ", ev.kind, getattr(p, "price", getattr(p, "reason", "")),
          getattr(p, "qty", ""))
print("   filled:", e.filled_qty(c), "mirror:", e._status_of(e._orders[c]),
      "stat:", e.stats["ioc_remainder_canceled"])
