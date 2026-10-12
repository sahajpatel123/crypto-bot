"""Nautilus paper-engine unit tests (Worker 2, E-007). Deterministic clock.

Requires nautilus_trader (trial venv); skipped in the stdlib-only project env.
Canonical seam types come from cryptobot.app.engine (manager-owned); this
module defines no competing event/order types.
"""
from datetime import datetime, timedelta, timezone

import pytest

nautilus = pytest.importorskip("nautilus_trader")

from cryptobot.adapters import NautilusPaperEngine  # noqa: E402
from cryptobot.app.engine import (  # noqa: E402
    EngineCancel,
    EngineEvent,
    EngineExpire,
    EngineFill,
    EngineFunding,
    EngineOrder,
    EngineOrderStatus,
    EngineReject,
)

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _engine(now=None, **kw):
    kw.setdefault("taker_bps", 5.0)
    kw.setdefault("now_utc", lambda: now[0] if now is not None else T0)
    kw.setdefault("submit_delay_ms", 0)
    kw.setdefault("fill_delay_ms", 1)
    engine = NautilusPaperEngine(**kw)
    engine.add_instrument("BTCUSDT", price_precision=2, size_precision=3,
                          tick_size=0.01, step_size=0.001, ts_utc=T0)
    return engine


def _quote(engine, i, bid, ask):
    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.model.objects import Price, Quantity
    tick = QuoteTick(
        instrument_id=engine.instrument_id("BTCUSDT"),
        bid_price=Price(bid, 2), ask_price=Price(ask, 2),
        bid_size=Quantity(1.0, 3), ask_size=Quantity(1.0, 3),
        ts_event=int((T0 + timedelta(seconds=i)).timestamp() * 1e9),
        ts_init=int((T0 + timedelta(seconds=i)).timestamp() * 1e9),
    )
    engine.feed(tick)
    return tick


def _ticker_record(seq, recv_ms, bid, ask):
    return {
        "v": 1, "format": "cryptobot-events/1", "input_class": "observed-public",
        "source": "binance-fapi-ws", "route": "public", "run_id": "r1", "seq": seq,
        "channel": "bookTicker", "symbol": "BTCUSDT", "exchange_ts_ms": recv_ms,
        "local_recv_ms": recv_ms, "local_mono_ns": recv_ms * 1_000_000,
        "gap_kind": None, "venue_seq": seq,
        "payload": {"update_id": seq, "bid": bid, "bid_qty": 1.5,
                    "ask": ask, "ask_qty": 2.5, "book_ts_ms": recv_ms},
    }


class _Sink:
    def __init__(self):
        self.deltas = []

    def note_fill_delta(self, reservation_id, exec_id, symbol, venue_side,
                        qty, price, fee, ts_utc):
        self.deltas.append((reservation_id, exec_id, symbol, venue_side,
                            qty, price, fee, ts_utc))


def test_implements_canonical_protocol_with_canonical_types():
    # Protocol is not runtime_checkable: verify the seam surface structurally.
    for name in ("submit", "submit_immediate", "resolve", "cancel", "poll",
                 "attach_protection", "open_orders", "filled_qty",
                 "set_exit_only", "note_mark", "recover", "close", "bind_sink"):
        assert callable(getattr(NautilusPaperEngine, name)), name
    assert NautilusPaperEngine.model_label == "nautilus-paper"
    # No competing definitions: adapter modules import the canonical types.
    import cryptobot.adapters.paper_engine as mod
    assert mod.EngineOrder is EngineOrder
    assert mod.EngineFill is EngineFill
    assert mod.EngineEvent is EngineEvent
    assert mod.EngineOrderStatus is EngineOrderStatus


def test_constructor_validates_cli_seam():
    with pytest.raises(ValueError, match="taker_bps"):
        NautilusPaperEngine(taker_bps=0.0)
    with pytest.raises(ValueError, match="fill_delay_ms"):
        NautilusPaperEngine(fill_delay_ms=0)
    with pytest.raises(ValueError, match="submit_delay_ms"):
        NautilusPaperEngine(submit_delay_ms=-1)


def test_market_order_taker_fill_with_fee():
    engine = _engine()
    _quote(engine, 0, 60000.00, 60000.50)
    cid = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    assert cid.startswith("pe-")
    _quote(engine, 1, 60001.00, 60001.50)
    events = engine.poll()
    fills = [e for e in events if e.kind == "fill"]
    assert len(fills) == 1
    fill = fills[0].payload
    assert isinstance(fills[0], EngineEvent) and isinstance(fill, EngineFill)
    assert fill.client_order_id == cid
    assert fill.instrument == "BTCUSDT" and fill.side == "BUY"
    assert fill.liquidity == "taker"
    assert fill.price == pytest.approx(60001.50)  # crossed the ask, never mid.
    assert fill.fee == pytest.approx(60001.50 * 0.001 * 0.0005)
    assert fill.fee > 0
    assert fill.execution_id  # ledger dedup key present.


