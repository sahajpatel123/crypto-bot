"""Runtime-trader unit tests (Worker 2, E-007). Real nautilus engine.

Requires nautilus_trader (trial venv); skipped in the stdlib-only project env.
"""
from datetime import UTC, datetime, timedelta

import pytest

nautilus = pytest.importorskip("nautilus_trader")

from cryptobot.accounting.ledger import Ledger  # noqa: E402
from cryptobot.adapters import NautilusPaperEngine  # noqa: E402
from cryptobot.execution import RuntimeTrader  # noqa: E402

T0 = datetime(2026, 10, 1, tzinfo=UTC)


class _Sink:
    def __init__(self):
        self.deltas = []
        self.fills = []
        self.releases = []
        self.flats = 0

    def note_fill_delta(self, reservation_id, exec_id, symbol, venue_side,
                        qty, price, fee, ts_utc):
        self.deltas.append((reservation_id, exec_id, symbol, venue_side,
                            qty, price, fee, ts_utc))

    def note_fill(self, reservation_id):
        self.fills.append(reservation_id)

    def release(self, reservation_id):
        self.releases.append(reservation_id)
        return True

    def note_flat(self):
        self.flats += 1


def _setup(tmp_path, **kw):
    now = [T0]
    engine = NautilusPaperEngine(outcome_sink=None, taker_bps=5.0,
                                 now_utc=lambda: now[0],
                                 submit_delay_ms=0, fill_delay_ms=1)
    engine.add_instrument("BTCUSDT", price_precision=2, size_precision=3,
                          tick_size=0.01, step_size=0.001, ts_utc=T0)
    trader = RuntimeTrader(engine, log_path=tmp_path / "rt.jsonl",
                           now_utc=lambda: now[0], **kw)
    return engine, trader, now


def _quote(engine, i, bid, ask):
    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.model.objects import Price, Quantity
    ts = int((T0 + timedelta(seconds=i)).timestamp() * 1e9)
    engine.feed(QuoteTick(engine.instrument_id("BTCUSDT"),
                          Price(bid, 2), Price(ask, 2),
                          Quantity(1.0, 3), Quantity(1.0, 3), ts, ts))


def _filled_cycle(engine, trader, res="res-1", qty=0.002, tick=0):
    """Entry fill + protection attached; returns (entry_id, legs)."""
    _quote(engine, tick, 60000.00, 60000.50)
    entry = trader.submit_entry("BTCUSDT", "LONG", qty, reservation_id=res)
    _quote(engine, tick + 1, 60001.00, 60001.50)
    assert trader.poll()
    legs = trader.protect(res, 59990.00, 60010.00)
    assert len(legs) == 2
    _quote(engine, tick + 2, 60001.00, 60001.50)  # legs accepted.
    trader.poll()
    return entry, legs


def test_entry_fill_converts_and_propagates_real_fee(tmp_path):
    sink = _Sink()
    engine, trader, _ = _setup(tmp_path, outcome_sink=sink)
    _quote(engine, 0, 60000.00, 60000.50)
    trader.submit_entry("BTCUSDT", "LONG", 0.002, reservation_id="res-1")
    _quote(engine, 1, 60001.00, 60001.50)
    trader.poll()
    assert sink.fills == ["res-1"]  # fill-first conversion, exactly once.
    assert len(sink.deltas) == 1
    res, exec_id, sym, side, qty, price, fee, ts = sink.deltas[0]
    assert (res, sym, side) == ("res-1", "BTCUSDT", "BUY")
    # CORR-EXEC: entry due at T0 fills at the T0 ask (60000.50).
    assert qty == pytest.approx(0.002) and fee == pytest.approx(60000.5 * 0.002 * 0.0005)
    assert fee > 0 and exec_id  # real simulator fee, durable exec id.
    trader.poll()  # idempotent: no duplicate callbacks.
    assert sink.fills == ["res-1"] and len(sink.deltas) == 1


