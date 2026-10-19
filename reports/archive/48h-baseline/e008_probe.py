"""Manager-independent E-008 probes (own script, own assertions)."""
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/tmp/cryto-bot-w2-e008/src")

from cryptobot.adapters import NautilusPaperEngine
from cryptobot.app.engine import EngineOrder

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _engine(**kw):
    kw.setdefault("taker_bps", 5.0)
    kw.setdefault("now_utc", lambda: T0)
    kw.setdefault("submit_delay_ms", 0)
    kw.setdefault("fill_delay_ms", 1)
    kw.setdefault("starting_balance_usdt", 10_000.0)
    e = NautilusPaperEngine(**kw)
    e.add_instrument("BTCUSDT", price_precision=2, size_precision=3,
                     tick_size=0.01, step_size=0.001, ts_utc=T0)
    return e


def _quote(engine, i, bid, ask, qty=1.0):
    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.model.objects import Price, Quantity
    tick = QuoteTick(
        instrument_id=engine.instrument_id("BTCUSDT"),
        bid_price=Price(bid, 2), ask_price=Price(ask, 2),
        bid_size=Quantity(qty, 3), ask_size=Quantity(qty, 3),
        ts_event=int((T0 + timedelta(seconds=i)).timestamp() * 1e9),
        ts_init=int((T0 + timedelta(seconds=i)).timestamp() * 1e9),
    )
    engine.feed(tick)


def fills_of(engine):
    out = []
    for ev in engine.poll():
        if ev.kind == "fill":
            out.append(ev.payload)
    return out


# 1. CEO probe: mark must never be a fill price.
e = _engine()
e.note_mark("BTCUSDT", 60000.0)
assert e.valuation_mark("BTCUSDT") == 60000.0
_quote(e, 1, 59999.0, 60001.0)
e.submit(EngineOrder(instrument="BTCUSDT", side="BUY", qty=0.1,
                     kind="MARKET", role="entry"))
_quote(e, 2, 59999.0, 60001.0)
f = fills_of(e)
assert len(f) == 1 and abs(f[0].price - 60001.0) < 1e-6, f
print("PROBE 1 (market crosses ask, not mark):", f[0].price)

# 2. Protected limit at the mark cancels when touch cannot be lifted.
e2 = _engine()
e2.note_mark("BTCUSDT", 60000.0)
_quote(e2, 1, 59999.0, 60001.0)
cid = e2.submit_protected(
    EngineOrder(instrument="BTCUSDT", side="BUY", qty=0.1, kind="MARKET",
                role="entry"), 60000.0)
_quote(e2, 2, 59999.0, 60001.0)
evs = e2.poll()
kinds = [ev.kind for ev in evs]
assert "fill" not in kinds, kinds
assert any(k in ("cancel", "expire", "reject") for k in kinds), kinds
print("PROBE 2 (protected@mark cancels):", kinds)

# 3. Margin cycle through the sim account.
e3 = _engine(default_leverage=5)
m0 = e3.account_margin()
assert m0 == (10000.0, 10000.0), m0
_quote(e3, 1, 59999.0, 60001.0)
e3.submit(EngineOrder(instrument="BTCUSDT", side="BUY", qty=0.1,
                      kind="MARKET", role="entry"))
_quote(e3, 2, 59999.0, 60001.0)
assert fills_of(e3), "entry did not fill"
m1 = e3.account_margin()
assert m1[0] < 10000.0 and m1[1] < m1[0], m1  # locked + maint held
print("PROBE 3 (margin locks on open):", m0, "->", m1)

# 4. Strict replay fails closed on shuffled history.
e4 = _engine(strict_replay=True)
_quote(e4, 5, 59999.0, 60001.0)
try:
    _quote(e4, 2, 59999.0, 60001.0)
    raise SystemExit("STRICT REPLAY DID NOT RAISE")
except ValueError as exc:
    print("PROBE 4 (strict replay raises):", str(exc)[:60])

# 5. Live default restamps instead of raising.
e5 = _engine()
_quote(e5, 5, 59999.0, 60001.0)
_quote(e5, 2, 59999.0, 60001.0)
assert e5.stats["restamped_ticks"] == 1
print("PROBE 5 (lenient restamp counted): ok")

print("ALL MANAGER PROBES GREEN")
