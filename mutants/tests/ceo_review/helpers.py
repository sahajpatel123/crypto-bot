"""CEO-finding black-box regressions (Worker 1, Q-003). Shared builders.

Named ``helpers`` (not ``conftest``) so the module cannot collide with
``tests/acceptance/conftest.py`` under pytest rootdir imports.

Every test drives PUBLIC interfaces only (Ledger, RiskPolicy, SliceRisk,
plan_size, OrderManager/FakeVenue, Intent) and asserts the correct BUSINESS
result from directive Sec 1 — never a copy of current buggy output. Pre-fix
runs are expected to fail exactly on the documented symptom; fix-after runs
(after manager-integrated V-004/E-005) must pass unchanged.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from cryptobot.coordination import DataQuality, ForecastCost, Intent, Side
from cryptobot.risk import AccountSnapshot

T0 = datetime(2026, 10, 11, 12, 0, 0, tzinfo=timezone.utc)


def make_clock(start: datetime = T0) -> tuple[list, Callable[[], datetime]]:
    cell = [start]
    return cell, lambda: cell[0]


def audit_cost() -> ForecastCost:
    return ForecastCost(1, 1, 1, 0)


def audit_account(equity: float = 1000.0) -> AccountSnapshot:
    return AccountSnapshot(equity, equity, equity, 0, False)


def audit_intent(
    now: datetime,
    low: float = 100.0,
    high: float = 100.0,
    stop: float = 99.0,
    forecast: ForecastCost | None = None,
    side: Side = Side.LONG,
) -> Intent:
    return Intent(
        "AUDIT", "1", "BTCUSDT", side, now,
        low, high, now + timedelta(seconds=5), stop,
        "stop-or-time", 30, forecast if forecast is not None else audit_cost(),
        "audit", DataQuality.CLEAN,
    )
