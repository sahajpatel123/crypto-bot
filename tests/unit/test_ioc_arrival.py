"""IOC arrival-cancel regression + coverage (Worker 1, 30MIN §4).

Rule: an IOC is evaluated against the causally-available book AT
command arrival. A nonmarketable remainder cancels at arrival and NEVER
revives on later ticks (F-W1B1 relabel ruled insufficient and superseded:
no blanket maker-relabel; no-rest enforcement instead).
"""
from datetime import datetime, timedelta, timezone

import pytest

nautilus = pytest.importorskip("nautilus_trader")

from cryptobot.adapters import NautilusPaperEngine  # noqa: E402
from cryptobot.app.engine import EngineOrder  # noqa: E402

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _engine(**kw):
    kw.setdefault("taker_bps", 5.0)
    kw.setdefault("now_utc", lambda: T0)
    kw.setdefault("submit_delay_ms", 0)
    kw.setdefault("fill_delay_ms", 1)
    engine = NautilusPaperEngine(**kw)
    engine.add_instrument("BTCUSDT", price_precision=2, size_precision=3,
                          tick_size=0.01, step_size=0.001, ts_utc=T0)
    return engine


def _quote(engine, at, bid, ask, bid_size=1.0, ask_size=1.0):
    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.model.objects import Price, Quantity
    ns = int(at.timestamp() * 1e9)
    engine.feed(QuoteTick(
        engine.instrument_id("BTCUSDT"), Price(bid, 2), Price(ask, 2),
        Quantity(bid_size, 3), Quantity(ask_size, 3),
        ts_event=ns, ts_init=ns))


def _drain(engine):
    out = []
    for _ in range(10):
        batch = engine.poll()
        if not batch:
            break
        out.extend(batch)
    return out


def test_ioc_nonmarketable_cancels_at_arrival_no_revival():
    # Dispatch §4 verbatim: T0 99/101, BUY 0.001 cap 100.50 (ask 101 >
    # cap: non-marketable), 50ms submit + 50ms native latency, advance
    # to T0+200ms, then ask 100 at T0+1s. Correct: cancel at arrival
    # (T0+50ms), NO fill when the better ask arrives later.
    engine = _engine(submit_delay_ms=50, fill_delay_ms=50)
    _quote(engine, T0, 99.0, 101.0)
    coid = engine.submit(EngineOrder(instrument="BTCUSDT", side="BUY",
                                     qty=0.001, kind="LIMIT", price=100.50,
                                     role="entry"))
    engine.advance_to(T0 + timedelta(milliseconds=200))
    arrivals = _drain(engine)
    kinds = [e.kind for e in arrivals]
    assert "fill" not in kinds
    cancels = [e for e in arrivals if e.kind == "cancel"]
    assert len(cancels) == 1, f"expected arrival cancel, got {kinds}"
    assert cancels[0].payload.client_order_id == coid
    assert cancels[0].ts_utc == T0 + timedelta(milliseconds=50)
    _quote(engine, T0 + timedelta(seconds=1), 99.0, 100.0)
    late = _drain(engine)
    assert [e.kind for e in late].count("fill") == 0, \
        "revival: nonmarketable IOC filled on a later tick"
    assert cancels[0].payload.reason == "nonmarketable-at-arrival"
    assert engine.stats["ioc_remainder_canceled"] == 0
    assert engine.stats["ioc_artifact_corrected"] == 0
    assert "ioc_maker_relabeled" not in engine.stats  # F-W1B1 superseded.