def test_submit_delay_queues_until_due():
    engine = _engine(submit_delay_ms=60_000)
    _quote(engine, 0, 60000.00, 60000.50)
    cid = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    assert engine.resolve(cid) is None  # queued, no durable id yet.
    assert engine.open_orders() == []
    _quote(engine, 1, 60001.00, 60001.50)  # only 1s later: still queued.
    assert engine.resolve(cid) is None
    assert not [e for e in engine.poll() if e.kind == "fill"]
    _quote(engine, 61, 60002.00, 60002.50)  # past due: submitted, then filled.
    assert engine.resolve(cid) == cid
    _quote(engine, 62, 60003.00, 60003.50)
    fills = [e for e in engine.poll() if e.kind == "fill"]
    assert [f.payload.client_order_id for f in fills] == [cid]


def test_cancel_drops_queued_submit():
    engine = _engine(submit_delay_ms=60_000)
    _quote(engine, 0, 60000.00, 60000.50)
    cid = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    engine.cancel(cid, "changed-mind")
    _quote(engine, 61, 60002.00, 60002.50)
    _quote(engine, 62, 60003.00, 60003.50)
    assert engine.poll() == []
    assert engine.open_orders() == []
    assert engine.resolve(cid) is None


def test_submit_immediate_bypasses_delays_exits_only():
    engine = _engine(submit_delay_ms=60_000, fill_delay_ms=50)
    _quote(engine, 0, 60000.00, 60000.50)
    with pytest.raises(ValueError, match="exits-only"):
        engine.submit_immediate(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    queued = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET",
                                       role="exit"))
    rushed = engine.submit_immediate(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET",
                                                 role="exit"))
    assert engine.resolve(rushed) == rushed  # no queue wait.
    assert engine.resolve(queued) is None
    engine.advance_to(T0)  # same-ts drain: immediate delivers, queued does not.
    states = {s.client_order_id: s.state for s in engine.open_orders()}
    assert states[rushed] == "filled"  # crossed the standing book, no delay.
    assert engine.resolve(queued) is None
    _quote(engine, 1, 60001.00, 60001.50)
    fills = [e for e in engine.poll() if e.kind == "fill"]
    assert [f.payload.client_order_id for f in fills] == [rushed]


def test_client_ids_unique_across_submits():
    engine = _engine()
    _quote(engine, 0, 60000.00, 60000.50)
    ids = {engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
           for _ in range(25)}
    assert len(ids) == 25
    assert all(engine.resolve(i) == i for i in ids)
    assert engine.resolve("pe-999999-unknown") is None


def test_marketable_limit_fills_as_taker_with_price_protection():
    engine = _engine()
    _quote(engine, 0, 60000.00, 60000.50)
    cid = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "LIMIT", price=60010.00))
    _quote(engine, 1, 60001.00, 60001.50)
    fills = [e for e in engine.poll() if e.kind == "fill"]
    assert len(fills) == 1
    assert fills[0].payload.client_order_id == cid
    assert fills[0].payload.liquidity == "taker"
    assert fills[0].payload.price <= 60010.00  # limit cap honored.


def test_non_marketable_limit_cancels_without_resting():
    engine = _engine()
    _quote(engine, 0, 60000.00, 60000.50)
    cid = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "LIMIT", price=59000.00))
    _quote(engine, 1, 60001.00, 60001.50)
    kinds = [(e.kind, e.payload.client_order_id) for e in engine.poll()]
    assert ("cancel", cid) in kinds
    assert not [k for k, _ in kinds if k == "fill"]
    states = {s.client_order_id: s.state for s in engine.open_orders()}
    assert states[cid] == "cancelled"  # IOC: never rests, never maker-fills.


def test_open_orders_snapshot_shape():
    engine = _engine()
    _quote(engine, 0, 60000.00, 60000.50)
    cid = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.002, "MARKET",
                                    reservation_id="res-1"))
    (status,) = engine.open_orders()
    assert isinstance(status, EngineOrderStatus)
    assert status.client_order_id == cid and status.instrument == "BTCUSDT"
    assert status.qty == pytest.approx(0.002) and status.filled_qty == 0.0
    assert status.reservation_id == "res-1" and status.role == "entry"
    assert status.state == "open"
    _quote(engine, 1, 60001.00, 60001.50)
    assert engine.poll()
    (status,) = engine.open_orders()
    assert status.state == "filled" and status.filled_qty == pytest.approx(0.002)


