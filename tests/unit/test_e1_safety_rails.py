"""E1 Session-level safety decisions across configured run modes.

The policy and Session are real; account snapshots and order side effects are
controlled doubles. This proves shared halt/stop dispatch, not live venue
execution; the loopback emulator rehearsal and CLI gate tests cover those paths.
"""
from __future__ import annotations

import time
from dataclasses import replace

import pytest
from tests.unit.test_session_replay import _session

from cryptobot.risk.types import AccountSnapshot


@pytest.mark.parametrize("mode", ["replay", "paper", "emulator-demo", "prod"])
def test_daily_loss_halts_and_reduces_in_each_config_mode(
        tmp_path, mode):
    """A max-daily-loss breach halts admission and runs stop actions."""
    session, store = _session(tmp_path, warmup_bars=3)
    actual_mode = "paper" if mode == "emulator-demo" else mode
    session.config = replace(
        session.config, mode=actual_mode,
        engine_kind="live" if mode in ("emulator-demo", "prod")
        else session.config.engine_kind,
        engine_demo=(mode == "emulator-demo"),
        allow_live_submission=(mode == "prod"))
    store.create_run(session.run_id, actual_mode, "e1-safety",
                     str(session.workdir), None)
    session.policy.reconcile_day(100.0, 0.0)
    session.apply_armed_limits(capital_usdt=100.0,
                               max_daily_loss_usdt=1.0,
                               canary_trades=1, equity_usdt=100.0)
    account = AccountSnapshot(
        reconciled_equity=98.9, marked_equity=98.9,
        net_liquidation=98.9, net_realised_global=-1.1,
        open_position=True, flows_cumulative=0.0,
        available_margin_usdt=98.9, mark_age_ms=0.0)
    session._snapshot_account = lambda: account
    session._supervise_account = lambda _now: account
    session._refresh_filters_if_stale = lambda: None
    session._drain_unknown_outcomes = lambda: None
    session.engine.open_orders = lambda: [type(
        "Order", (), {"client_order_id": "entry-1", "role": "entry",
                      "state": "open"})()]
    cancelled = []
    session.engine.cancel = lambda cid, _reason: cancelled.append(cid)
    flattened = []
    session._flatten = lambda reason: flattened.append(reason)
    try:
        result = session._supervise(
            {"last_beat": time.monotonic()}, time.monotonic())
        assert result is None
        assert session.policy.emergency_active()
        assert any(reason.startswith("halt:emergency")
                   for reason in session._exit_only_reasons)
        assert cancelled == ["entry-1"]
        assert flattened == ["stop-action"]
    finally:
        store.close()


@pytest.mark.parametrize("mode", ["replay", "paper", "emulator-demo", "prod"])
def test_persisted_flatten_stop_is_honored_in_each_config_mode(tmp_path, mode):
    """The operator-stop channel persists and reaches the run supervisor."""
    session, store = _session(tmp_path, warmup_bars=3)
    actual_mode = "paper" if mode == "emulator-demo" else mode
    session.config = replace(
        session.config, mode=actual_mode,
        engine_kind="live" if mode in ("emulator-demo", "prod")
        else session.config.engine_kind,
        engine_demo=(mode == "emulator-demo"),
        allow_live_submission=(mode == "prod"))
    store.create_run(session.run_id, actual_mode, "e1-stop",
                     str(session.workdir), None)
    session.policy.reconcile_day(100.0, 0.0)
    account = AccountSnapshot(
        reconciled_equity=100.0, marked_equity=100.0,
        net_liquidation=100.0, net_realised_global=0.0,
        open_position=False, mark_age_ms=0.0)
    session._snapshot_account = lambda: account
    session._supervise_account = lambda _now: account
    session._run_stop_actions = lambda: None
    session._drain_unknown_outcomes = lambda: None
    session._refresh_filters_if_stale = lambda: None
    flattened = []
    session._flatten = lambda reason: flattened.append(reason)
    try:
        store.request_stop(session.run_id, "flatten")
        store.request_stop(session.run_id, "flatten")
        assert store.stop_requested(session.run_id) == "flatten"
        assert session.control_tick() == "operator-stop:flatten"
        assert flattened == ["operator-stop-flatten"]
    finally:
        store.close()