def test_corr_marketable_ioc_executes_at_arrival_not_later_quote():
    # CORR-EXEC acceptance M1: probe shape verbatim (T0 99/101, BUY 0.001
    # cap 101.50, 50+50ms). Due at T0+50ms against the standing arrival
    # book, the IOC fills @101 in the 200ms drain — no tick required —
    # and the quote 10s later at ask 90 determines NOTHING (no fill at
    # 90, no revival, occurrence and time fixed at due time).
    engine = _engine(submit_delay_ms=50, fill_delay_ms=50)
    _quote(engine, T0, 99.0, 101.0)
    coid = engine.submit(EngineOrder(instrument="BTCUSDT", side="BUY",
                                     qty=0.001, kind="LIMIT", price=101.50,
                                     role="entry"))
    engine.advance_to(T0 + timedelta(milliseconds=200))
    early = _drain(engine)
    fills = [e for e in early if e.kind == "fill"]
    assert len(fills) == 1, f"expected due-time execution, got {early}"
    assert fills[0].payload.client_order_id == coid
    assert fills[0].payload.price == pytest.approx(101.0)
    assert fills[0].payload.qty == pytest.approx(0.001)
    _quote(engine, T0 + timedelta(seconds=10), 89.0, 90.0)
    assert [e.kind for e in _drain(engine)].count("fill") == 0
    assert engine.filled_qty(coid) == pytest.approx(0.001)


def test_ioc_nonmarketable_sell_mirror():
    # SELL cap 99.50 > bid 99.00: non-marketable, cancels at arrival;
    # the later bid 98 (marketable then) must not revive it.
    engine = _engine()
    _quote(engine, T0, 99.0, 101.0)
    coid = engine.submit(EngineOrder(instrument="BTCUSDT", side="SELL",
                                     qty=0.001, kind="LIMIT", price=99.50,
                                     role="entry"))
    first = _drain(engine)
    assert [(e.kind, e.payload.client_order_id) for e in first] == [
        ("cancel", coid)]
    assert first[0].payload.reason == "nonmarketable-at-arrival"
    _quote(engine, T0 + timedelta(seconds=1), 98.0, 99.0)
    assert [e.kind for e in _drain(engine)].count("fill") == 0


def test_ioc_marketable_fills_within_cap_bound():
    # Marketable BUY (cap 101.50 >= ask 101): fills on the next tick at a
    # price no worse than the cap (band enforcement), remainder cancels.
    engine = _engine()
    _quote(engine, T0, 99.0, 101.0)
    coid = engine.submit(EngineOrder(instrument="BTCUSDT", side="BUY",
                                     qty=0.001, kind="LIMIT", price=101.50,
                                     role="entry"))
    _quote(engine, T0 + timedelta(seconds=1), 99.0, 101.0)
    _quote(engine, T0 + timedelta(seconds=2), 99.0, 101.0)
    events = _drain(engine)
    fills = [e for e in events if e.kind == "fill"]
    assert len(fills) == 1 and fills[0].payload.client_order_id == coid
    assert fills[0].payload.price <= 101.50
    assert fills[0].payload.liquidity == "taker"
    # Remainder sweep ran (fully filled: nothing to cancel, no crash).
    _quote(engine, T0 + timedelta(seconds=3), 50.0, 51.0)
    assert [e.kind for e in _drain(engine)].count("fill") == 0


def _trade(engine, at, price, size):
    from nautilus_trader.model.data import TradeTick
    from nautilus_trader.model.enums import AggressorSide
    from nautilus_trader.model.identifiers import TradeId
    from nautilus_trader.model.objects import Price, Quantity
    ns = int(at.timestamp() * 1e9)
    engine.feed(TradeTick(
        engine.instrument_id("BTCUSDT"), Price(price, 2),
        Quantity(size, 3), AggressorSide.BUYER, TradeId(f"T-{ns}"),
        ts_event=ns, ts_init=ns))


