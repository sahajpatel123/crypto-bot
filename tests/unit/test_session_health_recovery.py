"""F2: the Session health gate latches level-wise and releases on clear.

Round X1-R1 (deep research) filed F2: a `health:stale-mark` verdict from
a quiet-window snapshot latched Session exit-only once and never
released it (only a day roll or emergency recovery could). All 24 round
cells produced 0 fills — the round measured the latch, not the
strategies — and the single stuck latch re-wrote run state on every
market event (~8.2M duplicate transitions / ~1 GB journal in the S1
control cell).

These tests pin the fixed semantics:

- a not-ok snapshot latches entry blocking (fail-closed) exactly once,
  even when the stale condition persists across many events;
- a later ok snapshot releases exactly the reasons this gate latched
  and flips the run back to ready only when nothing else blocks entries;
- other exit-only reasons (funding mismatch etc.) survive the health
  release and keep the run halted;
- a full release wipe (day reconcile) resets the gate's tracking so a
  still-stale feed re-latches instead of staying silently open;
- a changed health reason releases the previous one.
"""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cryptobot.app.config import load_config
from cryptobot.app.session import Session, WallClock
from cryptobot.app.store import RunStore
from cryptobot.coordination.exits import ExitPolicy, encode_exit_rule
from cryptobot.coordination.intent import DataQuality, ForecastCost, Intent, Side
from cryptobot.coordination.selector import Candidate


def _paper_config(tmp_path: Path):
    text = open("configs/paper.toml").read()
    text = text.replace('mode = "replay"', 'mode = "paper"', 1)
    text = text.replace('kind = "reference"', 'kind = "nautilus"', 1)
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    cfg_path = tmp_path / "paper.toml"
    cfg_path.write_text(text)
    return load_config(cfg_path)


class _HaltEngine:
    """Stub engine with reason-keyed exit-only (live-engine semantics)."""

    model_label = "f2-stub"
    assumptions = ("stub: f2",)

    def __init__(self):
        self.reasons: set[str] = set()
        self.halt_calls: list[tuple[bool, str]] = []
        self.submits: list = []
        self._now = datetime(2020, 1, 1, tzinfo=UTC)

    @property
    def now_utc(self):
        return self._now

    def advance_to(self, ts_utc):
        self._now = ts_utc

    def poll(self):
        return []

    def pop_events(self, max_events: int = 1000):
        return []

    def note_mark(self, instrument, price, ts_utc=None):
        pass

    def note_event(self, event):
        pass

    def valuation_mark(self, instrument):
        return None

    def valuation_mark_ts(self, instrument):
        return None

    def set_exit_only(self, halted, reason=""):
        self.halt_calls.append((bool(halted), reason))
        if halted:
            self.reasons.add(reason or "unspecified")
        else:
            self.reasons.discard(reason)

    def exit_only_reasons(self):
        return tuple(sorted(self.reasons))

    def recover(self, sink):
        pass

    def close(self):
        pass

    def unknown_ids(self):
        return []

    def resolve(self, cid):
        return None

    def cancel(self, cid, reason):
        pass

    def submit(self, cmd):
        if self.reasons:
            raise PermissionError(
                f"exit-only: {','.join(self.exit_only_reasons())}")
        self.submits.append(cmd)
        return "f2-1"

    def submit_immediate(self, cmd):
        return self.submit(cmd)


def _session(tmp_path: Path, engine=None, name="f2-health"):
    engine = engine or _HaltEngine()
    cfg = _paper_config(tmp_path)
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    session = Session(cfg, store, tmp_path / "runs" / name, name,
                      clock=WallClock(), engine=engine)
    session.policy.reconcile_day(120.0, 0.0)
    session.arm_replay_filters(
        {"BTCUSDT": {"tick_size": 0.10, "step_size": 0.001,
                     "min_qty": 0.001, "min_notional": 5.0},
         "ETHUSDT": {"tick_size": 0.01, "step_size": 0.001,
                     "min_qty": 0.001, "min_notional": 5.0}},
        origin="test", asof_utc=datetime.now(UTC))
    session._init_run_files()
    return session, store


def _book(symbol: str, ts_ms: int) -> dict:
    return {"channel": "bookTicker", "symbol": symbol,
            "input_class": "observed-public",
            "exchange_ts_ms": ts_ms, "local_recv_ms": ts_ms + 5,
            "payload": {"bid": 99.99, "ask": 100.01}}


def _run_state_rows(session) -> list:
    path = session.workdir / "risk.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()
            if line.strip()]


def _intent(symbol: str, now: datetime) -> Intent:
    return Intent(
        strategy="S1", version="0.1.0", instrument=symbol,
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
        evidence_ref=f"test:{symbol}", data_quality=DataQuality.CLEAN)


def test_stale_snapshot_latches_once_then_fresh_releases(tmp_path):
    engine = _HaltEngine()
    session, store = _session(tmp_path, engine)
    try:
        old_ms = int(time.time() * 1000) - 30_000
        for _ in range(5):
            session._ingest(_book("ETHUSDT", old_ms), {}, {})
        # Fail-closed: entry blocking latched under the health reason.
        assert engine.exit_only_reasons() == ("health:stale-mark",)
        assert session._exit_only_reasons == {"health:stale-mark"}
        with pytest.raises(PermissionError, match="exit-only"):
            engine.submit(object())
        # Idempotent: one latch write, not one per event (X1-R1 logged
        # ~8.2M duplicate transitions for one stuck latch).
        assert [c for c in engine.halt_calls if c[0]] == [
            (True, "health:stale-mark")]
        rows = [r for r in _run_state_rows(session)
                if r["to_state"] == "halted"]
        assert len(rows) == 1 and rows[0]["reason"] == "health:stale-mark"
        # A fresh snapshot is proof the condition cleared: release.
        now_ms = int(time.time() * 1000)
        session._ingest(_book("ETHUSDT", now_ms), {}, {})
        assert engine.exit_only_reasons() == ()
        assert session._exit_only_reasons == set()
        assert session._health_halt_reasons == set()
        assert store.get_run(session.run_id)["state"] == "ready"
        assert any(r["to_state"] == "ready"
                   and r["reason"] == "health-recovered"
                   for r in _run_state_rows(session))
        engine.submit(object())  # entries flow once fully lifted.
    finally:
        store.close()


