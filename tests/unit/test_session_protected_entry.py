"""Directive L76: protected IOC entries, band caps, expiry enforcement."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptobot.app.config import load_config
from cryptobot.app.session import Session
from cryptobot.app.store import RunStore
from cryptobot.coordination.exits import ExitPolicy, encode_exit_rule
from cryptobot.coordination.intent import DataQuality, ForecastCost, Intent, Side
from cryptobot.coordination.selector import Candidate


def _config(tmp_path: Path, **over) -> Path:
    text = Path("configs/paper.toml").read_text()
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    for key, value in over.items():
        text = text.replace(f"{key} =", f"{key} = {value} #", 1)
    path = tmp_path / "test.toml"
    path.write_text(text)
    return path


def test_side_aware_tick_rounding():
    from cryptobot.risk.rounding import ceil_to_tick, floor_to_tick
    # BUY caps round DOWN: never pay above the band top.
    assert floor_to_tick(100.55, 0.10) == 100.5
    assert floor_to_tick(100.50, 0.10) == 100.5
    # SELL floors round UP: never accept below the band floor.
    assert ceil_to_tick(100.55, 0.10) == 100.6
    assert ceil_to_tick(100.50, 0.10) == 100.5


def _intent(now: datetime, **over) -> Intent:
    args = dict(
        strategy="S1", version="0.1.0", instrument="BTCUSDT",
        side=Side.LONG, evidence_ts_utc=now,
        entry_low=100.0, entry_high=100.55,
        entry_expiry_utc=now + timedelta(seconds=60),
        invalidation_price=99.0,
        exit_rule=encode_exit_rule(ExitPolicy(
            stop_price=99.0, target_price=102.0,
            time_exit_utc=now + timedelta(seconds=600),
            policy_id="test")),
        holding_limit_s=600,
        forecast_cost=ForecastCost(5.0, 5.0, 5.0, 1.0),
        evidence_ref="test:1", data_quality=DataQuality.CLEAN)
    args.update(over)
    return Intent(**args)


class _RecordingEngine:
    def __init__(self):
        from cryptobot.app.session import Session as _S  # noqa: F401
        self.protected_calls: list = []
        self.plain_calls: list = []
        self.raise_notimpl = False

    def submit_protected(self, cmd, limit_price):
        if self.raise_notimpl:
            raise NotImplementedError("reference engine has no protected IOC")
        self.protected_calls.append((cmd, limit_price))
        return "pre-1"

    def submit(self, cmd):
        self.plain_calls.append(cmd)
        return "pre-1"

    def resolve(self, cid):
        return None

    def set_exit_only(self, halted, reason=""):
        pass

    def note_mark(self, instrument, price):
        pass

    def recover(self, sink):
        pass

    def close(self):
        pass


def _ready_session(tmp_path: Path, engine) -> tuple[Session, RunStore]:
    cfg = load_config(_config(tmp_path, warmup_bars=3))
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    session = Session(cfg, store, tmp_path / "runs" / "prot-1", "prot-1",
                      engine=engine)
    now = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
    session.clock.set_ms(int(now.timestamp() * 1000))
    session.policy.reconcile_day(120.0, 0.0)
    session.store.create_run("prot-1", "replay", "fp",
                             str(session.workdir), None)
    # Venue tick known: caps quantize side-aware to 0.10.
    session.arm_replay_filters(
        {"BTCUSDT": {"tick_size": 0.10, "step_size": 0.001,
                     "min_qty": 0.001, "min_notional": 5.0}},
        origin="test", asof_utc=now)
    # Fresh valuation mark so the quote-age gate passes (W3-30MIN).
    from cryptobot.app.session import _SymbolFeed
    _feed = _SymbolFeed("BTCUSDT", 0)
    _feed.mark = 100.0
    _feed.mark_ts = now
    session._feeds["BTCUSDT"] = _feed
    return session, store


def test_entry_uses_protected_ioc_with_band_cap(tmp_path):
    engine = _RecordingEngine()
    session, store = _ready_session(tmp_path, engine)
    try:
        now = session.now_utc()
        session._maybe_admit([Candidate("S1", _intent(now))])
        assert session._position is not None
        assert len(engine.protected_calls) == 1
        assert engine.plain_calls == []
        cmd, cap = engine.protected_calls[0]
        # LONG: band top 100.55 floored to tick -> 100.5.
        assert cap == 100.5
        assert session._position["entry_cap"] == 100.5
        assert cmd.expire_at_utc == now + timedelta(seconds=60)
    finally:
        store.close()


def test_short_cap_is_band_floor_ceiled(tmp_path):
    engine = _RecordingEngine()
    session, store = _ready_session(tmp_path, engine)
    try:
        now = session.now_utc()
        intent = _intent(
            now, side=Side.SHORT, entry_low=99.45, entry_high=100.0,
            invalidation_price=101.0)
        session._maybe_admit([Candidate("S1", intent)])
        assert session._position is not None
        _, cap = engine.protected_calls[0]
        # SHORT: band floor 99.45 ceiled to tick -> 99.5.
        assert cap == 99.5
    finally:
        store.close()


def test_expired_opportunity_rejected_never_submitted(tmp_path):
    engine = _RecordingEngine()
    session, store = _ready_session(tmp_path, engine)
    try:
        now = session.now_utc()
        intent = _intent(
            now, evidence_ts_utc=now - timedelta(seconds=120),
            entry_expiry_utc=now - timedelta(seconds=1))
        session._maybe_admit([Candidate("S1", intent)])
        assert session._position is None
        assert engine.protected_calls == []
        assert engine.plain_calls == []
        assert "selection:expired" in session._reject_counts
    finally:
        store.close()


def test_reference_engine_falls_back_to_market(tmp_path):
    engine = _RecordingEngine()
    engine.raise_notimpl = True
    session, store = _ready_session(tmp_path, engine)
    try:
        session._maybe_admit([Candidate("S1", _intent(session.now_utc()))])
        assert session._position is not None
        assert engine.protected_calls == []
        assert len(engine.plain_calls) == 1
    finally:
        store.close()


def test_protected_ioc_fills_at_or_better_through_session(tmp_path):
    # Session-level fill proof: a marketable band cap on a quoted book
    # fills through _maybe_admit -> submit_protected at-or-better.
    pytest = __import__("pytest")
    pytest.importorskip("nautilus_trader")
    from datetime import timedelta

    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.model.objects import Price, Quantity

    from cryptobot.adapters import NautilusPaperEngine

    t0 = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
    now = [t0]
    engine = NautilusPaperEngine(
        taker_bps=5.0, now_utc=lambda: now[0],
        submit_delay_ms=0, fill_delay_ms=1)
    engine.add_instrument("BTCUSDT", price_precision=2, size_precision=3,
                          tick_size=0.10, step_size=0.001, ts_utc=t0)

    def quote(i, bid, ask):
        tick = QuoteTick(
            instrument_id=engine.instrument_id("BTCUSDT"),
            bid_price=Price(bid, 2), ask_price=Price(ask, 2),
            bid_size=Quantity(10.0, 3), ask_size=Quantity(10.0, 3),
            ts_event=int((t0 + timedelta(seconds=i)).timestamp() * 1e9),
            ts_init=int((t0 + timedelta(seconds=i)).timestamp() * 1e9))
        engine.feed(tick)

    quote(0, 100.10, 100.20)
    session, store = _ready_session(tmp_path, engine)
    # Contract v1: Session.__init__ binds the booking handler already.
    try:
        session._maybe_admit([Candidate("S1", _intent(session.now_utc()))])
        assert session._position is not None
        assert session._position["entry_cap"] == 100.5
        quote(1, 100.10, 100.20)
        session._drain_engine()
        assert session.ledger.has_position()
        fills = [r for r in store._db.execute(
            "SELECT payload FROM execution_events WHERE run_id='prot-1'"
            " AND kind='fill'").fetchall()]
        assert len(fills) == 1
        fill = json.loads(fills[0][0])
        assert fill["price"] <= 100.5  # at-or-better than the cap.
        assert fill["fee"] > 0  # realistic costs kept.
    finally:
        store.close()