def test_stop_and_target_legs_fill_independently():
    engine = _engine()
    _quote(engine, 0, 60000.00, 60000.50)
    entry = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.002, "MARKET"))
    _quote(engine, 1, 60001.00, 60001.50)
    assert [e.kind for e in engine.poll() if e.kind == "fill"]
    stop = engine.submit(EngineOrder("BTCUSDT", "SELL", 0.002, "STOP_MARKET",
                                     stop_price=59990.00, reduce_only=True,
                                     role="stop"))
    target = engine.submit(EngineOrder("BTCUSDT", "SELL", 0.002, "TAKE_PROFIT_MARKET",
                                       stop_price=60010.00, reduce_only=True,
                                       role="target"))
    assert stop != target != entry
    _quote(engine, 2, 60001.00, 60001.50)  # legs accepted here (triggers out of market).
    assert not engine.poll()  # accepted is internal state, not an event.
    _quote(engine, 3, 60011.00, 60011.50)  # target triggers and fills, stop rests.
    fills = [e for e in engine.poll() if e.kind == "fill"]
    assert [f.payload.client_order_id for f in fills] == [target]
    assert fills[0].payload.side == "SELL" and fills[0].payload.qty == pytest.approx(0.002)
    engine.cancel(stop, "sibling-settled")
    _quote(engine, 4, 60012.00, 60012.50)
    cancels = [e for e in engine.poll() if e.kind == "cancel"]
    assert [c.payload.client_order_id for c in cancels] == [stop]
    assert isinstance(cancels[0].payload, EngineCancel)
    assert cancels[0].payload.instrument == "BTCUSDT"


def test_attach_protection_sizes_to_filled_qty():
    engine = _engine()
    _quote(engine, 0, 60000.00, 60000.50)
    entry = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.002, "MARKET",
                                      reservation_id="res-9"))
    _quote(engine, 1, 60001.00, 60001.50)
    assert engine.poll()
    legs = engine.attach_protection(entry, 59990.00, 60010.00)
    assert len(legs) == 2
    statuses = {s.client_order_id: s for s in engine.open_orders()}
    assert statuses[legs[0]].role == "stop"
    assert statuses[legs[1]].role == "target"
    assert statuses[legs[0]].reservation_id == "res-9"  # reservation threads to legs.
    _quote(engine, 2, 60001.00, 60001.50)  # legs accepted (triggers out of market).
    _quote(engine, 3, 60011.00, 60011.50)  # target triggers and fills.
    fills = [e for e in engine.poll() if e.kind == "fill"]
    assert [f.payload.client_order_id for f in fills] == [legs[1]]
    assert fills[0].payload.qty == pytest.approx(0.002)


def test_attach_protection_stop_only_and_no_fill_refusal():
    engine = _engine()
    _quote(engine, 0, 60000.00, 60000.50)
    entry = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.002, "MARKET"))
    with pytest.raises(ValueError, match="with fills"):
        engine.attach_protection(entry, 59990.00, None)
    _quote(engine, 1, 60001.00, 60001.50)
    assert engine.poll()
    legs = engine.attach_protection(entry, 59990.00, None)
    assert len(legs) == 1


def test_stop_in_market_rejects():
    engine = _engine()
    _quote(engine, 0, 60000.00, 60000.50)
    # SELL stop above the market is already triggered -> venue rejects.
    cid = engine.submit(EngineOrder("BTCUSDT", "SELL", 0.001, "STOP_MARKET",
                                    stop_price=60010.00))
    _quote(engine, 1, 60001.00, 60001.50)
    rejects = [e for e in engine.poll() if e.kind == "reject"]
    assert len(rejects) == 1 and rejects[0].payload.client_order_id == cid
    assert isinstance(rejects[0].payload, EngineReject)
    assert rejects[0].payload.instrument == "BTCUSDT"


def test_gtd_expiry_reports_expire():
    engine = _engine()
    _quote(engine, 0, 60000.00, 60000.50)
    cid = engine.submit(EngineOrder("BTCUSDT", "SELL", 0.001, "STOP_MARKET",
                                    stop_price=59000.00,
                                    expire_at_utc=T0 + timedelta(seconds=30)))
    _quote(engine, 1, 60001.00, 60001.50)
    assert not [e for e in engine.poll() if e.kind == "expire"]
    engine.advance_to(T0 + timedelta(seconds=31))  # bare advance: no expiry yet.
    assert not [e for e in engine.poll() if e.kind == "expire"]
    _quote(engine, 31, 60001.00, 60001.50)  # expiry fires on fed data at/after expiry.
    expires = [e for e in engine.poll() if e.kind == "expire"]
    assert [x.payload.client_order_id for x in expires] == [cid]
    assert isinstance(expires[0].payload, EngineExpire)


def test_missing_prices_refused():
    engine = _engine()
    _quote(engine, 0, 60000.00, 60000.50)
    with pytest.raises(ValueError, match="LIMIT submit needs price"):
        engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "LIMIT"))
    with pytest.raises(ValueError, match="STOP_MARKET submit needs stop_price"):
        engine.submit(EngineOrder("BTCUSDT", "SELL", 0.001, "STOP_MARKET"))
    with pytest.raises(ValueError, match="unsupported order kind"):
        engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "TRAILING"))


