"""Runtime risk/accounting scenario regressions (Worker 3, V-006).

Public interfaces only; each test asserts the correct BUSINESS outcome for
an autonomous-runtime scenario: callback races, restart agreement, midnight
rollover under exposure, forced-exit signalling, and storage failure.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from helpers import T0, audit_account, audit_intent, make_clock
from cryptobot.accounting import Ledger
from cryptobot.risk import Approved, Rejected, RiskPolicy


def _policy(tmp_path: Path, clock) -> RiskPolicy:
    return RiskPolicy(state_path=tmp_path / "risk.json", now_utc=clock)


def _delta(policy: RiskPolicy, rid: str, exec_id: str, side: str,
           qty: float, ts) -> None:
    policy.note_fill_delta(rid, exec_id, "BTCUSDT", side, qty, 100.0, 0.5,
                           ts.isoformat())


def test_race_release_then_late_delta_reblocks(tmp_path):
    cell, clock = make_clock()
    policy = _policy(tmp_path, clock)
    policy.reconcile_day(1000.0)
    first = policy.evaluate(audit_intent(cell[0]), audit_account())
    assert isinstance(first, Approved)
    assert policy.release(first.reservation_id) is True
    mid = policy.evaluate(audit_intent(cell[0]), audit_account())
    assert isinstance(mid, Approved)
    assert policy.release(mid.reservation_id) is True
    _delta(policy, first.reservation_id, "late-1", "BUY", 1.0, cell[0])
    out = policy.evaluate(audit_intent(cell[0]), audit_account())
    assert isinstance(out, Rejected) and out.reason == "exposure:booked"


def test_race_flat_then_new_delta_reblocks(tmp_path):
    cell, clock = make_clock()
    policy = _policy(tmp_path, clock)
    policy.reconcile_day(1000.0)
    first = policy.evaluate(audit_intent(cell[0]), audit_account())
    _delta(policy, first.reservation_id, "d1", "BUY", 1.0, cell[0])
    policy.note_fill(first.reservation_id)
    _delta(policy, first.reservation_id, "d2", "SELL", 1.0, cell[0])
    policy.note_flat()
    assert policy.release(first.reservation_id) is False  # unresolved-free, nothing live
    mid = policy.evaluate(audit_intent(cell[0]), audit_account())
    assert isinstance(mid, Approved)
    assert policy.release(mid.reservation_id) is True
    _delta(policy, first.reservation_id, "d3-late", "BUY", 0.5, cell[0])
    out = policy.evaluate(audit_intent(cell[0]), audit_account())
    assert isinstance(out, Rejected) and out.reason == "exposure:booked"


def test_race_stale_release_keeps_newer_exposure(tmp_path):
    cell, clock = make_clock()
    policy = _policy(tmp_path, clock)
    policy.reconcile_day(1000.0)
    first = policy.evaluate(audit_intent(cell[0]), audit_account())
    _delta(policy, first.reservation_id, "d1", "BUY", 1.0, cell[0])
    assert policy.release(first.reservation_id) is False  # newer exposure: retained
    assert policy.unresolved_ids() == (first.reservation_id,)
    out = policy.evaluate(audit_intent(cell[0]), audit_account())
    assert isinstance(out, Rejected) and out.reason == "exposure:unresolved"


def test_restart_keeps_state_and_ledger_in_agreement(tmp_path):
    cell, clock = make_clock()
    policy = _policy(tmp_path, clock)
    policy.reconcile_day(1000.0)
    ledger = Ledger(1000.0)
    first = policy.evaluate(audit_intent(cell[0]), audit_account())
    _delta(policy, first.reservation_id, "d1", "BUY", 0.6, cell[0])
    _delta(policy, first.reservation_id, "d2", "BUY", 0.4, cell[0])
    ledger.note_fill("d1", "BTCUSDT", "BUY", 0.6, 100.0, 0.5, cell[0].isoformat())
    ledger.note_fill("d2", "BTCUSDT", "BUY", 0.4, 101.0, 0.5, cell[0].isoformat())
    ledger.record_funding(-1.0, cell[0], event_id="f1")
    ledger_path = tmp_path / "ledger.json"
    ledger.save(ledger_path)
    # Forced restart: fresh objects over persisted files.
    policy2 = _policy(tmp_path, clock)
    ledger2 = Ledger.load(ledger_path)
    assert policy2.booked_net(first.reservation_id) == pytest.approx(1.0)
    assert ledger2.position_qty() == pytest.approx(1.0)
    assert ledger2.to_dict() == ledger.to_dict()
    out = policy2.evaluate(audit_intent(cell[0]), audit_account())
    assert isinstance(out, Rejected) and out.reason == "exposure:one-position"


def test_midnight_rollover_keeps_exposure_but_drops_halt(tmp_path):
    cell, clock = make_clock()
    policy = _policy(tmp_path, clock)
    policy.reconcile_day(1000.0)
    first = policy.evaluate(audit_intent(cell[0]), audit_account())
    _delta(policy, first.reservation_id, "d1", "BUY", 1.0, cell[0])
    policy.note_fill(first.reservation_id)
    cell[0] += timedelta(hours=7)  # cross the IST midnight boundary
    status = policy.monitor_tick()
    assert "health:day-open-needs-reconciliation" in status.reasons
    policy.reconcile_day(1000.0)
    out = policy.evaluate(audit_intent(cell[0]), audit_account())
    assert isinstance(out, Rejected)  # booked exposure survives the rollover
    assert policy.booked_net(first.reservation_id) == 1.0


def test_forced_exit_signal_lifecycle(tmp_path):
    cell, clock = make_clock()
    policy = _policy(tmp_path, clock)
    policy.reconcile_day(1000.0)
    assert policy.monitor_tick(cell[0], audit_account()).ok is True
    halting = audit_account()
    import dataclasses
    # W3-24H: operating-level trip (-0.6% net of costs); stops key on
    # net_liquidation and the operating latch clears on day roll.
    halting = dataclasses.replace(halting, marked_equity=994.0,
                                  net_liquidation=994.0)
    status = policy.monitor_tick(cell[0], halting)
    assert status.ok is False and status.reasons == ("halt:operating-stop",)
    out = policy.evaluate(audit_intent(cell[0]), audit_account())
    assert isinstance(out, Rejected) and out.reason == "halt:operating-stop"
    cell[0] += timedelta(hours=7)
    policy.monitor_tick()
    policy.reconcile_day(1000.0)
    assert isinstance(policy.evaluate(audit_intent(cell[0]), audit_account()), Approved)


def test_storage_failure_fails_loud(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    policy = RiskPolicy(state_path=blocker / "risk.json",
                        now_utc=lambda: T0)
    with pytest.raises(OSError):
        policy.reconcile_day(1000.0)
    ledger = Ledger(1000.0)
    with pytest.raises(OSError):
        ledger.save(blocker / "ledger.json")
