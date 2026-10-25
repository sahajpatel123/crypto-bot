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

from tests.unit.test_session_replay import _session

from cryptobot.adapters.binance_live import RateLimitedError
from cryptobot.risk.policy import HealthStatus


def _prod(tmp_path):
    session, store = _session(tmp_path)
    session.config = dataclasses.replace(session.config, mode="prod")
    return session, store


def _account(equity, *, complete=True, margin=None, unrealized=None):
    """Engine snapshot double: wallet, marked margin equity, completeness.

    ``margin_balance_usdt`` is totalMarginBalance (wallet + unrealized), the
    figure the loss cap must police; ``wallet_equity_usdt`` is the wallet leg
    alone. ``complete`` mirrors the AccountSnapshot flag the adapter sets.
    """
    return SimpleNamespace(
        wallet_equity_usdt=equity,
        margin_balance_usdt=equity if margin is None else margin,
        unrealized_pnl_usdt=unrealized,
        complete=complete)


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
    session.engine.account_snapshot = lambda: _account(1234.5, complete=False)
    assert session._venue_equity() is None
    session.engine.account_snapshot = lambda: _account(float("nan"))
    assert session._venue_equity() is None

    def boom():
        raise RateLimitedError("429")
    session.engine.account_snapshot = boom
    assert session._venue_equity() is None


def test_incomplete_snapshot_falls_back_to_the_ledger(tmp_path):
    """An incomplete snapshot is unknown, never trusted equity.

    The adapter sets ``complete=False`` when a balance leg is missing or a
    position row failed to parse. Checking a non-existent ``incomplete``
    attribute accepted that snapshot as truth (the guard was dead code), so
    the cap policed a figure the venue had already called unreadable.
    """
    session, _ = _prod(tmp_path)
    session.engine.account_snapshot = lambda: _account(
        1000.0, margin=960.0, unrealized=-40.0, complete=False)
    assert session._venue_equity() is None
    fallback = session.ledger.net_liquidation(
        session._reference_mark(), session.config.taker_bps)
    assert session._snapshot_account().net_liquidation == fallback


def test_loss_cap_reads_venue_equity_marked_to_market(tmp_path):
    """Wallet 1000 with -40 unrealized is 960 of equity, not 1000.

    totalWalletBalance excludes unrealized PnL, so a position bleeding
    through the emergency threshold never moved the cap: the backstop only
    saw realized losses.
    """
    session, _ = _prod(tmp_path)
    session.engine.account_snapshot = lambda: _account(
        1000.0, margin=960.0, unrealized=-40.0)
    assert session._venue_equity() == 960.0
    assert session._snapshot_account().net_liquidation == 960.0


def test_loss_cap_falls_back_to_wallet_plus_unrealized(tmp_path):
    """Snapshots without a margin leg still yield wallet + unrealized."""
    session, _ = _prod(tmp_path)
    snap = _account(1000.0, unrealized=-40.0)
    snap.margin_balance_usdt = None
    session.engine.account_snapshot = lambda: snap
    assert session._venue_equity() == 960.0


def test_day_roll_uses_the_same_equity_as_the_cap(tmp_path):
    """Day-start baseline and running figure must share one accessor.

    Rolling on marked ledger equity while the cap compares a venue margin
    balance turns an open position's unrealized into phantom day PnL: +3%
    unrealized latches the operating stop on the next tick, and underwater
    it grants a larger loss budget than configured.
    """
    session, _ = _prod(tmp_path)
    session.engine.account_snapshot = lambda: _account(
        1000.0, margin=960.0, unrealized=-40.0)
    session._day = "1999-01-01"
    session._roll_day_if_needed()
    assert session.policy._state.day_start_equity == 960.0


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


def test_supervise_keeps_stops_on_an_unreadable_account(tmp_path):
    """A blocked REST read must not suspend loss monitoring.

    Returning None discarded the cached snapshot, and monitor_tick(account=
    None) skips halt/floor/mark-age evaluation entirely: the stop check
    failed open exactly when the venue was unreachable.
    """
    session, _ = _session(tmp_path)
    snap = session._snapshot_account()
    session._supervise_snap = snap
    session._supervise_snap_at = 0.0

    def boom(symbol=None):
        raise TimeoutError("read blocked")

    session._snapshot_account = boom
    assert session._supervise_account(6.0) is snap, "cached truth discarded"
    assert "account:unreadable" in session._exit_only_reasons

    seen: list[object] = []
    session.policy.monitor_tick = lambda account=None, now=None: (
        seen.append(account) or HealthStatus(True, (), ()))
    session._supervise({"last_beat": 0.0}, 6.0)
    assert seen and seen[0] is snap, "stop evaluation skipped while blocked"

    # A readable snapshot lifts the latch: the halt is level-evaluated.
    session._snapshot_account = lambda symbol=None: snap
    session._supervise_account(20.0)
    assert "account:unreadable" not in session._exit_only_reasons


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
