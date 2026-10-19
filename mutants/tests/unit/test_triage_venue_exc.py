"""F0.5 triage batch 2: venue-exception contract in session (B#1, A#4/B#5).

B#1 (CRITICAL): admit-time submit raising VenueRejectedError /
RateLimitedError / UnknownOutcomeError must not kill the process.
Deterministic rejects free the hold + record rejected; unknowns keep
the hold (fail-closed), link the engine cid, and record
submitted-unknown for the lookup drain.
A#4/B#5 (HIGH): venue reads (account_margin, open_orders) raising
mid-tick must degrade (block entries / skip tick), never die flat or
flatten-on-blip, never die with exposure.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptobot.adapters.binance_live import (
    RateLimitedError, UnknownOutcomeError, VenueHttpError,
    VenueRejectedError)
from cryptobot.app.config import load_config
from cryptobot.app.session import Session
from cryptobot.app.store import RunStore
from cryptobot.coordination.exits import encode_exit_rule, ExitPolicy
from cryptobot.coordination.intent import (
    DataQuality, ForecastCost, Intent, Side)
from cryptobot.coordination.selector import Candidate

NOW = datetime(2026, 10, 12, 6, 0, tzinfo=timezone.utc)


def _intent(now: datetime) -> Intent:
    return Intent(
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


class _SubmitEngine:
    """Recording engine with scripted submit behavior (no network)."""

    def __init__(self, behavior):
        self.behavior = behavior
        self.submits = []

    def submit_protected(self, cmd, limit_price):
        return self.submit(cmd)

    def submit(self, cmd):
        self.submits.append(cmd)
        if isinstance(self.behavior, Exception):
            raise self.behavior
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

    def poll(self):
        return []

    def open_orders(self):
        return []


def _ready_session(tmp_path: Path, engine) -> Session:
    text = Path("configs/paper.toml").read_text()
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    cfg_path = tmp_path / "test.toml"
    cfg_path.write_text(text)
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    session = Session(load_config(cfg_path), store,
                      tmp_path / "runs" / "b2", "b2", engine=engine)
    session.clock.set_ms(int(NOW.timestamp() * 1000))
    session.policy.reconcile_day(120.0, 0.0)
    session.store.create_run("b2", "replay", "fp", str(session.workdir),
                             None)
    session.arm_replay_filters(
        {"BTCUSDT": {"tick_size": 0.10, "step_size": 0.001,
                     "min_qty": 0.001, "min_notional": 5.0}},
        origin="test", asof_utc=NOW)
    from cryptobot.app.session import _SymbolFeed
    feed = _SymbolFeed("BTCUSDT", 0)
    feed.mark = 100.0
    feed.mark_ts = NOW
    session._feeds["BTCUSDT"] = feed
    return session


def _intents(session, tmp_path):
    import sqlite3

    conn = sqlite3.connect(tmp_path / "runs" / "cryptobot.db")
    try:
        return conn.execute(
            "SELECT decision, reason FROM intents").fetchall()
    finally:
        conn.close()


def test_rejected_submit_frees_hold_and_records(tmp_path):
    engine = _SubmitEngine(VenueRejectedError(400, -2019, "margin"))
    session = _ready_session(tmp_path, engine)
    session._maybe_admit([Candidate("S1", _intent(NOW))])  # noqa: SLF001
    assert session.policy.live_reservations() == ()
    rows = _intents(session, tmp_path)
    assert any(d == "rejected" and "venue-rejected" in (r or "")
               for d, r in rows), rows


def test_ratelimited_submit_frees_hold_and_records(tmp_path):
    engine = _SubmitEngine(RateLimitedError(429, -1003, "limit",
                                            retry_after_s=2.0))
    session = _ready_session(tmp_path, engine)
    session._maybe_admit([Candidate("S1", _intent(NOW))])  # noqa: SLF001
    assert session.policy.live_reservations() == ()
    rows = _intents(session, tmp_path)
    assert any(d == "rejected" and "rate-limited" in (r or "")
               for d, r in rows), rows


def test_unknown_submit_keeps_hold_and_links_cid(tmp_path):
    engine = _SubmitEngine(UnknownOutcomeError("bl-abc-000001", "504"))
    session = _ready_session(tmp_path, engine)
    session._maybe_admit([Candidate("S1", _intent(NOW))])  # noqa: SLF001
    # Fail-closed: the hold stands (re-entry blocked) until lookup.
    assert session.policy.live_reservations() != ()
    cmds = session.store.open_commands("b2")
    assert any(c.get("status") == "unknown"
               and c.get("engine_client_id") == "bl-abc-000001"
               for c in cmds), cmds


def test_health_tick_degrades_on_venue_read_error(tmp_path):
    engine = _SubmitEngine(None)

    def _boom():
        raise VenueHttpError(503, None, "down")

    engine.account_margin = _boom
    session = _ready_session(tmp_path, engine)
    session._health_tick()  # noqa: SLF001 — must not raise
    assert any("degraded-reads" in r
               for r in session._health_halt_reasons)  # noqa: SLF001


def test_stop_actions_survive_open_orders_429(tmp_path):
    engine = _SubmitEngine(None)

    def _boom():
        raise RateLimitedError(429, -1003, "limit", retry_after_s=2.0)

    engine.open_orders = _boom
    session = _ready_session(tmp_path, engine)
    session.policy._state.emergency_latched = True  # noqa: SLF001
    session._run_stop_actions()  # noqa: SLF001 — must not raise