def test_exit_only_refuses_entries_but_allows_exits():
    engine = _engine()
    _quote(engine, 0, 60000.00, 60000.50)
    engine.set_exit_only(True, "halt:test")
    with pytest.raises(PermissionError, match="exit-only"):
        engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    # Exits (non-entry roles) still submit.
    cid = engine.submit(EngineOrder("BTCUSDT", "SELL", 0.001, "MARKET", role="stop"))
    assert engine.resolve(cid) == cid
    engine.set_exit_only(False, "cleared")
    cid2 = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    assert engine.resolve(cid2) == cid2


def test_note_mark_is_valuation_only_never_executable():
    # B2: a mid-mark can never become a fill price (CEO probe). BBO
    # 59999/60001 with mark 60000: a market BUY crosses the ask at 60001.
    engine = _engine()
    engine.note_mark("BTCUSDT", 60000.00)
    assert engine.latest_mark("BTCUSDT") == 60000.00
    assert engine.valuation_mark("BTCUSDT") == 60000.00
    assert engine.latest_mark("ETHUSDT") is None
    cid = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    # Marks alone — even a rising one — never produce a fill. With no book the
    # venue rejects (correct venue behavior); the mark price never fills.
    engine.note_mark("BTCUSDT", 60001.00)
    engine.advance_to(T0 + timedelta(seconds=30))
    events = engine.poll()
    assert [e for e in events if e.kind == "fill"] == []
    assert [e.payload.client_order_id for e in events if e.kind == "reject"] == [cid]
    # Real quotes resolve by crossing the touch, never the mark.
    engine2 = _engine()
    engine2.note_mark("BTCUSDT", 60000.00)
    cid2 = engine2.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    _quote(engine2, 0, 59999.00, 60001.00)
    fills = [e for e in engine2.poll() if e.kind == "fill"]
    assert [f.payload.client_order_id for f in fills] == [cid2]
    assert fills[0].payload.price == pytest.approx(60001.00)  # the ask, not 60000.
    assert fills[0].payload.liquidity == "taker"


def test_submit_protected_fills_at_or_better():
    engine = _engine()
    _quote(engine, 0, 60000.00, 60000.50)
    cid = engine.submit_protected(
        EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"), 60002.00)
    _quote(engine, 1, 60001.00, 60001.50)
    fills = [e for e in engine.poll() if e.kind == "fill"]
    assert [f.payload.client_order_id for f in fills] == [cid]
    assert fills[0].payload.price == pytest.approx(60001.50)  # lifted the ask...
    assert fills[0].payload.price < 60002.00  # ...better than the limit.


def test_submit_protected_cancels_when_touch_unreachable():
    # CEO probe, second half: protected BUY at 60000 with ask 60001 cancels
    # (opportunity expired) instead of filling at the mark or chasing.
    engine = _engine()
    _quote(engine, 0, 59999.00, 60001.00)
    engine.note_mark("BTCUSDT", 60000.00)
    cid = engine.submit_protected(
        EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"), 60000.00)
    _quote(engine, 1, 59999.00, 60001.00)
    _quote(engine, 2, 59999.00, 60001.00)
    events = engine.poll()
    assert [e for e in events if e.kind == "fill"] == []
    cancels = [e for e in events if e.kind == "cancel"]
    assert [c.payload.client_order_id for c in cancels] == [cid]


def test_submit_protected_rejects_bad_limit():
    engine = _engine()
    _quote(engine, 0, 60000.00, 60000.50)
    with pytest.raises(ValueError, match="limit_price"):
        engine.submit_protected(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"), 0.0)


def test_note_event_feeds_true_taker_cross():
    engine = _engine()
    t0ms = int(T0.timestamp() * 1000)
    engine.note_event(_ticker_record(1, t0ms, 60000.00, 60000.50))
    cid = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    engine.note_event(_ticker_record(2, t0ms + 1000, 60001.00, 60001.50))
    fills = [e for e in engine.poll() if e.kind == "fill"]
    assert [f.payload.client_order_id for f in fills] == [cid]
    assert fills[0].payload.price == pytest.approx(60001.50)  # crossed the ask.


def test_note_event_mark_price_only_records():
    engine = _engine()
    engine.note_event({"channel": "markPrice", "symbol": "BTCUSDT",
                       "payload": {"mark": 60000.0, "funding_rate": 0.0001,
                                   "next_funding_ms": 1}})
    assert engine.latest_mark("BTCUSDT") == 60000.0
    assert engine.poll() == []


def test_sink_propagation_and_bind_replay(tmp_path):
    journal = tmp_path / "journal.jsonl"
    engine = _engine(journal_path=journal)
    _quote(engine, 0, 60000.00, 60000.50)
    cid = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET",
                                    reservation_id="res-1"))
    _quote(engine, 1, 60001.00, 60001.50)
    assert [e for e in engine.poll() if e.kind == "fill"]
    sink = _Sink()
    engine.bind_sink(sink)  # unbound at fill time: bind replays the backlog.
    assert len(sink.deltas) == 1
    res, exec_id, sym, side, qty, price, fee, ts = sink.deltas[0]
    assert (res, sym, side) == ("res-1", "BTCUSDT", "BUY")
    assert qty == pytest.approx(0.001) and fee > 0
    assert ts.endswith("+00:00")
    # Second bind does not double-propagate (journaled delta-propagated).
    engine.bind_sink(sink)
    assert len(sink.deltas) == 1
    text = journal.read_text()
    assert '"event": "submitted"' in text and '"event": "fill"' in text
    assert '"event": "delta-propagated"' in text


def test_live_propagate_skips_unreserved_fills(tmp_path):
    journal = tmp_path / "journal.jsonl"
    sink = _Sink()
    engine = _engine(outcome_sink=sink, journal_path=journal)
    _quote(engine, 0, 60000.00, 60000.50)
    engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))  # no reservation.
    _quote(engine, 1, 60001.00, 60001.50)
    assert [e for e in engine.poll() if e.kind == "fill"]
    assert sink.deltas == []  # reservation-less fills never hit the sink.


