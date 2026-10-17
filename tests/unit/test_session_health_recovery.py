"""Regression proofs for the execution blockers reported by the deep run.

Synthetic mechanics only: real Session, SQLite and pinned Nautilus adapter.
These tests do not constitute strategy profitability evidence.
"""
import json
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from cryptobot.adapters import NautilusPaperEngine
from cryptobot.app.config import load_config
from cryptobot.app.engine import EngineOrder
from cryptobot.app.session import ReplayClock, Session
from cryptobot.app.store import RunStore
from cryptobot.coordination import DataQuality, ForecastCost, Intent, Side
from cryptobot.coordination.exits import ExitPolicy, encode_exit_rule
from cryptobot.coordination.selector import Candidate


T0 = datetime(2026, 10, 12, 6, tzinfo=timezone.utc)
T0MS = int(T0.timestamp() * 1000)


@pytest.fixture
def rig(tmp_path):
    config = replace(load_config("configs/paper.toml"), warmup_bars=3,
                     submit_delay_ms=0, fill_delay_ms=1)
    clock = ReplayClock()
    clock.set_ms(T0MS)
    engine = NautilusPaperEngine(
        now_utc=clock.now, taker_bps=config.taker_bps,
        submit_delay_ms=0, fill_delay_ms=1,
        journal_path=tmp_path / "engine.jsonl")
    engine.add_instrument("BTCUSDT", price_precision=2, size_precision=3,
                          tick_size=0.01, step_size=0.001, ts_utc=T0)
    store = RunStore(tmp_path / "store.db")
    session = Session(config, store, tmp_path / "run", "health-recovery",
                      clock=clock, engine=engine)
    store.create_run(session.run_id, "replay", config.fingerprint,
                     str(session.workdir), None)
    session.policy.reconcile_day(config.paper_capital_usdt, 0.0)
    try:
        yield session
    finally:
        engine.close()
        store.close()


def _ingest(session, offset_ms, channel, payload):
    ts = T0MS + offset_ms
    session.clock.set_ms(ts)
    record = {"channel": channel, "symbol": "BTCUSDT", "seq": ts,
              "exchange_ts_ms": ts, "local_recv_ms": ts,
              "payload": payload}
    session._ingest(record, {}, {})


def _book(session, offset_ms):
    _ingest(session, offset_ms, "bookTicker",
            {"bid": 99.99, "ask": 100.01, "bid_qty": 10.0,
             "ask_qty": 10.0})


def _mark(session, offset_ms):
    _ingest(session, offset_ms, "markPrice", {"mark": 100.0})


def _stale(session):
    _book(session, 0)
    _mark(session, 0)
    _book(session, 5000)
    assert "health:stale-mark" in session._exit_only_reasons


def _candidate(now, *, hold_s=120):
    return Candidate("S1", Intent(
        strategy="S1", version="0.1.0", instrument="BTCUSDT",
        side=Side.LONG, evidence_ts_utc=now,
        entry_low=99.99, entry_high=100.10,
        entry_expiry_utc=now + timedelta(seconds=30),
        invalidation_price=99.0,
        exit_rule=encode_exit_rule(ExitPolicy(
            stop_price=99.0, target_price=102.0,
            time_exit_utc=now + timedelta(seconds=hold_s),
            policy_id="health-recovery-test")),
        holding_limit_s=hold_s,
        forecast_cost=ForecastCost(5.0, 5.0, 5.0, 1.0),
        evidence_ref=f"synthetic:health:{now.isoformat()}",
        data_quality=DataQuality.CLEAN))


def test_stale_mark_recovers_and_entry_fills_without_restart(rig):
    _stale(rig)
    rig._maybe_admit([_candidate(rig.now_utc())])
    assert rig._admitted == 0
    assert not rig.ledger.has_position()
    _mark(rig, 5100)
    _book(rig, 5200)
    assert rig.policy.check_health(rig._snapshot_account()).ok
    assert "health:stale-mark" not in rig._exit_only_reasons
    rig._maybe_admit([_candidate(rig.now_utc())])
    _book(rig, 5400)
    assert rig._admitted == 1
    assert rig.ledger.has_position()
    assert rig._position["protected"]


def test_fresh_mark_does_not_clear_persistent_or_foreign_halts(rig):
    _stale(rig)
    rig._halt_entries("funding-mismatch")
    rig.engine.set_exit_only(True, "stream:test")
    _mark(rig, 5100)
    _book(rig, 5200)
    assert "health:stale-mark" not in rig._exit_only_reasons
    assert "funding-mismatch" in rig._exit_only_reasons
    assert rig.engine._exit_only
    reasons = rig.engine.exit_only_reasons()
    assert "funding-mismatch" in reasons and "stream:test" in reasons


