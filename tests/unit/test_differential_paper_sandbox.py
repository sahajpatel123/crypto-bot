"""F1.5: paper engine vs sandbox venue differential (declared tolerance).

Same touch (frozen sandbox book), same MARKET/LIMIT-IOC orders both
sides: fill qty must match exactly; fill price within 1 tick
(nautilus always slips one adverse tick; sandbox fills at touch);
fees within relative tolerance of the price gap. Both seams are
taker-5bps; the drift top-up (B#9) lives at session booking, not in
engine fill prices, so engine prices compare directly.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

T0 = datetime(2026, 10, 1, tzinfo=UTC)
TICK = 0.10
# Declared tolerance: 1 slip tick (nautilus always-slip) + half a tick
# (paper feed rounds the sandbox touch to tick grid).
TOL_PX = 1.5 * TICK + 1e-9


def _paper_with_book(touch_bid, touch_ask):
    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.model.objects import Price, Quantity

    from cryptobot.adapters.paper_engine import NautilusPaperEngine

    engine = NautilusPaperEngine(submit_delay_ms=0, fill_delay_ms=1)
    engine.add_instrument("BTCUSDT", price_precision=2, size_precision=3,
                          tick_size=TICK, step_size=0.001, ts_utc=T0)

    def quote(i):
        engine.feed(QuoteTick(
            instrument_id=engine.instrument_id("BTCUSDT"),
            bid_price=Price(touch_bid, 2), ask_price=Price(touch_ask, 2),
            bid_size=Quantity(10.0, 3), ask_size=Quantity(10.0, 3),
            ts_event=int((T0 + timedelta(seconds=i)).timestamp() * 1e9),
            ts_init=int((T0 + timedelta(seconds=i)).timestamp() * 1e9)))

    return engine, quote


def _paper_fill(engine, quote, side, qty, kind="MARKET", price=None):
    from cryptobot.app.engine import EngineOrder

    quote(0)
    engine.submit(EngineOrder("BTCUSDT", side, qty, kind, price=price,
                              reservation_id="r-1", role="entry"))
    fills = []
    # Generous tick bound: fill_delay is sim-time, but loaded CI
    # must never flake on scheduling (ticks are 1s sim-time each).
    for i in range(1, 16):
        quote(i)
        fills += [e for e in engine.poll() if e.kind == "fill"]
        if fills:
            break
    assert fills, f"paper {side} {kind} never filled"
    return fills[0].payload


def test_market_fills_agree_within_tick():
    from cryptobot.adapters.sandbox_venue import SandboxVenue

    frozen_ms = 1_760_000_000_000
    sandbox = SandboxVenue()
    sandbox.now_ms = lambda: frozen_ms
    book = sandbox.book("BTCUSDT")
    bid = round(book["bid"] / TICK) * TICK
    ask = round(book["ask"] / TICK) * TICK

    for side, _touch in (("BUY", ask), ("SELL", bid)):
        engine, quote = _paper_with_book(bid, ask)
        paper = _paper_fill(engine, quote, side, 0.01)
        sb = sandbox.place_order(
            {"symbol": "BTCUSDT", "side": side, "type": "MARKET",
             "quantity": 0.01,
             "newClientOrderId": f"sb-{side}"})
        assert paper.qty == float(sb["executedQty"]) == 0.01
        sb_avg = sandbox.orders[str(sb["orderId"])]["avg"]
        exact = book["ask"] if side == "BUY" else book["bid"]
        assert sb_avg == exact  # sandbox fills at exact touch
        assert abs(paper.price - sb_avg) <= TOL_PX, (paper.price, sb_avg)
        _pf, sf = paper.fee, 0.01 * paper.price * 5.0 / 10000.0
        assert abs(paper.fee - sf) <= sf * 0.05 + 1e-9, (paper.fee, sf)


def test_limit_ioc_within_size_agrees():
    from cryptobot.adapters.sandbox_venue import SandboxVenue

    frozen_ms = 1_760_000_100_000
    sandbox = SandboxVenue()
    sandbox.now_ms = lambda: frozen_ms
    book = sandbox.book("BTCUSDT")
    bid = round(book["bid"] / TICK) * TICK
    ask = round(book["ask"] / TICK) * TICK

    engine, quote = _paper_with_book(bid, ask)
    paper = _paper_fill(engine, quote, "BUY", 0.01, kind="LIMIT",
                        price=ask)
    sb = sandbox.place_order(
        {"symbol": "BTCUSDT", "side": "BUY", "type": "LIMIT",
         "quantity": 0.01, "price": book["ask"], "timeInForce": "IOC",
         "newClientOrderId": "sb-ioc"})
    assert sb["status"] == "FILLED"
    assert paper.qty == float(sb["executedQty"]) == 0.01
    sb_avg = sandbox.orders[str(sb["orderId"])]["avg"]
    assert sb_avg == book["ask"]
    assert abs(paper.price - sb_avg) <= TOL_PX