def test_recover_rebuilds_and_marks_lost(tmp_path):
    journal = tmp_path / "journal.jsonl"
    engine = _engine(journal_path=journal)
    _quote(engine, 0, 60000.00, 60000.50)
    entry = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.002, "MARKET",
                                      reservation_id="res-1"))
    _quote(engine, 1, 60001.00, 60001.50)
    assert engine.poll()
    legs = engine.attach_protection(entry, 59990.00, 60010.00)
    engine.set_exit_only(True, "halt:test")
    fresh = _engine(journal_path=journal)
    sink = _Sink()
    fresh.recover(sink)
    assert len(sink.deltas) == 1  # the entry fill replayed to the new sink.
    assert fresh.lost_orders() == sorted([entry] + legs)  # sim orders never survive.
    assert fresh.filled_qty(entry) == pytest.approx(0.002)  # logged fills stand.
    assert fresh.filled_qty("pe-999999-nope") == 0.0
    assert fresh.open_orders() == []  # nothing live in the fresh sim.
    with pytest.raises(PermissionError, match="exit-only"):
        fresh.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))  # halt level kept.
    # Seq continuity: no id collisions after recovery.
    cid = fresh.submit(EngineOrder("BTCUSDT", "SELL", 0.001, "MARKET", role="exit"))
    assert cid not in ([entry] + legs)


def test_recover_needs_journal():
    engine = _engine()
    with pytest.raises(RuntimeError, match="journal_path"):
        engine.recover(_Sink())


def test_auto_instrument_from_venue_filters():
    def rest_get(url, timeout):
        assert url.endswith("/fapi/v1/exchangeInfo")
        return {"symbols": [{
            "symbol": "BTCUSDT", "pricePrecision": 2, "quantityPrecision": 3,
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.002"},
                {"filterType": "MIN_NOTIONAL", "notional": "5"}]}]}, 1.0

    engine = NautilusPaperEngine(taker_bps=5.0, now_utc=lambda: T0,
                                 submit_delay_ms=0, fill_delay_ms=1,
                                 rest_get=rest_get)
    cid = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.0029, "MARKET"))
    _quote(engine, 0, 60000.00, 60000.50)
    _quote(engine, 1, 60001.00, 60001.50)
    fills = [e for e in engine.poll() if e.kind == "fill"]
    assert [f.payload.client_order_id for f in fills] == [cid]
    assert fills[0].payload.qty == pytest.approx(0.002)  # floored to step.
    with pytest.raises(ValueError, match="minQty"):
        engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    with pytest.raises(ValueError, match="MIN_NOTIONAL"):
        engine.submit(EngineOrder("BTCUSDT", "BUY", 0.002, "LIMIT", price=1.00))


def test_auto_instrument_rest_failure_fails_closed():
    def rest_get(url, timeout):
        raise OSError("filters unreachable")

    engine = NautilusPaperEngine(taker_bps=5.0, now_utc=lambda: T0,
                                 submit_delay_ms=0, fill_delay_ms=1,
                                 rest_get=rest_get)
    with pytest.raises(RuntimeError, match="filters unreachable"):
        engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))


def test_cancel_unknown_id_fails_closed():
    engine = _engine()
    with pytest.raises(KeyError):
        engine.cancel("pe-000000-deadbeef", "test")


def test_same_tick_submits_drain_fifo():
    # Integration fix: entry + legs submitted in one tick share a due and
    # must drain in submission order (was: TypeError comparing EngineOrder).
    from cryptobot.app.engine import EngineOrder
    engine = _engine(submit_delay_ms=50)
    now_ns = engine._clock.timestamp_ns()
    c1 = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.01, "MARKET"))
    c2 = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.01, "MARKET"))
    assert engine.resolve(c1) is None and engine.resolve(c2) is None
    engine._clock.set_time(now_ns + 60_000_000)
    engine._drain_pending()
    assert engine.resolve(c1) == c1 and engine.resolve(c2) == c2
    ids = list(engine._orders)
    assert ids.index(c1) < ids.index(c2)