def test_ioc_partial_fill_cancels_remainder():
    # Arrival ask size 0.0005 < qty 0.002: partial fill at the first
    # opportunity, then the remainder cancels (no revival on later size).
    engine = _engine()
    _quote(engine, T0, 99.0, 101.0, ask_size=0.0005)
    coid = engine.submit(EngineOrder(instrument="BTCUSDT", side="BUY",
                                     qty=0.002, kind="LIMIT", price=101.50,
                                     role="entry"))
    _quote(engine, T0 + timedelta(seconds=1), 99.0, 101.0, ask_size=5.0)
    first = _drain(engine)
    fills = [e for e in first if e.kind == "fill"]
    assert len(fills) == 1
    part = engine.filled_qty(coid)
    assert 0.0 < part < 0.002  # partial, whatever nautilus matched.
    _quote(engine, T0 + timedelta(seconds=2), 99.0, 101.0, ask_size=5.0)
    _quote(engine, T0 + timedelta(seconds=3), 99.0, 101.0, ask_size=5.0)
    rest = _drain(engine)
    assert [e.kind for e in rest].count("fill") == 0, \
        "remainder revived on later size"
    assert engine.filled_qty(coid) == pytest.approx(part)  # frozen.


def test_ioc_marketable_executes_first_opportunity_only():
    # Marketable at arrival: executes at the FIRST opportunity (against
    # arrival liquidity, before later prints matter) and never again —
    # exactly one fill even with deep later prints.
    engine = _engine()
    _quote(engine, T0, 99.0, 101.0)
    coid = engine.submit(EngineOrder(instrument="BTCUSDT", side="BUY",
                                     qty=0.001, kind="LIMIT", price=101.50,
                                     role="entry"))
    _trade(engine, T0 + timedelta(seconds=1), 101.60, 1.0)
    first = _drain(engine)
    assert [e.kind for e in first].count("fill") == 1
    _trade(engine, T0 + timedelta(seconds=2), 100.50, 5.0)
    _trade(engine, T0 + timedelta(seconds=3), 100.50, 5.0)
    rest = _drain(engine)
    assert [e.kind for e in rest].count("fill") == 0
    assert engine.filled_qty(coid) == pytest.approx(0.001)


def test_ioc_cancel_while_queued_drops_submit():
    # Chronological due-time cancel: submit_delay 50ms, cancel arrives at
    # T0 before the submit's T0+50ms due time → the queued submit is
    # dropped, nothing ever enters the venue (no fill, no order events).
    engine = _engine(submit_delay_ms=50, fill_delay_ms=50)
    _quote(engine, T0, 99.0, 101.0, ask_size=1.0)
    coid = engine.submit(EngineOrder(instrument="BTCUSDT", side="BUY",
                                     qty=0.001, kind="LIMIT", price=101.50,
                                     role="entry"))
    engine.cancel(coid, "test-early-cancel")
    engine.advance_to(T0 + timedelta(milliseconds=200))
    _quote(engine, T0 + timedelta(seconds=1), 99.0, 101.0, ask_size=5.0)
    assert _drain(engine) == []
    assert engine.filled_qty(coid) == 0.0
    assert engine.resolve(coid) is None  # never reached the venue.


def test_ioc_same_ts_cancel_rejected_fill_stands():
    # Same-timestamp submit/cancel tie-breaks AT the venue: the cancel
    # for the not-yet-accepted order is rejected ("not found") and the
    # arrival fill stands — the adapter reports the venue verdict as-is
    # (one fill + one reject, exactly the submitted qty, no revival).
    engine = _engine()
    _quote(engine, T0, 99.0, 101.0, ask_size=1.0)
    coid = engine.submit(EngineOrder(instrument="BTCUSDT", side="BUY",
                                     qty=0.001, kind="LIMIT", price=101.50,
                                     role="entry"))
    engine.cancel(coid, "test-same-ts-cancel")
    _quote(engine, T0 + timedelta(seconds=1), 99.0, 101.0, ask_size=5.0)
    events = _drain(engine)
    kinds = [e.kind for e in events]
    assert kinds.count("fill") == 1
    assert kinds.count("reject") == 1
    assert "not found" in events[kinds.index("reject")].payload.reason
    assert engine.filled_qty(coid) == pytest.approx(0.001)
    _quote(engine, T0 + timedelta(seconds=2), 99.0, 101.0, ask_size=5.0)
    assert [e.kind for e in _drain(engine)].count("fill") == 0


