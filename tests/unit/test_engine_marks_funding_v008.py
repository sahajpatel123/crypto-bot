"""V-008 §7: mark-age semantics + settled-funding reconcile input (engine side)."""
from datetime import datetime, timezone

import pytest

nautilus = pytest.importorskip("nautilus_trader")

from cryptobot.accounting import Ledger  # noqa: E402
from cryptobot.adapters import NautilusPaperEngine  # noqa: E402
from cryptobot.app.engine import EngineFunding, EngineOrder  # noqa: E402

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _engine():
    engine = NautilusPaperEngine(taker_bps=5.0, now_utc=lambda: T0,
                                 submit_delay_ms=0, fill_delay_ms=1)
    engine.add_instrument("BTCUSDT", price_precision=2, size_precision=3,
                          tick_size=0.01, step_size=0.001, ts_utc=T0)
    return engine


def _quote(engine, i, bid, ask):
    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.model.objects import Price, Quantity
    engine.feed(QuoteTick(
        instrument_id=engine.instrument_id("BTCUSDT"),
        bid_price=Price(bid, 2), ask_price=Price(ask, 2),
        bid_size=Quantity(1.0, 3), ask_size=Quantity(1.0, 3),
        ts_event=int(T0.timestamp() * 1e9) + i * 1_000_000_000,
        ts_init=int(T0.timestamp() * 1e9) + i * 1_000_000_000))


def _mark_record(recv_ms, mark, rate=0.0001, next_ms=None):
    return {
        "v": 1, "format": "cryptobot-events/1", "input_class": "observed-public",
        "source": "binance-fapi-ws", "route": "public", "run_id": "r1", "seq": 9,
        "channel": "markPrice", "symbol": "BTCUSDT", "exchange_ts_ms": recv_ms,
        "local_recv_ms": recv_ms, "local_mono_ns": recv_ms * 1_000_000,
        "gap_kind": None, "venue_seq": 9,
        "payload": {"mark": mark, "funding_rate": rate,
                    "next_funding_ms": recv_ms if next_ms is None else next_ms},
    }


def test_mark_ts_none_before_any_mark():
    assert _engine().valuation_mark_ts("BTCUSDT") is None


def test_note_mark_stamps_engine_now():
    engine = _engine()
    engine.note_mark("BTCUSDT", 60000.0)
    assert engine.valuation_mark_ts("BTCUSDT") == T0


def test_note_mark_honors_explicit_ts():
    engine = _engine()
    ts = datetime(2026, 10, 2, tzinfo=timezone.utc)
    engine.note_mark("BTCUSDT", 60000.0, ts_utc=ts)
    assert engine.valuation_mark_ts("BTCUSDT") == ts


def test_mark_price_marks_carry_exchange_time():
    engine = _engine()
    t0ms = int(T0.timestamp() * 1000)
    engine.note_event(_mark_record(t0ms + 1000, 60000.0))
    assert engine.valuation_mark("BTCUSDT") == 60000.0
    assert engine.valuation_mark_ts("BTCUSDT") == datetime.fromtimestamp(
        (t0ms + 1000) / 1000, tz=timezone.utc)


def test_settled_funding_total_matches_emitted_and_ledger():
    engine = _engine()
    assert engine.settled_funding_total() == 0.0
    assert engine.settled_funding_total("BTCUSDT") == 0.0
    t0ms = int(T0.timestamp() * 1000)
    _quote(engine, 0, 60000.00, 60000.50)
    engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    _quote(engine, 1, 60001.00, 60001.50)
    assert [e for e in engine.poll() if e.kind == "fill"]
    engine.note_event(_mark_record(t0ms + 1000, 60000.0, rate=0.0001,
                                   next_ms=t0ms + 1000))
    fundings = [e for e in engine.poll() if e.kind == "funding"]
    assert len(fundings) == 1
    payload = fundings[0].payload
    assert isinstance(payload, EngineFunding)
    assert engine.settled_funding_total("BTCUSDT") == pytest.approx(payload.amount)
    assert engine.settled_funding_total() == pytest.approx(payload.amount)
    # Ledger-side of the reconcile: booking the emitted event agrees.
    ledger = Ledger(10000.0)
    assert ledger.record_funding(payload.amount, payload.ts_utc,
                                 payload.event_id) is True
    assert ledger.funding_net() == pytest.approx(engine.settled_funding_total())
    # Same boundary never settles (or totals) twice.
    engine.note_event(_mark_record(t0ms + 1000, 60000.0, rate=0.0001,
                                   next_ms=t0ms + 1000))
    assert [e for e in engine.poll() if e.kind == "funding"] == []
    assert engine.settled_funding_total() == pytest.approx(payload.amount)