def test_feed_clamps_out_of_order_ticks():
    # Integration fix: cross-symbol interleave is normal (BTC@5 then ETH@4):
    # the ETH tick still lands in its own book (re-stamped to engine-now,
    # ts_event kept) and the clock holds at max (was: hard raise, crashed R2).
    # Genuinely stale same-instrument data stays superseded by design.
    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.model.objects import Price, Quantity
    engine = _engine()
    engine.add_instrument("ETHUSDT", price_precision=2, size_precision=3,
                          tick_size=0.01, step_size=0.001, ts_utc=T0)
    _quote(engine, 5, 60000.00, 60000.50)
    before = engine._clock.timestamp_ns()
    eth = QuoteTick(
        engine.instrument_id("ETHUSDT"),
        Price(3000.00, 2), Price(3000.50, 2),
        Quantity(1.0, 3), Quantity(1.0, 3),
        ts_event=int((T0 + timedelta(seconds=4)).timestamp() * 1e9),
        ts_init=int((T0 + timedelta(seconds=4)).timestamp() * 1e9))
    engine.feed(eth)
    assert engine._clock.timestamp_ns() == before
    iid = engine.instrument_id("ETHUSDT")
    assert str(engine._exchange.best_bid_price(iid)) == "3000.00"
    assert str(engine._exchange.best_ask_price(iid)) == "3000.50"


def test_no_binance_live_execution_client():
    import pathlib
    src = pathlib.Path("src/cryptobot/adapters/paper_engine.py").read_text()
    for banned in ("BinanceLiveExecClientFactory", "BinanceFuturesExecutionClient",
                   "BinanceSpotExecutionClient", "BinanceExecClientConfig"):
        assert banned not in src
    engine = _engine()
    assert type(engine._client).__name__ == "BacktestExecClient"


def test_assumptions_logged_and_doctored():
    engine = _engine(submit_delay_ms=50, fill_delay_ms=50)
    assert isinstance(engine.assumptions, tuple)  # session reads it as data.
    text = engine.doctor()
    for needle in ("taker-only", "support_contingent_orders=False", "R0",
                   "never double-charged", "no Binance live execution client",
                   "LIMIT IOC", "submit_delay_ms=50", "valuation-only",
                   "auto-register", "lost-on-restart", "strict_replay",
                   "deterministic ids", "funding", "account_margin",
                   "max_queued_submits"):
        assert needle in text


def _mark_record(recv_ms, mark, rate=0.0001, next_ms=None, status=None):
    payload = {"mark": mark, "funding_rate": rate,
               "next_funding_ms": recv_ms if next_ms is None else next_ms}
    if status is not None:
        payload["funding_status"] = status
    return {
        "v": 1, "format": "cryptobot-events/1", "input_class": "observed-public",
        "source": "binance-fapi-ws", "route": "public", "run_id": "r1", "seq": 9,
        "channel": "markPrice", "symbol": "BTCUSDT", "exchange_ts_ms": recv_ms,
        "local_recv_ms": recv_ms, "local_mono_ns": recv_ms * 1_000_000,
        "gap_kind": None, "venue_seq": 9,
        "payload": payload,
    }


def _trade_tick(engine, i, price, qty, aggressor=None):
    from nautilus_trader.model.data import TradeTick
    from nautilus_trader.model.enums import AggressorSide
    from nautilus_trader.model.identifiers import TradeId
    from nautilus_trader.model.objects import Price, Quantity
    tick = TradeTick(
        instrument_id=engine.instrument_id("BTCUSDT"),
        price=Price(price, 2), size=Quantity(qty, 3),
        aggressor_side=aggressor or AggressorSide.BUYER,
        trade_id=TradeId(f"T-{i}"),
        ts_event=int((T0 + timedelta(seconds=i)).timestamp() * 1e9),
        ts_init=int((T0 + timedelta(seconds=i)).timestamp() * 1e9),
    )
    engine.feed(tick)
    return tick


def test_market_fills_across_thin_trade_prints_without_cancel():
    # Trade-only replay (archive basis): prints seed L1 size; the print size
    # fills at-print and the swept remainder walks one tick adverse
    # (nautilus empty-book model — conservative, labeled in assumptions).
    # The remainder is never fake-cancelled the way IOC would.
    engine = _engine()
    cid = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.01, "MARKET"))
    _trade_tick(engine, 0, 77191.10, 0.001)
    _trade_tick(engine, 1, 77191.00, 0.012)
    events = engine.poll()
    fills = [e for e in events if e.kind == "fill"]
    assert [e for e in events if e.kind == "cancel"] == []
    assert sum(f.payload.qty for f in fills) == pytest.approx(0.01)
    assert fills[0].payload.price == pytest.approx(77191.10)  # the print.
    assert {f.payload.price for f in fills} <= {77191.10, 77191.11}
    assert engine.filled_qty(cid) == pytest.approx(0.01)


