"""Paper contract-v1 tests (Worker 2, release Checkpoint A)."""
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from cryptobot.adapters.paper_engine import NautilusPaperEngine
from cryptobot.app.engine import EngineOrder

T0 = datetime(2026, 10, 1, tzinfo=UTC)


def _engine(tmp_path, **kw):
    kw.setdefault("taker_bps", 5.0)
    kw.setdefault("now_utc", lambda: T0)
    kw.setdefault("submit_delay_ms", 0)
    kw.setdefault("fill_delay_ms", 1)
    kw.setdefault("journal_path", tmp_path / "paper.jsonl")
    engine = NautilusPaperEngine(**kw)
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
        ts_event=int((T0 + timedelta(seconds=i)).timestamp() * 1e9),
        ts_init=int((T0 + timedelta(seconds=i)).timestamp() * 1e9)))


def test_open_orders_excludes_terminal_orders(tmp_path):
    engine = _engine(tmp_path)
    _quote(engine, 0, 60000.00, 60000.50)
    # Marketable limit rests until the next tick (paper LIMIT is
    # taker-only: nonmarketable cancels at arrival, never rests).
    resting = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "LIMIT",
                                        price=60000.50))
    states = {s.client_order_id: (s.state, s.version)
              for s in engine.open_orders()}
    assert states == {resting: ("open", 1)}
    filled = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    _quote(engine, 1, 60001.00, 60001.50)
    assert engine.poll()
    assert engine.open_orders() == []
    # Tracked truth still answers for terminal ids.
    assert engine.order_status(filled).state == "filled"
    assert engine.order_status(filled).version >= 2
    assert engine.order_status(resting).state == "filled"


def test_order_status_tracked_truth_shapes(tmp_path):
    engine = _engine(tmp_path, submit_delay_ms=60_000)
    _quote(engine, 0, 60000.00, 60000.50)
    assert engine.order_status("never-seen") is None
    queued = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    status = engine.order_status(queued)
    assert (status.state, status.version) == ("open", 0)
    assert engine.resolve(queued) is None
    assert engine.unknown_ids() == ()


def test_queued_past_window_is_tracked_expired(tmp_path):
    engine = _engine(tmp_path, submit_delay_ms=60_000)
    cid = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.01, "MARKET",
                                    expire_at_utc=T0 + timedelta(seconds=10)))
    engine.advance_to(T0 + timedelta(seconds=61))
    status = engine.order_status(cid)
    assert status.state == "expired"
    assert status.version == 2  # submitted-intent + terminal.
    assert engine.open_orders() == []


def test_execution_ids_namespaced_and_stable_across_recover(tmp_path):
    engine = _engine(tmp_path, run_tag="rls")
    _quote(engine, 0, 60000.00, 60000.50)
    engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET",
                              reservation_id="r1"))
    _quote(engine, 1, 60001.00, 60001.50)
    fills = [e for e in engine.poll() if e.kind == "fill"]
    assert [f.payload.execution_id for f in fills] == [
        "paper/rls/BTCUSDT/000001"]
    pushed: list = []
    engine2 = _engine(tmp_path, run_tag="rls")
    engine2.recover(pushed.append)
    # Same journaled id re-pushed (Session dedups); the open sim order
    # is lost-on-restart truth, not silently dropped.
    assert [e.payload.execution_id for e in pushed
            if e.kind == "fill"] == ["paper/rls/BTCUSDT/000001"]
    # The new fill must continue the seq, never collide with 000001.
    pushed.clear()
    _quote(engine2, 2, 60002.00, 60002.50)
    engine2.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET",
                               reservation_id="r2"))
    _quote(engine2, 3, 60003.00, 60003.50)
    assert [e for e in engine2.poll()
            if e.kind == "fill"] == []  # pushed, not queued.
    assert [e.payload.execution_id for e in pushed
            if e.kind == "fill"] == ["paper/rls/BTCUSDT/000002"]


