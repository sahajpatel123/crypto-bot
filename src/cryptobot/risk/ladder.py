"""Capital ladder, automatic demotion and canary sizing (T6.2/T6.3).

Promotion is manual only — nothing here can raise capital. Demotion is
automatic: stressed slippage, a rolling expectancy CI whose UPPER bound
is negative, an unknown outcome aged past its budget, or the operating
daily stop each force the bot back to minimum size / halted.
"""
from __future__ import annotations

import math


def demotion_reasons(*, slippage_ratio: float | None = None,
                     expectancy_ci_upper_bps: float | None = None,
                     expectancy_n: int = 0, expectancy_min_n: int = 30,
                     unknown_age_s: float | None = None,
                     unknown_budget_s: float = 60.0,
                     daily_stop_hit: bool = False) -> tuple[str, ...]:
    """All currently-triggered demotion reasons (empty = none)."""
    out: list[str] = []
    if slippage_ratio is not None and slippage_ratio > 1.5:
        out.append("slippage>1.5x-assumed")
    if expectancy_ci_upper_bps is not None \
            and expectancy_n >= expectancy_min_n \
            and expectancy_ci_upper_bps < 0:
        out.append("expectancy-ci-upper<0")
    if unknown_age_s is not None and unknown_age_s > unknown_budget_s:
        out.append("unknown-outcome-aged")
    if daily_stop_hit:
        out.append("operating-daily-stop")
    return tuple(out)


def canary_size(*, trade_index: int, canary_trades: int,
                min_qty: float, planned_qty: float) -> float:
    """First ``canary_trades`` after arming trade at minimum size."""
    if trade_index < max(0, int(canary_trades)):
        return float(min_qty)
    return float(planned_qty)


def ladder_level(*, armed_capital_usdt: float, demoted: bool,
                 canary_done: bool) -> str:
    """Current ladder rung: halted < canary < armed (promotion manual)."""
    if demoted:
        return "halted"
    if not canary_done:
        return "canary"
    return "armed" if armed_capital_usdt > 0 else "halted"


def _check_finite(name: str, value: float) -> None:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