def test_target_fill_settles_stop_and_fires_flat(tmp_path):
    sink = _Sink()
    engine, trader, _ = _setup(tmp_path, outcome_sink=sink)
    _, legs = _filled_cycle(engine, trader)
    _quote(engine, 3, 60011.00, 60011.50)  # target triggers and fills.
    events = trader.poll()
    assert any(e["event"].startswith("sibling-cancelled-after") for e in events)
    _quote(engine, 4, 60012.00, 60012.50)  # stop cancel lands.
    trader.poll()
    assert trader.position_net("res-1") == pytest.approx(0.0)
    assert sink.flats == 1  # reconciled net-zero, nothing live.
    assert legs[0] in [c for c in trader._terminal]  # stop verified cancelled.


def test_stop_fill_cancels_target(tmp_path):
    sink = _Sink()
    engine, trader, _ = _setup(tmp_path, outcome_sink=sink)
    _, legs = _filled_cycle(engine, trader)
    _quote(engine, 3, 59989.00, 59989.50)  # stop triggers and fills.
    trader.poll()
    _quote(engine, 4, 59988.00, 59988.50)
    trader.poll()
    assert trader.position_net("res-1") == pytest.approx(0.0)
    assert sink.flats == 1
    assert legs[1] in trader._terminal  # target verified cancelled.


def test_dead_entry_releases_reservation(tmp_path):
    sink = _Sink()
    engine, trader, _ = _setup(tmp_path, outcome_sink=sink)
    _quote(engine, 0, 60000.00, 60000.50)
    # Non-marketable LIMIT IOC: cancels with zero fills.
    trader.submit_entry("BTCUSDT", "LONG", 0.001, kind="LIMIT", price=59000.00,
                        reservation_id="res-1")
    _quote(engine, 1, 60001.00, 60001.50)
    trader.poll()
    assert sink.releases == ["res-1"]
    assert sink.fills == [] and sink.flats == 0


def test_entry_expiry_refused_pre_submit(tmp_path):
    _, trader, _ = _setup(tmp_path)
    with pytest.raises(ValueError, match="entry-expired"):
        trader.submit_entry("BTCUSDT", "LONG", 0.001,
                            expire_at_utc=T0 - timedelta(seconds=1),
                            reservation_id="res-1")


def test_time_exit_flattens_via_immediate(tmp_path):
    sink = _Sink()
    engine, trader, now = _setup(tmp_path, outcome_sink=sink)
    _filled_cycle(engine, trader)
    trader.set_time_exit("res-1", T0 + timedelta(seconds=30))
    assert trader.check_time_exits(T0 + timedelta(seconds=10)) == []
    events = trader.check_time_exits(T0 + timedelta(seconds=31))
    assert [e["event"] for e in events] == ["time-exit"]
    _quote(engine, 3, 60002.00, 60002.50)
    _quote(engine, 4, 60003.00, 60003.50)
    trader.poll()
    trader.poll()
    assert trader.position_net("res-1") == pytest.approx(0.0)
    assert sink.flats == 1


def test_halt_blocks_entries_not_exits_and_persists(tmp_path):
    engine, trader, _ = _setup(tmp_path)
    _filled_cycle(engine, trader)
    trader.set_halted(True, "risk:halt-test")
    with pytest.raises(PermissionError, match="exit-only"):
        trader.submit_entry("BTCUSDT", "LONG", 0.001, reservation_id="res-2")
    assert trader.flatten("res-1", "halt-flatten") is not None  # exits still go.
    log_text = (tmp_path / "rt.jsonl").read_text()
    assert "halt-engaged" in log_text
    # Level persists across recovery.
    recovered = RuntimeTrader.recover(engine, tmp_path / "rt.jsonl",
                                      now_utc=lambda: T0)
    assert recovered.exit_only is True
    with pytest.raises(PermissionError, match="exit-only"):
        recovered.submit_entry("BTCUSDT", "LONG", 0.001, reservation_id="res-3")