def test_queued_submit_past_window_expires_never_submitted():
    engine = _engine(submit_delay_ms=60_000)
    cid = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.01, "MARKET",
                                    expire_at_utc=T0 + timedelta(seconds=10)))
    assert engine.resolve(cid) is None  # queued, not yet in the sim.
    engine.advance_to(T0 + timedelta(seconds=61))  # due, but past the window.
    events = engine.poll()
    expires = [e for e in events if e.kind == "expire"]
    assert [x.payload.client_order_id for x in expires] == [cid]
    assert expires[0].payload.reason == "queued-past-window"
    assert isinstance(expires[0].payload, EngineExpire)
    with pytest.raises(KeyError):
        engine.order_status(cid)  # never reached the simulator.


def test_queued_submit_within_window_fills_normally():
    engine = _engine(submit_delay_ms=1_000)
    cid = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET",
                                    expire_at_utc=T0 + timedelta(seconds=60)))
    _quote(engine, 2, 60000.00, 60000.50)
    _quote(engine, 3, 60000.00, 60000.50)  # second tick clears fill latency.
    fills = [e for e in engine.poll() if e.kind == "fill"]
    assert [f.payload.client_order_id for f in fills] == [cid]


def test_strict_replay_fails_closed_on_shuffle():
    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.model.objects import Price, Quantity
    engine = _engine(strict_replay=True)
    _quote(engine, 10, 60000.00, 60000.50)
    stale = QuoteTick(
        instrument_id=engine.instrument_id("BTCUSDT"),
        bid_price=Price(59999.00, 2), ask_price=Price(59999.50, 2),
        bid_size=Quantity(1.0, 3), ask_size=Quantity(1.0, 3),
        ts_event=int((T0 + timedelta(seconds=9)).timestamp() * 1e9),
        ts_init=int((T0 + timedelta(seconds=9)).timestamp() * 1e9),
    )
    with pytest.raises(ValueError, match="strict replay"):
        engine.feed(stale)
    # Lenient default restamps and counts instead of raising.
    lax = _engine()
    _quote(lax, 10, 60000.00, 60000.50)
    lax.feed(stale)
    assert lax.stats["restamped_ticks"] == 1


def test_seeded_client_ids_deterministic():
    a = _engine(random_seed=7)
    b = _engine(random_seed=7)
    c = _engine(random_seed=8)
    ids_a = [a.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
             for _ in range(3)]
    ids_b = [b.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
             for _ in range(3)]
    ids_c = [c.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
             for _ in range(3)]
    assert ids_a == ids_b  # same seed: stable execution ids (B1).
    assert ids_a != ids_c  # different seed: different stream.
    assert len(set(ids_a)) == 3


def test_submit_queue_bound_fails_closed():
    engine = _engine(submit_delay_ms=60_000, max_queued_submits=2)
    _quote(engine, 0, 60000.00, 60000.50)
    engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    assert engine.stats["queued_submits"] == 2
    with pytest.raises(OverflowError, match="submit queue full"):
        engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))


def test_pending_events_bound_fails_closed():
    engine = _engine(max_pending_events=1)
    _quote(engine, 0, 60000.00, 60000.50)
    engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    _quote(engine, 1, 60001.00, 60001.50)  # first fill enqueued (no poll).
    engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    with pytest.raises(OverflowError, match="pending event queue full"):
        _quote(engine, 2, 60002.00, 60002.50)  # second fill overflows.


def test_pop_events_is_bounded():
    engine = _engine()
    _quote(engine, 0, 60000.00, 60000.50)
    c1 = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    c2 = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    _quote(engine, 1, 60001.00, 60001.50)
    first = engine.pop_events(max_events=1)
    assert [e.payload.client_order_id for e in first] == [c1]
    assert engine.stats["pending_events"] == 1
    rest = engine.pop_events()
    assert [e.payload.client_order_id for e in rest] == [c2]
    assert engine.stats["pending_events"] == 0


def test_account_margin_locks_and_releases():
    engine = _engine(default_leverage=5)
    assert engine.default_leverage == 5  # B2 session asserts the same number.
    assert engine.account_margin() == (10000.0, 10000.0)
    _quote(engine, 0, 60000.00, 60000.50)
    engine.submit(EngineOrder("BTCUSDT", "BUY", 0.1, "MARKET"))
    _quote(engine, 1, 60001.00, 60001.50)
    assert engine.poll()
    available, free = engine.account_margin()
    assert (available, free) == (pytest.approx(9396.984925),
                                 pytest.approx(8796.969925))
    assert free < available < 10000.0  # exposure locks margin.
    engine.submit(EngineOrder("BTCUSDT", "SELL", 0.1, "MARKET", role="target"))
    _quote(engine, 2, 60002.00, 60002.50)
    assert engine.poll()
    available, free = engine.account_margin()
    assert available == pytest.approx(free)  # flat: no maintenance lock.
    assert (available, free) == (pytest.approx(9994.049825),
                                 pytest.approx(9994.049825))