def test_bind_sink_pushes_every_emission(tmp_path):
    engine = _engine(tmp_path)
    _quote(engine, 0, 60000.00, 60000.50)
    engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET",
                              reservation_id="r1"))
    _quote(engine, 1, 60001.00, 60001.50)
    pre = engine.poll()
    assert [e.kind for e in pre] == ["fill"]  # pre-binding leftover.
    pushed: list = []
    engine.bind_sink(pushed.append)
    entry = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET",
                                      reservation_id="r2"))
    _quote(engine, 2, 60002.00, 60002.50)  # fill materializes.
    stop_id, _target_id = engine.attach_protection(
        entry, stop_price=59000.00, target_price=61000.00)
    engine.cancel(stop_id, "test")
    _quote(engine, 3, 60003.00, 60003.50)  # cancel materializes.
    t2ms = int((T0 + timedelta(seconds=3)).timestamp() * 1000)
    engine.note_event({
        "v": 1, "format": "cryptobot-events/1",
        "input_class": "observed-public", "source": "binance-fapi-ws",
        "route": "public", "run_id": "r1", "seq": 9,
        "channel": "markPrice", "symbol": "BTCUSDT",
        "exchange_ts_ms": t2ms, "local_recv_ms": t2ms,
        "local_mono_ns": t2ms * 1_000_000, "gap_kind": None, "venue_seq": 9,
        "payload": {"mark": 60002.0, "funding_rate": 0.0001,
                    "next_funding_ms": t2ms}})
    kinds = [e.kind for e in pushed]
    assert kinds == ["fill", "cancel", "funding"]
    assert engine.poll() == []  # pushed, not queued.


def test_bind_sink_rejects_direct_booking_sinks(tmp_path):
    class Sink:
        def note_fill_delta(self, *args):
            raise AssertionError("must never be invoked")

    engine = _engine(tmp_path)
    with pytest.raises(TypeError, match="EngineEvent callable"):
        engine.bind_sink(Sink())
    with pytest.raises(TypeError, match="EngineEvent callable"):
        engine.bind_sink(object())
    with pytest.raises(TypeError, match="EngineEvent callable"):
        engine.recover(Sink())


def test_versions_monotonic_across_transitions(tmp_path):
    engine = _engine(tmp_path)
    _quote(engine, 0, 60000.00, 60000.50)
    entry = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    _quote(engine, 1, 60001.00, 60001.50)
    assert engine.poll()
    assert engine.order_status(entry).version == 2  # submit + fill.
    stop_id, _target_id = engine.attach_protection(
        entry, stop_price=59000.00, target_price=61000.00)
    assert engine.order_status(stop_id).version == 1
    engine.cancel(stop_id, "test")
    _quote(engine, 2, 60002.00, 60002.50)  # cancel materializes.
    assert engine.poll()
    terminal = engine.order_status(stop_id)
    assert terminal.state == "cancelled"
    assert terminal.version == 2


def test_account_snapshot_reports_positions_and_margin(tmp_path):
    engine = _engine(tmp_path)
    snap = engine.account_snapshot()
    assert snap.complete is True and snap.positions == ()
    assert snap.wallet_equity_usdt == pytest.approx(10000.0)
    _quote(engine, 0, 60000.00, 60000.50)
    engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    _quote(engine, 1, 60001.00, 60001.50)
    assert engine.poll()
    snap = engine.account_snapshot()
    assert snap.complete is True
    [(pos,)] = [[p for p in snap.positions]]
    assert pos.instrument == "BTCUSDT" and pos.qty == pytest.approx(0.001)
    assert pos.entry_price == pytest.approx(60000.50)
    assert pos.mark_price is not None
    assert snap.available_margin_usdt < snap.wallet_equity_usdt
    # No mark anywhere: incomplete, never silently flat-valued.
    engine._marks.clear()
    engine._bbo.clear()
    engine._last_print.clear()
    snap = engine.account_snapshot()
    assert snap.complete is False
    assert snap.margin_balance_usdt is None