def test_health_release_keeps_other_latches(tmp_path):
    engine = _HaltEngine()
    session, store = _session(tmp_path, engine)
    try:
        session._halt_entries("funding-mismatch")
        session._set_state("halted", "funding-mismatch")
        old_ms = int(time.time() * 1000) - 30_000
        session._ingest(_book("ETHUSDT", old_ms), {}, {})
        assert engine.exit_only_reasons() == (
            "funding-mismatch", "health:stale-mark")
        now_ms = int(time.time() * 1000)
        session._ingest(_book("ETHUSDT", now_ms), {}, {})
        # The funding latch is not the health gate's to release.
        assert engine.exit_only_reasons() == ("funding-mismatch",)
        assert session._exit_only_reasons == {"funding-mismatch"}
        # ...and the run must not claim ready while it stands.
        assert store.get_run(session.run_id)["state"] == "halted"
    finally:
        store.close()


def test_release_all_resets_tracking_and_relatches(tmp_path):
    engine = _HaltEngine()
    session, store = _session(tmp_path, engine)
    try:
        old_ms = int(time.time() * 1000) - 30_000
        session._ingest(_book("ETHUSDT", old_ms), {}, {})
        assert engine.exit_only_reasons() == ("health:stale-mark",)
        session._release_all_exit_only("day-reconciled")
        assert engine.exit_only_reasons() == ()
        assert session._health_halt_reasons == set()
        # Still stale: the next snapshot re-latches (never silently open).
        session._ingest(_book("ETHUSDT", old_ms), {}, {})
        assert engine.exit_only_reasons() == ("health:stale-mark",)
    finally:
        store.close()


def test_reason_change_releases_previous_reason(tmp_path):
    engine = _HaltEngine()
    session, store = _session(tmp_path, engine)
    try:
        old_ms = int(time.time() * 1000) - 30_000
        session._ingest(_book("ETHUSDT", old_ms), {}, {})
        assert engine.exit_only_reasons() == ("health:stale-mark",)
        # Mark observations disappear entirely -> unknown-age block.
        session._feeds["ETHUSDT"].mark = None
        session._health_tick()
        assert engine.exit_only_reasons() == ("health:mark-age-unknown",)
        assert session._health_halt_reasons == {"health:mark-age-unknown"}
        rows = _run_state_rows(session)
        assert rows[-1]["to_state"] == "halted"
        assert rows[-1]["reason"] == "health:mark-age-unknown"
    finally:
        store.close()


class _BoolEngine(_HaltEngine):
    """Paper-shaped halt: one bool, any lift label clears it."""

    def __init__(self):
        super().__init__()
        self.halted = False

    def set_exit_only(self, halted, reason=""):
        self.halt_calls.append((bool(halted), reason))
        self.halted = bool(halted)

    def exit_only_reasons(self):
        return ("paper-bool",) if self.halted else ()


def test_paper_bool_survivor_reasserted(tmp_path):
    engine = _BoolEngine()
    session, store = _session(tmp_path, engine)
    try:
        session._halt_entries("funding-mismatch")
        assert engine.halted is True
        old_ms = int(time.time() * 1000) - 30_000
        session._ingest(_book("ETHUSDT", old_ms), {}, {})
        now_ms = int(time.time() * 1000)
        session._ingest(_book("ETHUSDT", now_ms), {}, {})
        # The mark halt lifted, but the funding latch survives: the paper
        # engine's single bool must still read halted.
        assert session._exit_only_reasons == {"funding-mismatch"}
        assert engine.halted is True
        assert engine.halt_calls[-1] == (True, "funding-mismatch")
        assert store.get_run(session.run_id)["state"] == "halted"
    finally:
        store.close()


def test_supervision_tick_never_releases(tmp_path):
    engine = _HaltEngine()
    session, store = _session(tmp_path, engine)
    try:
        old_ms = int(time.time() * 1000) - 30_000
        session._ingest(_book("ETHUSDT", old_ms), {}, {})
        assert engine.exit_only_reasons() == ("health:stale-mark",)
        # Exactly what _supervise runs: a timer tick with no snapshot.
        # No observation, no release — the latch must survive it.
        tick = session.policy.monitor_tick(account=None)
        assert tick.ok  # no policy-level latch is involved
        assert engine.exit_only_reasons() == ("health:stale-mark",)
        assert session._exit_only_reasons == {"health:stale-mark"}
    finally:
        store.close()


def test_entries_flow_after_mark_recovery(tmp_path):
    """The X1-R1 failure mode end-to-end: blocked while stale, then the
    submit path works again once a fresh snapshot lands."""
    engine = _HaltEngine()
    session, store = _session(tmp_path, engine)
    try:
        old_ms = int(time.time() * 1000) - 30_000
        session._ingest(_book("ETHUSDT", old_ms), {}, {})
        with pytest.raises(PermissionError, match="exit-only"):
            engine.submit(object())
        now_ms = int(time.time() * 1000)
        session._ingest(_book("ETHUSDT", now_ms), {}, {})
        session._maybe_admit(
            [Candidate("S1", _intent("ETHUSDT", session.now_utc()))])
        assert session._position is not None
        assert len(engine.submits) == 1
    finally:
        store.close()