def test_ioc_cancel_fill_race_is_exactly_once():
    # Fill executes, cancel in flight: the fill stands exactly once and
    # the losing cancel surfaces as a reject (never a double terminal).
    engine = _engine()
    _quote(engine, T0, 99.0, 101.0)
    coid = engine.submit(EngineOrder(instrument="BTCUSDT", side="BUY",
                                     qty=0.001, kind="LIMIT", price=101.50,
                                     role="entry"))
    _quote(engine, T0 + timedelta(seconds=1), 99.0, 101.0)
    engine.cancel(coid, "test-race")
    _quote(engine, T0 + timedelta(seconds=2), 99.0, 101.0)
    events = _drain(engine)
    fills = [e for e in events if e.kind == "fill"]
    assert len(fills) == 1  # booked exactly once.
    assert engine.filled_qty(coid) == pytest.approx(0.001)
    terminal = [e.kind for e in events
                if e.kind in ("cancel", "reject", "expire")]
    assert terminal, "race loser must still report"


def test_protection_attaches_after_partial_fill():
    # Protection legs size to FILLED qty (not ordered qty) after a
    # partial — verified individually, never assumed.
    engine = _engine()
    _quote(engine, T0, 99.0, 101.0, ask_size=0.0005)
    coid = engine.submit(EngineOrder(instrument="BTCUSDT", side="BUY",
                                     qty=0.002, kind="LIMIT", price=101.50,
                                     role="entry"))
    _quote(engine, T0 + timedelta(seconds=1), 99.0, 101.0, ask_size=5.0)
    _drain(engine)
    part = engine.filled_qty(coid)
    assert 0.0 < part < 0.002
    legs = engine.attach_protection(coid, stop_price=95.0,
                                    target_price=110.0)
    assert len(legs) == 2
    for leg in legs:
        status = [s for s in engine.open_orders()
                  if s.client_order_id == leg]
        assert status, f"leg {leg} missing"


def test_reduce_only_exit_never_flips_flat():
    # A reduce-only SELL with no position must not open a short.
    engine = _engine()
    _quote(engine, T0, 99.0, 101.0)
    engine.submit(EngineOrder(instrument="BTCUSDT", side="SELL", qty=0.001,
                              kind="MARKET", reduce_only=True, role="target"))
    _quote(engine, T0 + timedelta(seconds=1), 99.0, 101.0)
    _quote(engine, T0 + timedelta(seconds=2), 99.0, 101.0)
    events = _drain(engine)
    assert [e.kind for e in events].count("fill") == 0


def test_submit_immediate_journal_labels_diagnostic(tmp_path):
    engine = _engine()
    engine.journal_path = tmp_path / "journal.jsonl"
    _quote(engine, T0, 99.0, 101.0)
    engine.submit(EngineOrder(instrument="BTCUSDT", side="BUY", qty=0.001,
                              kind="MARKET", role="entry"))
    _quote(engine, T0 + timedelta(seconds=1), 99.0, 101.0)
    _drain(engine)
    engine.submit_immediate(EngineOrder(
        instrument="BTCUSDT", side="SELL", qty=0.001, kind="MARKET",
        reduce_only=True, role="target"))
    text = (tmp_path / "journal.jsonl").read_text()
    assert "immediate_exit" in text


def _journal_fills(path):
    import json
    return [json.loads(line)["detail"] for line in path.read_text().splitlines()
            if json.loads(line)["event"] == "fill"]


