"""F0.5 triage batch 3: protection legs (B#11, B#2/B#12, B#17).

B#11 (MEDIUM): attach_protection submitting leg1 then failing leg2
must roll leg1 back (cancel) or surface its id for tracking — never
leave a live untracked leg to friendly-fire the next position.
B#2/B#12 (CRITICAL/MEDIUM): session must never attach wrong-way legs
after a reversal: reversed exposure flattens, never re-protects.
B#17 (MEDIUM): user-stream TRADE under a triggered-order id must
attribute to the algo cid via the _triggered map.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from cryptobot.adapters.binance_live import UnknownOutcomeError
from cryptobot.app.config import load_config
from cryptobot.app.session import Session
from cryptobot.app.store import RunStore

NOW = datetime(2026, 10, 17, 12, 0, 0, tzinfo=UTC)


def _session_with(engine, tmp_path: Path) -> Session:
    text = Path("configs/paper.toml").read_text()
    text = text.replace('mode = "replay"', 'mode = "paper"', 1)
    text = text.replace('kind = "reference"', 'kind = "nautilus"', 1)
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    cfg_path = tmp_path / "paper.toml"
    cfg_path.write_text(text)
    return Session(load_config(cfg_path),
                   RunStore(tmp_path / "runs" / "cryptobot.db"),
                   tmp_path / "run", "b3-run", engine=engine)


def test_live_attach_rolls_back_leg1_on_leg2_failure(tmp_path):
    import venue_fixtures as venues
    from cryptobot.adapters.binance_live import VenueRejectedError

    engine, _ = venues.make_engine(tmp_path, [])
    engine._filters["BTCUSDT"] = {"step": 0.001, "tick": 0.1,
                                  "min_qty": 0.001}
    engine.lookup = lambda cid: SimpleNamespace(  # noqa: SLF001
        instrument="BTCUSDT", filled_qty=0.5, qty=0.5,
        reservation_id="r-1")
    engine._venue_side_of = lambda cid: "BUY"  # noqa: SLF001
    calls = []
    cancels = []

    def _submit(cmd):
        calls.append(cmd)
        if len(calls) == 1:
            return "leg-stop-1"
        raise VenueRejectedError(400, -1013, "target bad")

    engine.submit = _submit
    engine.cancel = lambda cid, reason: cancels.append(cid)
    engine._symbols["leg-stop-1"] = "BTCUSDT"  # noqa: SLF001
    with pytest.raises(VenueRejectedError):
        engine.attach_protection("entry-1", 59990.0, 60010.0)
    assert cancels == ["leg-stop-1"], (
        f"leg1 left live untracked: cancels={cancels}")


def test_live_attach_surfaces_leg1_when_rollback_fails(tmp_path):
    import venue_fixtures as venues
    from cryptobot.adapters.binance_live import VenueRejectedError

    engine, _ = venues.make_engine(tmp_path, [])
    engine._filters["BTCUSDT"] = {"step": 0.001, "tick": 0.1,  # noqa: SLF001
                                  "min_qty": 0.001}
    engine.lookup = lambda cid: SimpleNamespace(  # noqa: SLF001
        instrument="BTCUSDT", filled_qty=0.5, qty=0.5,
        reservation_id="r-1")
    engine._venue_side_of = lambda cid: "BUY"  # noqa: SLF001
    calls = []

    def _submit(cmd):
        calls.append(cmd)
        if len(calls) == 1:
            return "leg-stop-1"
        raise VenueRejectedError(400, -1013, "target bad")

    engine.submit = _submit

    def _cancel_boom(cid, reason):
        raise UnknownOutcomeError(cid, "cancel 504")

    engine.cancel = _cancel_boom
    with pytest.raises(VenueRejectedError) as excinfo:
        engine.attach_protection("entry-1", 59990.0, 60010.0)
    assert getattr(excinfo.value, "partial_leg_id", None) == "leg-stop-1"


def test_paper_attach_rolls_back_leg1(tmp_path):
    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.model.objects import Price, Quantity

    from cryptobot.adapters.paper_engine import NautilusPaperEngine
    from cryptobot.app.engine import EngineOrder

    t0 = datetime(2026, 10, 1, tzinfo=UTC)
    engine = NautilusPaperEngine(submit_delay_ms=0, fill_delay_ms=1)
    engine.add_instrument("BTCUSDT", price_precision=2, size_precision=3,
                          tick_size=0.10, step_size=0.001, ts_utc=t0)

    def quote(i, bid, ask):
        tick = QuoteTick(
            instrument_id=engine.instrument_id("BTCUSDT"),
            bid_price=Price(bid, 2), ask_price=Price(ask, 2),
            bid_size=Quantity(1.0, 3), ask_size=Quantity(1.0, 3),
            ts_event=int((t0 + timedelta(seconds=i)).timestamp() * 1e9),
            ts_init=int((t0 + timedelta(seconds=i)).timestamp() * 1e9))
        engine.feed(tick)

    quote(0, 60000.00, 60000.50)
    entry = engine.submit(EngineOrder(
        instrument="BTCUSDT", side="BUY", qty=0.01, kind="MARKET",
        reservation_id="r-1", role="entry"))
    for i in range(1, 5):
        quote(i, 60000.00 + i, 60000.50 + i)
        engine.poll()
    st = engine.order_status(entry)
    assert st is not None and st.filled_qty > 0, "entry did not fill"
    real_submit = engine.submit
    calls = []

    def _flaky(cmd):
        calls.append(cmd)
        if len(calls) == 2:
            raise OverflowError("queue full")
        return real_submit(cmd)

    engine.submit = _flaky
    cancels = []
    engine.cancel = lambda cid, reason: cancels.append(cid)
    with pytest.raises(OverflowError):
        engine.attach_protection(entry, 59990.0, 60010.0)
    # Leg1 (the 1st protection submit) must have a cancel requested.
    assert len(cancels) == 1, f"leg1 left live untracked: {cancels}"


def _reversed_session(tmp_path: Path):
    class _Eng:
        model_label = "b3"
        assumptions = ()

        def __init__(self):
            self.submits = []
            self.statuses = {}

        def poll(self):
            return []

        def open_orders(self):
            return []

        def order_status(self, cid):
            return self.statuses.get(cid)

        def cancel(self, cid, reason):
            return None

        def submit_immediate(self, cmd):
            self.submits.append(cmd)
            return f"close-{len(self.submits)}"

        def attach_protection(self, entry, stop, target):
            raise AssertionError("must not attach on reversed exposure")

        def account_snapshot(self):
            from types import SimpleNamespace as _NS
            return _NS(positions=())

    engine = _Eng()
    session = _session_with(engine, tmp_path)
    # LONG position whose ledger net is SHORT (double-fill reversal).
    session.ledger.record_fill("BUY", 0.5, 60000.0, 1.0, NOW, "e1",
                               symbol="BTCUSDT")
    session.ledger.record_fill("SELL", 0.5, 59900.0, 1.0, NOW, "e2",
                               symbol="BTCUSDT")
    session.ledger.record_fill("SELL", 0.5, 59900.0, 1.0, NOW, "e3",
                               symbol="BTCUSDT")
    assert session.ledger.position_qty() == -0.5
    session._position = {  # noqa: SLF001
        "instrument": "BTCUSDT", "reservation_id": "r-1",
        "side": "LONG", "entry_id": "entry-1", "entry_pre_id": "entry-1",
        "legs": [], "retired": [], "close_ids": [],
        "cancel_requested": set(), "seen_ids": set(),
        "protected": False, "protect_attempts": 0, "attach_filled": 0.0,
        "stop": 59900.0, "target": 60100.0,
        "time_exit": datetime(2030, 1, 1, tzinfo=UTC)}
    engine.statuses["entry-1"] = SimpleNamespace(state="filled",
                                                 filled_qty=0.5)
    return session, engine


def test_reversed_exposure_flattens_never_protects(tmp_path):
    session, engine = _reversed_session(tmp_path)
    session._ensure_protection_inner(session._position)  # noqa: SLF001
    assert len(engine.submits) == 1  # one reduce-only close of -0.5
    assert engine.submits[0].side == "BUY"
    assert session._position["legs"] == []  # noqa: SLF001


def test_attach_unknown_leg_gets_tracked(tmp_path):
    class _Eng2:
        model_label = "b3b"
        assumptions = ()

        def poll(self):
            return []

        def open_orders(self):
            return []

        def order_status(self, cid):
            if cid == "entry-1":
                return SimpleNamespace(state="filled", filled_qty=0.5,
                                       qty=0.5)
            return None

        def cancel(self, cid, reason):
            return None

        def attach_protection(self, entry, stop, target):
            raise UnknownOutcomeError("leg-unknown-1", "submit 504")

    engine = _Eng2()
    session = _session_with(engine, tmp_path)
    session.ledger.record_fill("BUY", 0.5, 60000.0, 1.0, NOW, "e1",
                               symbol="BTCUSDT")
    session._position = {  # noqa: SLF001
        "instrument": "BTCUSDT", "reservation_id": "r-1",
        "side": "LONG", "entry_id": "entry-1", "entry_pre_id": "entry-1",
        "legs": [], "retired": [], "close_ids": [],
        "cancel_requested": set(), "seen_ids": set(),
        "protected": False, "protect_attempts": 0, "attach_filled": 0.0,
        "stop": 59900.0, "target": 60100.0,
        "time_exit": datetime(2030, 1, 1, tzinfo=UTC)}
    session._ensure_protection_inner(session._position)  # noqa: SLF001
    assert "leg-unknown-1" in session._position["legs"]  # noqa: SLF001


def test_triggered_trade_attributes_to_algo_cid(tmp_path):
    import venue_fixtures as venues

    engine, _ = venues.make_engine(tmp_path, [])
    engine.note_user_event({
        "e": "ALGO_UPDATE", "E": 1_700_000_000_000,
        "o": {"s": "BTCUSDT", "c": "algo-1", "S": "SELL", "X": "TRIGGERED",
              "x": "TRIGGERED", "ti": "TRIG-9"}})
    engine.note_user_event({
        "e": "ORDER_TRADE_UPDATE", "E": 1_700_000_001_000,
        "o": {"s": "BTCUSDT", "c": "TRIG-9", "S": "SELL", "X": "FILLED",
              "x": "TRADE", "l": "0.5", "L": "59900.0", "N": "USDT",
              "n": "1.0", "t": 777}})
    assert engine._adopted_qty.get("algo-1", 0.0) == 0.5  # noqa: SLF001
