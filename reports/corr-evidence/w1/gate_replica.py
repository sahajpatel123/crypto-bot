"""Replica of manager-described gate test_corr_review_acceptance (M1 contract).

IOC BUY/SELL/partial: fill @arrival-touch by 200ms, remainder terminal
same opportunity, nothing later. Runs from /tmp against the worktree;
NOT committed (manager owns the gate file).
"""
import sys
sys.path.insert(0, "/tmp/cryto-bot-w1-corr/src")
sys.path.insert(0, "/tmp/cryto-bot-w1-corr/tests/unit")
from datetime import timedelta
from test_ioc_arrival import _engine, _quote, _drain, T0
from cryptobot.app.engine import EngineOrder

def lim(side, qty, price):
    return EngineOrder(instrument="BTCUSDT", side=side, qty=qty,
                       kind="LIMIT", price=price, role="entry")

# BUY full
e = _engine(submit_delay_ms=50, fill_delay_ms=50)
_quote(e, T0, 99.0, 101.0)
b = e.submit(lim("BUY", 0.001, 101.50))
e.advance_to(T0 + timedelta(milliseconds=200))
d = _drain(e)
f = [x for x in d if x.kind == "fill"]
assert len(f) == 1 and f[0].payload.price == 101.0, d
assert f[0].payload.qty == 0.001
_quote(e, T0 + timedelta(seconds=10), 89.0, 90.0)
assert [x.kind for x in _drain(e)].count("fill") == 0
assert e.filled_qty(b) == 0.001
print("BUY ok: fill @101 by 200ms, nothing later")

# SELL full
e = _engine(submit_delay_ms=50, fill_delay_ms=50)
_quote(e, T0, 99.0, 101.0)
s = e.submit(lim("SELL", 0.001, 98.50))
e.advance_to(T0 + timedelta(milliseconds=200))
d = _drain(e)
f = [x for x in d if x.kind == "fill"]
assert len(f) == 1 and f[0].payload.price == 99.0, d
_quote(e, T0 + timedelta(seconds=10), 110.0, 111.0)
assert [x.kind for x in _drain(e)].count("fill") == 0
print("SELL ok: fill @99 by 200ms, nothing later")

# BUY partial: thin arrival ask -> partial + terminal remainder same opp
e = _engine(submit_delay_ms=50, fill_delay_ms=50)
_quote(e, T0, 99.0, 101.0, ask_size=0.001)
p = e.submit(lim("BUY", 0.003, 101.50))
e.advance_to(T0 + timedelta(milliseconds=200))
d = _drain(e)
f = [x for x in d if x.kind == "fill"]
t = [x for x in d if x.kind in ("cancel", "reject", "expire")]
assert len(f) == 1 and 0.0 < e.filled_qty(p) < 0.003, d
assert len(t) == 1, d  # remainder terminal SAME opportunity
part = e.filled_qty(p)
_quote(e, T0 + timedelta(seconds=10), 89.0, 90.0)
assert [x.kind for x in _drain(e)].count("fill") == 0
assert e.filled_qty(p) == part
print(f"PARTIAL ok: {part} + terminal remainder by 200ms, frozen")
print("GATE REPLICA: ALL PASS")