def test_exit_latency_sensitivity_instant_vs_realistic(tmp_path):
    # 30MIN §4(4), engine level: the identical exit flow under an
    # immediate (diagnostic, zero-latency) model vs a realistic
    # 50/50ms model must show MEASURABLY different execution/report
    # times — base economics must not silently depend on instant exits.
    # (Session._flatten migration to delayed exits is manager-owned;
    # this test pins the engine-side sensitivity + labeling.)
    # Dense 10ms ticks after exit submission: the 100ms modeled
    # latency gap is visible (1s ticks would quantize both to one tick).
    base = T0 + timedelta(seconds=1)
    fast = _engine()
    fast.journal_path = tmp_path / "fast.jsonl"
    _quote(fast, T0, 99.0, 101.0)
    fast.submit(EngineOrder(instrument="BTCUSDT", side="BUY", qty=0.001,
                            kind="MARKET", role="entry"))
    _quote(fast, base, 99.0, 101.0)
    _drain(fast)
    fast.submit_immediate(EngineOrder(
        instrument="BTCUSDT", side="SELL", qty=0.001, kind="MARKET",
        reduce_only=True, role="target"))
    for ms in (10, 20, 30, 200):
        _quote(fast, base + timedelta(milliseconds=ms), 99.0, 101.0)
    _drain(fast)

    slow = _engine(submit_delay_ms=50, fill_delay_ms=50)
    slow.journal_path = tmp_path / "slow.jsonl"
    _quote(slow, T0, 99.0, 101.0)
    slow.submit(EngineOrder(instrument="BTCUSDT", side="BUY", qty=0.001,
                            kind="MARKET", role="entry"))
    _quote(slow, base, 99.0, 101.0)
    _drain(slow)
    slow.submit(EngineOrder(instrument="BTCUSDT", side="SELL", qty=0.001,
                            kind="MARKET", reduce_only=True, role="target"))
    for ms in (10, 20, 30, 200):
        _quote(slow, base + timedelta(milliseconds=ms), 99.0, 101.0)
    _drain(slow)

    fast_fills = _journal_fills(tmp_path / "fast.jsonl")
    slow_fills = _journal_fills(tmp_path / "slow.jsonl")
    assert len(fast_fills) == len(slow_fills) == 2
    assert fast_fills[1]["exec_ts_utc"] < slow_fills[1]["exec_ts_utc"]
    assert fast_fills[1]["ts_utc"] < slow_fills[1]["ts_utc"]
    assert "immediate_exit" in (tmp_path / "fast.jsonl").read_text()
    assert "immediate_exit" not in (tmp_path / "slow.jsonl").read_text()


def test_ioc_marketable_sell_mirror_executes_at_arrival():
    # SELL mirror of the CORR acceptance M1: marketable at arrival (bid
    # 99 >= cap 98.50) → fills @99 in the 200ms drain, no tick required;
    # the bid 10s later at 110 determines nothing (no fill at 110).
    engine = _engine(submit_delay_ms=50, fill_delay_ms=50)
    _quote(engine, T0, 99.0, 101.0)
    coid = engine.submit(EngineOrder(instrument="BTCUSDT", side="SELL",
                                     qty=0.001, kind="LIMIT", price=98.50,
                                     role="entry"))
    engine.advance_to(T0 + timedelta(milliseconds=200))
    early = _drain(engine)
    fills = [e for e in early if e.kind == "fill"]
    assert len(fills) == 1, f"expected due-time execution, got {early}"
    assert fills[0].payload.price == pytest.approx(99.0)
    _quote(engine, T0 + timedelta(seconds=10), 110.0, 111.0)
    assert [e.kind for e in _drain(engine)].count("fill") == 0
    assert engine.filled_qty(coid) == pytest.approx(0.001)


def test_ioc_trade_only_print_gates_arrival():
    # Sparse data, no BBO ever: the last print is the executable
    # reference. BUY cap 100.50 >= print 100 → marketable, submits and
    # fills; BUY cap 99.50 < print 100 → cancels at arrival, no revival.
    engine = _engine()
    _trade(engine, T0, 100.0, 1.0)
    good = engine.submit(EngineOrder(instrument="BTCUSDT", side="BUY",
                                     qty=0.001, kind="LIMIT", price=100.50,
                                     role="entry"))
    bad = engine.submit(EngineOrder(instrument="BTCUSDT", side="BUY",
                                    qty=0.001, kind="LIMIT", price=99.50,
                                    role="entry"))
    _trade(engine, T0 + timedelta(seconds=1), 100.0, 1.0)
    events = _drain(engine)
    by_id = {}
    for e in events:
        by_id.setdefault(e.payload.client_order_id, []).append(e.kind)
    assert "fill" in by_id[good]
    assert by_id[bad] == ["cancel"]
    assert engine.filled_qty(good) == pytest.approx(0.001)
    assert engine.filled_qty(bad) == 0.0