def test_funding_settles_from_mark_price_terms():
    engine = _engine()
    t0ms = int(T0.timestamp() * 1000)
    _quote(engine, 0, 60000.00, 60000.50)
    engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    _quote(engine, 1, 60001.00, 60001.50)
    assert [e for e in engine.poll() if e.kind == "fill"]
    # Settlement boundary reached at t0+1s with a positive rate: long pays.
    engine.note_event(_mark_record(t0ms + 1000, 60000.0, rate=0.0001,
                                   next_ms=t0ms + 1000))
    fundings = [e for e in engine.poll() if e.kind == "funding"]
    assert len(fundings) == 1
    payload = fundings[0].payload
    assert isinstance(payload, EngineFunding)
    assert payload.instrument == "BTCUSDT"
    assert payload.amount == pytest.approx(-0.001 * 60000.0 * 0.0001)
    assert engine.stats["funding_events"] == 1
    # Same boundary never settles twice.
    engine.note_event(_mark_record(t0ms + 1000, 60000.0, rate=0.0001,
                                   next_ms=t0ms + 1000))
    assert [e for e in engine.poll() if e.kind == "funding"] == []


def test_funding_skipped_when_flat_or_zero_rate():
    engine = _engine()
    t0ms = int(T0.timestamp() * 1000)
    _quote(engine, 0, 60000.00, 60000.50)
    engine.note_event(_mark_record(t0ms, 60000.0))  # flat: no cash flow.
    assert engine.poll() == []
    engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    _quote(engine, 1, 60001.00, 60001.50)
    assert engine.poll()
    engine.note_event(_mark_record(t0ms + 1000, 60001.0, rate=0.0,
                                   next_ms=t0ms + 1000))  # zero rate: nothing.
    assert [e for e in engine.poll() if e.kind == "funding"] == []


def test_funding_absent_terms_invalidate_no_silent_zero():
    engine = _engine()
    t0ms = int(T0.timestamp() * 1000)
    _quote(engine, 0, 60000.00, 60000.50)
    engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    _quote(engine, 1, 60001.00, 60001.50)
    assert engine.poll()
    engine.note_event(_mark_record(t0ms + 1000, 60000.0, rate=0.0001,
                                   next_ms=t0ms + 1000))
    assert len([e for e in engine.poll() if e.kind == "funding"]) == 1
    # Terms go explicitly unknown: no settlement on stale rates, no zero fill.
    engine.note_event(_mark_record(t0ms + 2000, 60000.0, rate=None,
                                   next_ms=0, status="absent"))
    engine.advance_to(T0 + timedelta(hours=9))
    assert [e for e in engine.poll() if e.kind == "funding"] == []
    # Sourced terms re-establish settlement afterwards.
    engine.note_event(_mark_record(t0ms + 9 * 3600_000, 60000.0, rate=0.0001,
                                   next_ms=t0ms + 9 * 3600_000))
    assert len([e for e in engine.poll() if e.kind == "funding"]) == 1


def test_funding_never_projects_past_last_asserted_boundary():
    engine = _engine()
    t0ms = int(T0.timestamp() * 1000)
    _quote(engine, 0, 60000.00, 60000.50)
    engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    _quote(engine, 1, 60001.00, 60001.50)
    assert engine.poll()
    engine.note_event(_mark_record(t0ms + 1000, 60000.0, rate=0.0001,
                                   next_ms=t0ms + 1000))
    assert len([e for e in engine.poll() if e.kind == "funding"]) == 1
    # Clock crosses where the old +8h self-projection would have fired:
    # nothing settles without a newer sourced record asserting it.
    engine.advance_to(T0 + timedelta(hours=9))
    assert [e for e in engine.poll() if e.kind == "funding"] == []


def test_recover_advances_seeded_ids(tmp_path):
    journal = tmp_path / "journal.jsonl"
    first = _engine(journal_path=journal, random_seed=7)
    _quote(first, 0, 60000.00, 60000.50)
    journaled = [first.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
                 for _ in range(2)]
    fresh = _engine(random_seed=7)  # same seed, no journal: replays id stream.
    fresh_first = fresh.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    assert fresh_first == journaled[0]
    second = _engine(journal_path=journal, random_seed=7)
    second.recover(_Sink())
    resumed = second.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    assert resumed not in journaled  # RNG advanced past journaled ids.
    assert resumed.split("-")[1] == "000003"  # sequence continues.
