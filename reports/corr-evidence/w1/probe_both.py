"""Map old-vs-new delivery/matching across submit paths (run on both trees)."""
import sys
TREE = sys.argv[1]
sys.path.insert(0, f"{TREE}/src")
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

def qt(e, ms, bid=99.0, ask=101.0):
    ns = int((T0 + timedelta(milliseconds=ms)).timestamp() * 1e9)
    e.feed(QuoteTick(e.instrument_id("BTCUSDT"), Price(bid, 2), Price(ask, 2),
                     Quantity(1.0, 3), Quantity(1.0, 3),
                     ts_event=ns, ts_init=ns))

def drain(e):
    out = []
    for _ in range(10):
        b = e.poll()
        if not b:
            break
        out.extend(b)
    return [(x.kind, getattr(x.payload, "price", getattr(x.payload, "reason", ""))) for x in out]

def lim(side="BUY", price=101.50):
    return EngineOrder(instrument="BTCUSDT", side=side, qty=0.001,
                       kind="LIMIT", price=price, role="entry")
def mkt():
    return EngineOrder(instrument="BTCUSDT", side="BUY", qty=0.001,
                       kind="MARKET", role="entry")

print("L1 delay-0 MKT, no book, quote@T0:", end=" ")
e = eng(); c = e.submit(mkt()); qt(e, 0); print(drain(e), "filled:", e.filled_qty(c))

print("L2 ruling: delay-10 IOC, book, adv200:", end=" ")
e = eng(10, 10); qt(e, 0); b = e.submit(lim()); e.advance_to(T0 + timedelta(milliseconds=200))
print("filled:", e.filled_qty(b), drain(e))

print("L3 P-A: delay-0 IOC, book, adv200:", end=" ")
e = eng(); qt(e, 0); b = e.submit(lim()); e.advance_to(T0 + timedelta(milliseconds=200))
print("filled:", e.filled_qty(b), drain(e))

print("L4 delay-0 MKT, book, quote@T+1000:", end=" ")
e = eng(); qt(e, 0); c = e.submit(mkt()); qt(e, 1000, 100.0, 102.0)
print(drain(e), "filled:", e.filled_qty(c))

print("L5 delay-50/50 IOC, book, adv200, quote@10s(89/90):", end=" ")
e = eng(50, 50); qt(e, 0); b = e.submit(lim())
e.advance_to(T0 + timedelta(milliseconds=200)); d1 = drain(e)
qt(e, 10000, 89.0, 90.0); d2 = drain(e)
print("at200:", d1, "at10s:", d2, "filled:", e.filled_qty(b))