class _StubEngine:
    """Scripted S3 engine for trader-logic races the sim refuses to produce."""

    def __init__(self):
        self._events = []
        self._status = {}
        self._qty = {}
        self._seq = 0
        self.exit_only = False

    def _mint(self, role):
        self._seq += 1
        cid = f"stub-{self._seq:04d}"
        self._status[cid] = "ACCEPTED"
        self._qty[cid] = 0.0
        return cid

    def submit(self, cmd):
        cid = self._mint(cmd.role)
        self._qty[cid] = cmd.qty
        return cid

    def submit_immediate(self, cmd):
        return self.submit(cmd)

    def resolve(self, cid):
        return cid if cid in self._status else None

    def attach_protection(self, entry_id, stop_price, target_price):
        legs = [self._mint("stop")]
        if target_price is not None:
            legs.append(self._mint("target"))
        return legs

    def cancel(self, cid, reason):
        if cid in self._status:
            self._status[cid] = "CANCELED"

    def poll(self):
        drained, self._events = self._events, []
        return drained

    def queue(self, event):
        self._events.append(event)

    def open_orders(self):
        from cryptobot.app.engine import EngineOrderStatus
        return [EngineOrderStatus(c, "BTCUSDT",
                                  "cancelled" if s == "CANCELED" else "open",
                                  self._qty[c], 0.0, "res-1", "stop")
                for c, s in self._status.items()]

    def filled_qty(self, cid):
        return 0.0

    def order_status(self, cid):
        return self._status[cid]

    def set_exit_only(self, halted, reason=""):
        self.exit_only = halted

    def note_mark(self, instrument, price):
        pass

    def recover(self, sink):
        pass

    def close(self):
        pass


def _fill_event(cid, side, qty, price, exec_id, ts):
    from cryptobot.app.engine import EngineEvent, EngineFill
    return EngineEvent("fill", EngineFill(
        execution_id=exec_id, client_order_id=cid, instrument="BTCUSDT",
        side=side, qty=qty, price=price, fee=qty * price * 0.0005,
        ts_utc=ts, liquidity="taker"), ts)


def test_exit_race_overfill_freezes_further_exits(tmp_path):
    # Venue-side race (both legs fill before either cancel lands): the trader
    # books truthfully, freezes further exits, and never reports flat.
    sink = _Sink()
    engine = _StubEngine()
    trader = RuntimeTrader(engine, log_path=tmp_path / "rt.jsonl",
                           outcome_sink=sink, now_utc=lambda: T0)
    entry = trader.submit_entry("BTCUSDT", "LONG", 0.002, reservation_id="res-1")
    with pytest.raises(ValueError, match="with fills"):
        trader.protect("res-1", 59990.00, 60010.00)
    trader._client_fills[entry] = 0.002  # race setup: entry filled at venue.
    legs = [engine._mint("stop"), engine._mint("target")]
    for leg, role in zip(legs, ("stop", "target")):
        trader._client_reservation[leg] = "res-1"
        trader._client_role[leg] = role
        trader._legs.setdefault("res-1", {})[leg] = role
    engine.queue(_fill_event(entry, "BUY", 0.002, 60001.0, "ex-1", T0))
    engine.queue(_fill_event(legs[0], "SELL", 0.002, 59990.0, "ex-2", T0))
    engine.queue(_fill_event(legs[1], "SELL", 0.002, 60010.0, "ex-3", T0))
    events = trader.poll()
    assert any(e["event"] == "exit-overfill-freeze" for e in events)
    assert trader.position_net("res-1") == pytest.approx(-0.002)  # exits overshot.
    assert sink.flats == 0  # terminal state never implies flat.
    assert trader.flatten("res-1", "manual") is None  # frozen: no compounding.
    assert "res-1" in trader._frozen


def test_sim_cancels_reduce_only_stop_once_flat(tmp_path):
    # The simulator itself prevents the bracket race: after the target flattens
    # the position, the reduce-only stop cancels instead of filling.
    sink = _Sink()
    engine, trader, _ = _setup(tmp_path, outcome_sink=sink)
    _, legs = _filled_cycle(engine, trader)
    _quote(engine, 3, 60011.00, 60011.50)  # target fills; settle cancels stop.
    trader.poll()
    _quote(engine, 4, 59989.00, 59989.50)  # crash through the stop level.
    trader.poll()
    assert trader.position_net("res-1") == pytest.approx(0.0)
    assert legs[0] in trader._terminal  # stop cancelled, never filled.
    assert sink.flats == 1 and "res-1" not in trader._frozen


