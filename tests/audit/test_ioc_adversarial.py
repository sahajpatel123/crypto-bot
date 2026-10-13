"""Independent adversarial IOC probes (Worker 5, 30min §4).

Own authorship, own scenarios: the directive §4 acceptance list —
both sides, marketable/nonmarketable IOC, partial + canceled
remainder, queued expiry, price-band enforcement, cancel/fill races,
late-but-valid exactly-once, protection after partials, reduce-only
exits, and emergency-exit latency labeling.

Drive rule: canonical LIMIT (nautilus IOC) resolves at due time
against the standing arrival book — bare advance past due resolves it,
no tick required (CORR directive Worker-1 supersedes the earlier
tick-driven pin); other kinds resolve on ticks/advance as before. So
arrival-vs-later-tick separation is exactly what these probes test.
Each test fails before its fix and passes after; open items carry
strict-xfail with owner in tests/audit/conftest.py.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

nautilus = pytest.importorskip("nautilus_trader")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.adapters import NautilusPaperEngine  # noqa: E402
from cryptobot.app.engine import EngineOrder  # noqa: E402

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _engine(submit_delay_ms=0, fill_delay_ms=50, **kw):
    kw.setdefault("taker_bps", 5.0)
    kw.setdefault("now_utc", lambda: T0)
    engine = NautilusPaperEngine(
        submit_delay_ms=submit_delay_ms, fill_delay_ms=fill_delay_ms, **kw)
    engine.add_instrument("BTCUSDT", price_precision=2, size_precision=3,
                          tick_size=0.01, step_size=0.001, ts_utc=T0)
    return engine


def _qt(engine, ms, bid, ask, bid_size=1.0, ask_size=1.0):
    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.model.objects import Price, Quantity
    tick = QuoteTick(
        instrument_id=engine.instrument_id("BTCUSDT"),
        bid_price=Price(bid, 2), ask_price=Price(ask, 2),
        bid_size=Quantity(bid_size, 3), ask_size=Quantity(ask_size, 3),
        ts_event=int((T0 + timedelta(milliseconds=ms)).timestamp() * 1e9),
        ts_init=int((T0 + timedelta(milliseconds=ms)).timestamp() * 1e9),
    )
    engine.feed(tick)
    return tick


def _order(side, qty, kind="LIMIT", price=None, **kw):
    kw.setdefault("reservation_id", "w5-ioc-1")
    kw.setdefault("role", "entry")
    return EngineOrder(instrument="BTCUSDT", side=side, qty=qty,
                       kind=kind, price=price, **kw)


def _fills_for(engine, cid):
    return [e for e in engine.poll() if e.kind == "fill"
            and e.payload.client_order_id == cid]


def test_nonmarketable_buy_ioc_dead_at_arrival_no_late_revival():
    """Directive §4 case: BUY capped 100.50 arrives vs ask 101 and must
    be CANCELED before any later tick; ask 100 at T0+1s revives nothing."""
    engine = _engine(submit_delay_ms=50, fill_delay_ms=50)
    _qt(engine, 0, 99.0, 101.0)
    cid = engine.submit(_order("BUY", 0.1, price=100.50))
    engine.advance_to(T0 + timedelta(milliseconds=200))
    assert engine.order_status(cid) == "CANCELED", (
        "nonmarketable IOC still alive after arrival")
    assert engine.filled_qty(cid) == 0.0
    _qt(engine, 1000, 99.0, 100.0)
    assert engine.filled_qty(cid) == 0.0, "canceled IOC revived on later ask"
    assert _fills_for(engine, cid) == []
    assert engine.stats["ioc_artifact_corrected"] == 0


def test_nonmarketable_sell_ioc_dead_at_arrival_no_late_revival():
    """SELL mirror: capped 99.50 vs bid 99 dies at arrival; bid 100
    later revives nothing."""
    engine = _engine(submit_delay_ms=50, fill_delay_ms=50)
    _qt(engine, 0, 99.0, 101.0)
    cid = engine.submit(_order("SELL", 0.1, price=99.50))
    engine.advance_to(T0 + timedelta(milliseconds=200))
    assert engine.order_status(cid) == "CANCELED", (
        "nonmarketable IOC still alive after arrival")
    assert engine.filled_qty(cid) == 0.0
    _qt(engine, 1000, 100.0, 101.0)
    assert engine.filled_qty(cid) == 0.0, "canceled IOC revived on later bid"
    assert engine.stats["ioc_artifact_corrected"] == 0


def test_marketable_ioc_fills_on_arrival_tick_at_arrival_prices():
    """Marketable IOC, due-time semantics (CORR directive Worker-1
    supersedes the earlier tick-driven pin): due at T0+10ms against the
    standing 99/101 book, the advance to T0+200ms fills BUY at ask 101
    and SELL at bid 99 with no tick required; later ticks — including a
    moved one — fill nothing more, exactly once each."""
    engine = _engine(submit_delay_ms=10, fill_delay_ms=10)
    _qt(engine, 0, 99.0, 101.0)
    buy = engine.submit(_order("BUY", 0.1, price=101.50,
                               reservation_id="w5-ioc-b"))
    sell = engine.submit(_order("SELL", 0.1, price=98.50,
                                reservation_id="w5-ioc-s"))
    engine.advance_to(T0 + timedelta(milliseconds=200))
    assert engine.filled_qty(buy) == 0.1, "marketable BUY not filled at due time"
    assert engine.filled_qty(sell) == 0.1, "marketable SELL not filled at due time"
    events = engine.poll()
    buys = [e for e in events if e.kind == "fill"
            and e.payload.client_order_id == buy]
    sells = [e for e in events if e.kind == "fill"
             and e.payload.client_order_id == sell]
    assert len(buys) == 1 and buys[0].payload.price == 101.0, (
        f"BUY filled off arrival book: {buys!r}")
    assert len(sells) == 1 and sells[0].payload.price == 99.0, (
        f"SELL filled off arrival book: {sells!r}")
    _qt(engine, 300, 99.0, 101.0)
    assert engine.filled_qty(buy) == 0.1, "BUY filled twice"
    assert engine.filled_qty(sell) == 0.1, "SELL filled twice"
    _qt(engine, 1000, 100.0, 102.0)
    assert engine.filled_qty(buy) == 0.1, "BUY revived on moved tick"
    assert engine.filled_qty(sell) == 0.1, "SELL revived on moved tick"
    assert _fills_for(engine, buy) == []
    assert _fills_for(engine, sell) == []


def test_partial_fill_cancels_remainder_without_resting():
    """Ask depth 0.05 against BUY 0.1: partial 0.05 fills on the tick,
    remainder cancels; fresh depth next tick fills nothing more."""
    engine = _engine()
    _qt(engine, 0, 99.0, 101.0, ask_size=0.05)
    cid = engine.submit(_order("BUY", 0.1, price=101.50))
    _qt(engine, 100, 99.0, 101.0, ask_size=0.05)
    assert engine.filled_qty(cid) == 0.05
    assert engine.order_status(cid) == "CANCELED"
    _qt(engine, 1000, 99.0, 101.0, ask_size=1.0)
    assert engine.filled_qty(cid) == 0.05, "remainder rested into next tick"


def test_queued_expiry_kills_order_past_window():
    """STOP_MARKET with GTD expiry untriggered at the expiry tick dies
    expired with no fill. Continuous-tick drive (realistic streams tick
    through expiry; a lone 6s gap-tick both delivers and skips expiry
    evaluation — noted for W1/W2, not asserted here)."""
    engine = _engine()
    _qt(engine, 0, 99.0, 101.0)
    cid = engine.submit(_order(
        "BUY", 0.1, kind="STOP_MARKET", stop_price=150.0,
        expire_at_utc=T0 + timedelta(seconds=5)))
    _qt(engine, 1000, 99.0, 101.0)
    engine.advance_to(T0 + timedelta(seconds=6))
    _qt(engine, 6000, 99.0, 101.0)
    assert engine.order_status(cid) == "EXPIRED"
    assert engine.filled_qty(cid) == 0.0
    kinds = [e.kind for e in engine.poll()
             if getattr(e.payload, "client_order_id", None) == cid]
    assert "expire" in kinds


def test_price_band_bounds_the_cross_at_arrival():
    """submit_protected BUY limited 100.50 vs ask 101 is dead at
    arrival; a later ask 100 must not fill the dead order."""
    engine = _engine(submit_delay_ms=10, fill_delay_ms=10)
    _qt(engine, 0, 99.0, 101.0)
    cid = engine.submit_protected(_order("BUY", 0.1), 100.50)
    engine.advance_to(T0 + timedelta(milliseconds=200))
    assert engine.order_status(cid) == "CANCELED", (
        "out-of-band protected order alive after arrival")
    assert engine.filled_qty(cid) == 0.0
    _qt(engine, 1000, 99.0, 100.0)
    assert engine.filled_qty(cid) == 0.0, "dead protected order filled late"


def test_queued_cancel_wins_deterministically_no_phantom_fill():
    """Cancel while the submit is still queued drops it: after arrival
    time plus a favorable tick, zero fills and no phantom order."""
    engine = _engine(submit_delay_ms=500, fill_delay_ms=10)
    _qt(engine, 0, 99.0, 101.0)
    cid = engine.submit(_order("BUY", 0.1, price=101.50))
    assert engine.resolve(cid) is None  # still queued, nothing sent.
    engine.cancel(cid, "w5:queued-race")
    engine.advance_to(T0 + timedelta(milliseconds=800))
    _qt(engine, 900, 99.0, 100.0)
    assert engine.filled_qty(cid) == 0.0
    assert _fills_for(engine, cid) == []
    with pytest.raises(KeyError):
        engine.order_status(cid)


def test_late_but_valid_fill_reports_exactly_once():
    """A genuine fill polled late still books exactly once: one fill
    event, stable filled_qty across drains, taker liquidity."""
    engine = _engine()
    _qt(engine, 0, 99.0, 101.0)
    cid = engine.submit(_order("BUY", 0.1, price=101.50))
    _qt(engine, 100, 99.0, 101.0)
    first = _fills_for(engine, cid)
    assert len(first) == 1
    assert engine.filled_qty(cid) == 0.1
    assert _fills_for(engine, cid) == [], "fill reported twice"
    assert engine.filled_qty(cid) == 0.1
    assert first[0].payload.liquidity == "taker"


def test_protection_attaches_to_filled_not_ordered_qty():
    """After a 0.05 partial of 0.1, both protection legs cover 0.05;
    attaching to a zero-fill entry is refused."""
    engine = _engine()
    _qt(engine, 0, 99.0, 101.0, ask_size=0.05)
    cid = engine.submit(_order("BUY", 0.1, price=101.50))
    _qt(engine, 100, 99.0, 101.0, ask_size=0.05)
    assert engine.filled_qty(cid) == 0.05
    legs = engine.attach_protection(cid, 95.0, 105.0)
    assert len(legs) == 2
    got = {s.client_order_id: s.qty for s in engine.open_orders()}
    assert got[legs[0]] == 0.05 and got[legs[1]] == 0.05, got
    zero = engine.submit(_order("BUY", 0.1, price=90.0,
                                reservation_id="w5-ioc-z"))
    _qt(engine, 300, 99.0, 101.0)
    assert engine.filled_qty(zero) == 0.0
    with pytest.raises(ValueError):
        engine.attach_protection(zero, 95.0, 105.0)


def test_reduce_only_exit_closes_without_flipping():
    """Reduce-only SELL 0.2 against a 0.1 long closes 0.1 flat; a
    reduce-only exit with no position creates no short."""
    engine = _engine()
    _qt(engine, 0, 99.0, 101.0)
    entry = engine.submit(_order("BUY", 0.1, price=101.50))
    _qt(engine, 100, 99.0, 101.0)
    assert engine.filled_qty(entry) == 0.1
    out = engine.submit(_order("SELL", 0.2, kind="MARKET",
                               reduce_only=True, role="target",
                               reservation_id="w5-ioc-x"))
    _qt(engine, 500, 99.0, 101.0)
    assert engine.filled_qty(out) == 0.1
    naked = engine.submit(_order("SELL", 0.1, kind="MARKET",
                                 reduce_only=True, role="target",
                                 reservation_id="w5-ioc-n"))
    _qt(engine, 800, 99.0, 101.0)
    assert engine.filled_qty(naked) == 0.0, "reduce-only opened a short"


def test_emergency_exit_latency_is_labeled_not_silent():
    """submit_immediate refuses entries (control) and the engine
    assumptions disclose the zero-latency bypass so economics cannot
    silently depend on it."""
    engine = _engine(submit_delay_ms=50, fill_delay_ms=50)
    _qt(engine, 0, 99.0, 101.0)
    with pytest.raises(ValueError):
        engine.submit_immediate(_order("BUY", 0.1, price=101.50))
    disclosed = " ".join(engine.assumptions).lower()
    assert "submit_immediate" in disclosed and "bypass" in disclosed, (
        f"bypass undisclosed in assumptions: {engine.assumptions!r}")
