"""Money-path invariants: venue-truth loss cap, timer-driven stops, and a
kill switch that survives a rate limit.

Each test fails on the pre-repair tree, where the daily-loss cap policed the
local ledger, stop evaluation was skipped whenever the control tick ran with
account=None, and a RateLimitedError escaped the reduce branch and ended the
loop with exposure still open.
"""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace

from cryptobot.adapters.binance_live import RateLimitedError
from cryptobot.risk.policy import HealthStatus

from tests.unit.test_session_replay import _session


def _prod(tmp_path):
    session, store = _session(tmp_path)
    session.config = dataclasses.replace(session.config, mode="prod")
    return session, store


def _account(equity, *, incomplete=False):
    return SimpleNamespace(wallet_equity_usdt=equity, incomplete=incomplete)


def test_loss_cap_uses_venue_equity_in_prod(tmp_path):
    session, _ = _prod(tmp_path)
    session.engine.account_snapshot = lambda: _account(1234.5)
    assert session._venue_equity() == 1234.5
    assert session._snapshot_account().net_liquidation == 1234.5


def test_loss_cap_ignores_venue_in_paper(tmp_path):
    session, _ = _session(tmp_path)
    session.engine.account_snapshot = lambda: _account(1234.5)
    assert session._venue_equity() is None
    assert session._snapshot_account().net_liquidation != 1234.5


def test_loss_cap_refuses_incomplete_or_unreadable_equity(tmp_path):
    session, _ = _prod(tmp_path)
    session.engine.account_snapshot = lambda: _account(1234.5, incomplete=True)
    assert session._venue_equity() is None
    session.engine.account_snapshot = lambda: _account(float("nan"))
    assert session._venue_equity() is None

    def boom():
        raise RateLimitedError("429")
    session.engine.account_snapshot = boom
    assert session._venue_equity() is None


def test_supervise_evaluates_stops_with_an_account(tmp_path):
    session, _ = _session(tmp_path)
    seen: list[object] = []

    def fake_tick(account=None, now=None):
        seen.append(account)
        return HealthStatus(True, (), ())

    session.policy.monitor_tick = fake_tick
    session._supervise({"last_beat": 0.0}, 0.0)
    assert seen and seen[0] is not None, "control tick skipped stop evaluation"


def test_supervise_snapshot_is_rate_limited(tmp_path):
    session, _ = _session(tmp_path)
    calls: list[int] = []
    session._snapshot_account = lambda symbol=None: calls.append(1) or object()
    session._supervise_account(0.0)
    session._supervise_account(0.5)
    assert len(calls) == 1, "snapshot rebuilt inside the refresh window"
    session._supervise_account(6.0)
    assert len(calls) == 2


def test_kill_switch_survives_rate_limit_and_retries(tmp_path):
    session, store = _session(tmp_path)
    session.policy.pending_stop_actions = lambda snap: {"reduce_exposure"}
    session.policy.emergency_active = lambda: True

    attempts: list[int] = []

    def failing_flatten(reason):
        attempts.append(1)
        raise RateLimitedError("429 Too Many Requests")

    session._flatten = failing_flatten
    session._run_stop_actions()  # must not raise
    assert attempts == [1]

    # The next tick tries again rather than leaving exposure open for good.
    session._run_stop_actions()
    assert attempts == [1, 1]