def test_top_up_covers_late_second_entry(tmp_path):
    engine, trader, _ = _setup(tmp_path)
    _filled_cycle(engine, trader, qty=0.001)
    _quote(engine, 3, 60002.00, 60002.50)
    trader.submit_entry("BTCUSDT", "LONG", 0.001, reservation_id="res-1")
    _quote(engine, 4, 60003.00, 60003.50)
    events = trader.poll()
    assert any(e["event"].startswith("protection-topup") for e in events)
    assert len(trader._legs["res-1"]) == 4  # incremental pair added.


def test_recover_rebuilds_and_replays_without_dupes(tmp_path):
    engine, trader, _ = _setup(tmp_path)  # no sink: deltas unpropagated.
    _filled_cycle(engine, trader)
    sink = _Sink()
    recovered = RuntimeTrader.recover(engine, tmp_path / "rt.jsonl",
                                      outcome_sink=sink, now_utc=lambda: T0)
    assert len(sink.deltas) == 1  # at-least-once replay on recovery.
    assert sink.fills == ["res-1"]
    recovered.poll()  # live engine still holds the legs: no lost marks, no dupes.
    assert len(sink.deltas) == 1 and sink.fills == ["res-1"]
    assert recovered._terminal.get("pe-000001-00000000", None) is None
    assert not any(v == "lost-on-restart" for v in recovered._terminal.values())


def test_recover_marks_lost_and_releases_unfilled(tmp_path):
    engine, _, _ = _setup(tmp_path)
    trader = RuntimeTrader(engine, log_path=tmp_path / "rt.jsonl", now_utc=lambda: T0)
    trader.submit_entry("BTCUSDT", "LONG", 0.001, reservation_id="res-1")
    fresh_engine = NautilusPaperEngine(outcome_sink=None, taker_bps=5.0,
                                       now_utc=lambda: T0,
                                       submit_delay_ms=0, fill_delay_ms=1)
    fresh_engine.add_instrument("BTCUSDT", price_precision=2, size_precision=3,
                                tick_size=0.01, step_size=0.001, ts_utc=T0)
    sink = _Sink()
    recovered = RuntimeTrader.recover(fresh_engine, tmp_path / "rt.jsonl",
                                      outcome_sink=sink, now_utc=lambda: T0)
    assert list(recovered._terminal.values()) == ["lost-on-restart"]
    assert sink.releases == ["res-1"]  # never filled, never will: release is correct.
    assert sink.fills == [] and sink.flats == 0


def test_recover_flags_open_exposure_without_flat(tmp_path):
    engine, trader, _ = _setup(tmp_path)
    _filled_cycle(engine, trader)
    fresh_engine = NautilusPaperEngine(outcome_sink=None, taker_bps=5.0,
                                       now_utc=lambda: T0,
                                       submit_delay_ms=0, fill_delay_ms=1)
    fresh_engine.add_instrument("BTCUSDT", price_precision=2, size_precision=3,
                                tick_size=0.01, step_size=0.001, ts_utc=T0)
    sink = _Sink()
    recovered = RuntimeTrader.recover(fresh_engine, tmp_path / "rt.jsonl",
                                      outcome_sink=sink, now_utc=lambda: T0)
    assert sink.fills == ["res-1"] and sink.flats == 0  # fills stand; never flat.
    assert "restart-exposure-open" in (tmp_path / "rt.jsonl").read_text()
    assert recovered.position_net("res-1") == pytest.approx(0.002)


def test_funding_books_and_skips(tmp_path):
    ledger = Ledger(10_000.0)
    _, trader, _ = _setup(tmp_path, ledger=ledger)
    ts = T0 + timedelta(hours=8)
    assert trader.ingest_funding("BTCUSDT", -1.5, "fund-1", ts) is True
    assert ledger.funding_net() == pytest.approx(-1.5)
    assert trader.ingest_funding("BTCUSDT", -1.5, "fund-1", ts) is False  # dup.
    assert trader.ingest_funding("BTCUSDT", 0.0, "fund-2", ts) is False  # zero skipped.
