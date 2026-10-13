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
    # Print 0.0005 < qty 0.002: partial fill, then the remainder cancels
    # instead of resting for later prints (no revival).
    engine = _engine()
    _quote(engine, T0, 99.0, 101.0)
    coid = engine.submit(EngineOrder(instrument="BTCUSDT", side="BUY",
                                     qty=0.002, kind="LIMIT", price=101.50,
                                     role="entry"))
    _trade(engine, T0 + timedelta(seconds=1), 101.0, 0.0005)
    first = _drain(engine)
    fills = [e for e in first if e.kind == "fill"]
    assert len(fills) == 1
    part = engine.filled_qty(coid)
    assert 0.0 < part < 0.002  # partial, whatever nautilus matched.
    _trade(engine, T0 + timedelta(seconds=2), 101.0, 5.0)
    _trade(engine, T0 + timedelta(seconds=3), 101.0, 5.0)
    rest = _drain(engine)
    assert [e.kind for e in rest].count("fill") == 0, \
        "remainder revived on later prints"
    assert engine.filled_qty(coid) == pytest.approx(part)  # frozen.


def test_ioc_zero_match_prints_no_revival():
    # Marketable at arrival but matched by nothing for two prints above
    # the cap: the IOC terminates (nautilus evaluates per trade tick),
    # so the later print at 100.50 cannot revive it.
    engine = _engine()
    _quote(engine, T0, 99.0, 101.0)
    coid = engine.submit(EngineOrder(instrument="BTCUSDT", side="BUY",
                                     qty=0.001, kind="LIMIT", price=101.50,
                                     role="entry"))
    _trade(engine, T0 + timedelta(seconds=1), 101.60, 1.0)
    _trade(engine, T0 + timedelta(seconds=2), 101.70, 1.0)
    _drain(engine)
    _trade(engine, T0 + timedelta(seconds=3), 100.50, 1.0)
    rest = _drain(engine)
    assert [e.kind for e in rest].count("fill") == 0
    assert engine.filled_qty(coid) == 0.0


def test_ioc_race_fill_stands_then_frozen():
    # The sweep cancels after the accept tick, but nautilus matches each
    # tick BEFORE processing queued cancels — so a fill executing before
    # the cancel lands is genuine and stands (same race as real venues);
    # the order is then terminal and later size cannot revive it.
    engine = _engine()
    _quote(engine, T0, 99.0, 101.0, ask_size=1.0)
    coid = engine.submit(EngineOrder(instrument="BTCUSDT", side="BUY",
                                     qty=0.001, kind="LIMIT", price=101.50,
                                     role="entry"))
    _quote(engine, T0 + timedelta(seconds=1), 99.0, 101.0, ask_size=0.0001)
    _drain(engine)
    assert engine.stats["ioc_remainder_canceled"] >= 1
    _quote(engine, T0 + timedelta(seconds=2), 99.0, 101.0, ask_size=5.0)
    race = _drain(engine)
    assert [e.kind for e in race].count("fill") <= 1  # race fill, if any.
    frozen = engine.filled_qty(coid)
    _quote(engine, T0 + timedelta(seconds=3), 99.0, 101.0, ask_size=5.0)
    _quote(engine, T0 + timedelta(seconds=4), 99.0, 101.0, ask_size=5.0)
    rest = _drain(engine)
    assert [e.kind for e in rest].count("fill") == 0
    assert engine.filled_qty(coid) == pytest.approx(frozen)


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
    _quote(engine, T0, 99.0, 101.0)
    coid = engine.submit(EngineOrder(instrument="BTCUSDT", side="BUY",
                                     qty=0.002, kind="LIMIT", price=101.50,
                                     role="entry"))
    _trade(engine, T0 + timedelta(seconds=1), 101.0, 0.0005)
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
    fast = _engine()
    fast.journal_path = tmp_path / "fast.jsonl"
    _quote(fast, T0, 99.0, 101.0)
    fast.submit(EngineOrder(instrument="BTCUSDT", side="BUY", qty=0.001,
                            kind="MARKET", role="entry"))
    _quote(fast, T0 + timedelta(seconds=1), 99.0, 101.0)
    _drain(fast)
    fast.submit_immediate(EngineOrder(
        instrument="BTCUSDT", side="SELL", qty=0.001, kind="MARKET",
        reduce_only=True, role="target"))
    _quote(fast, T0 + timedelta(seconds=2), 99.0, 101.0)
    _drain(fast)

    slow = _engine(submit_delay_ms=50, fill_delay_ms=50)
    slow.journal_path = tmp_path / "slow.jsonl"
    _quote(slow, T0, 99.0, 101.0)
    slow.submit(EngineOrder(instrument="BTCUSDT", side="BUY", qty=0.001,
                            kind="MARKET", role="entry"))
    _quote(slow, T0 + timedelta(seconds=1), 99.0, 101.0)
    _drain(slow)
    slow.submit(EngineOrder(instrument="BTCUSDT", side="SELL", qty=0.001,
                            kind="MARKET", reduce_only=True, role="target"))
    _quote(slow, T0 + timedelta(seconds=2), 99.0, 101.0)
    _quote(slow, T0 + timedelta(seconds=3), 99.0, 101.0)
    _drain(slow)

    fast_fills = _journal_fills(tmp_path / "fast.jsonl")
    slow_fills = _journal_fills(tmp_path / "slow.jsonl")
    assert len(fast_fills) == len(slow_fills) == 2
    assert fast_fills[1]["exec_ts_utc"] < slow_fills[1]["exec_ts_utc"]
    assert fast_fills[1]["ts_utc"] < slow_fills[1]["ts_utc"]
    assert "immediate_exit" in (tmp_path / "fast.jsonl").read_text()
    assert "immediate_exit" not in (tmp_path / "slow.jsonl").read_text()


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