def test_freshness_flaps_are_recoverable_and_audited(rig):
    _stale(rig)
    _mark(rig, 5100)
    _book(rig, 5200)
    _book(rig, 7000)
    assert "health:stale-mark" in rig._exit_only_reasons
    _mark(rig, 7100)
    _book(rig, 7200)
    assert "health:stale-mark" not in rig._exit_only_reasons
    rows = [json.loads(line) for line in
            (rig.workdir / "risk.jsonl").read_text().splitlines()]
    changes = [r for r in rows if r["reason"] == "health:stale-mark"
               and r["kind"] in ("entry-halt", "entry-halt-released")]
    assert [r["kind"] for r in changes] == [
        "entry-halt", "entry-halt-released",
        "entry-halt", "entry-halt-released"]


def test_control_tick_rechecks_mark_health_without_market_traffic(rig):
    _book(rig, 0)
    _mark(rig, 0)
    rig.clock.set_ms(T0MS + 5000)
    rig.control_tick()
    assert "health:stale-mark" in rig._exit_only_reasons
    _mark(rig, 5100)
    rig.control_tick()
    assert "health:stale-mark" not in rig._exit_only_reasons


def test_unknown_mark_age_recovers_after_first_observation(rig):
    rig.control_tick()
    assert "health:mark-age-unknown" in rig._exit_only_reasons
    _book(rig, 0)
    assert "health:mark-age-unknown" not in rig._exit_only_reasons
    assert not rig.engine._exit_only


def test_idle_control_step_books_time_exit_before_return(rig):
    _book(rig, 0)
    rig._maybe_admit([_candidate(rig.now_utc(), hold_s=30)])
    _book(rig, 200)
    assert rig._position is not None and rig.ledger.has_position()
    rig.clock.set_ms(T0MS + 30000)
    ctx = {"last_market_mono": time.monotonic(),
           "last_beat": time.monotonic()}
    rig._control_step(None, None, {}, {}, ctx,
                      time.monotonic() + 10, "synthetic")
    # Native fill latency matures on this next idle wake, not on restart.
    rig.clock.set_ms(T0MS + 30200)
    rig._control_step(None, None, {}, {}, ctx,
                      time.monotonic() + 10, "synthetic")
    assert not rig.ledger.has_position()
    assert rig._position is None
    fills = rig.store._db.execute(
        "SELECT count(*) FROM execution_events WHERE kind='fill'").fetchone()[0]
    assert fills == 2


def test_paper_halt_releases_only_its_own_reason(rig):
    rig.engine.set_exit_only(True, "health:stale-mark")
    rig.engine.set_exit_only(True, "funding-mismatch")
    rig.engine.set_exit_only(False, "health:stale-mark")
    with pytest.raises(PermissionError, match="exit-only"):
        rig.engine.submit_protected(EngineOrder(
            "BTCUSDT", "BUY", 0.1, "LIMIT", price=100.1), 100.1)


def test_paper_recovery_preserves_independent_reasons(rig, tmp_path):
    rig.engine.set_exit_only(True, "health:stale-mark")
    rig.engine.set_exit_only(True, "funding-mismatch")
    recovered = NautilusPaperEngine(
        now_utc=rig.now_utc, taker_bps=5.0,
        journal_path=tmp_path / "engine.jsonl")
    try:
        recovered.recover(lambda event: None)
        assert recovered.exit_only_reasons() == (
            "funding-mismatch", "health:stale-mark")
        recovered.set_exit_only(False, "health:stale-mark")
        assert recovered.exit_only_reasons() == ("funding-mismatch",)
        assert recovered._exit_only
    finally:
        recovered.close()


def test_legacy_paper_halt_journal_still_blocks_entries(tmp_path):
    journal = tmp_path / "legacy.jsonl"
    journal.write_text(json.dumps({"event": "exit-only", "detail": {
        "halted": True, "reason": "funding-mismatch"}}) + "\n")
    recovered = NautilusPaperEngine(journal_path=journal)
    try:
        recovered.recover(lambda event: None)
        assert recovered.exit_only_reasons() == ("funding-mismatch",)
        assert recovered._exit_only
    finally:
        recovered.close()


def test_shutdown_budget_exhaustion_preserves_unsettled_exposure(
        rig, monkeypatch):
    _book(rig, 0)
    rig._maybe_admit([_candidate(rig.now_utc())])
    _book(rig, 200)
    assert rig.ledger.has_position()
    rig._flatten("operator-stop-flatten")
    monkeypatch.setenv("CRYPTOBOT_DEADLINE_MONO",
                       str(time.monotonic() - 1.0))
    rig._settle_shutdown_exits()
    assert rig.ledger.has_position()
    assert rig._position is not None
    assert rig._position["close_ids"]
    assert rig.policy.booked_total_qty() > 0
    row = rig.store._db.execute(
        "SELECT payload FROM checkpoints WHERE kind=?",
        ("shutdown-exposure-pending",)).fetchone()
    assert row is not None
    assert json.loads(row[0])["qty"] > 0