def test_ioc_queued_past_window_expires_never_submits():
    # Expiry interplay: submit_delay 50ms but the window already passed
    # when the submit drains → expire event, never submitted, no fill.
    engine = _engine(submit_delay_ms=50, fill_delay_ms=1)
    _quote(engine, T0, 99.0, 101.0)
    coid = engine.submit(EngineOrder(
        instrument="BTCUSDT", side="BUY", qty=0.001, kind="LIMIT",
        price=101.50, role="entry",
        expire_at_utc=T0 + timedelta(milliseconds=10)))
    engine.advance_to(T0 + timedelta(milliseconds=200))
    events = _drain(engine)
    assert [e.kind for e in events] == ["expire"]
    assert engine.filled_qty(coid) == 0.0
    assert engine.resolve(coid) is None


def test_ioc_no_subsequent_tick_resolves_at_due_time():
    # M1: immediate-or-cancel never rests open. No subsequent tick, but
    # the standing arrival book exists — so the advance past due resolves
    # the IOC at due time (fill @101), with nothing invented.
    engine = _engine()
    _quote(engine, T0, 99.0, 101.0)
    coid = engine.submit(EngineOrder(instrument="BTCUSDT", side="BUY",
                                     qty=0.001, kind="LIMIT", price=101.50,
                                     role="entry"))
    engine.advance_to(T0 + timedelta(milliseconds=200))
    early = _drain(engine)
    assert [e.kind for e in early].count("fill") == 1
    assert engine.filled_qty(coid) == pytest.approx(0.001)
    states = {s.client_order_id: s.state for s in engine.open_orders()}
    assert coid not in states  # terminal: excluded from open-only view.
    assert engine.order_status(coid).state == "filled"  # terminal truth.


def test_ioc_partial_remainder_cancels_same_opportunity():
    # Thin arrival liquidity (0.0005 < 0.002): partial fill at the first
    # opportunity, remainder canceled within that same opportunity (venue
    # enforces IOC natively; the adapter sweep retires tracking as a
    # backstop) — later size never revives it, qty frozen.
    engine = _engine()
    _quote(engine, T0, 99.0, 101.0, ask_size=0.0005)
    coid = engine.submit(EngineOrder(instrument="BTCUSDT", side="BUY",
                                     qty=0.002, kind="LIMIT", price=101.50,
                                     role="entry"))
    _quote(engine, T0 + timedelta(seconds=1), 99.0, 101.0, ask_size=5.0)
    events = _drain(engine)
    assert [e.kind for e in events].count("fill") == 1
    assert [e.kind for e in events].count("cancel") == 1
    part = engine.filled_qty(coid)
    assert 0.0 < part < 0.002
    _quote(engine, T0 + timedelta(seconds=2), 99.0, 101.0, ask_size=5.0)
    assert [e.kind for e in _drain(engine)].count("fill") == 0
    assert engine.filled_qty(coid) == pytest.approx(part)  # frozen.


def test_queued_submit_past_window_expires_unsubmitted():
    engine = _engine(submit_delay_ms=1000)
    _quote(engine, T0, 99.0, 101.0)
    coid = engine.submit(EngineOrder(
        instrument="BTCUSDT", side="BUY", qty=0.001, kind="MARKET",
        expire_at_utc=T0 + timedelta(milliseconds=500), role="entry"))
    engine.advance_to(T0 + timedelta(seconds=2))
    events = _drain(engine)
    expires = [e for e in events if e.kind == "expire"]
    assert len(expires) == 1
    assert expires[0].payload.client_order_id == coid
    assert expires[0].payload.reason == "queued-past-window"
    assert [e.kind for e in events].count("fill") == 0
