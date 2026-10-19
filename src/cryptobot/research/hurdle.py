"""Owner daily-profit hurdle versus measured annualized Sharpe.

This does not change a frozen gate. A 2%/day target is reported as
unmet when the measured Sharpe and drawdown cannot produce it.
"""
from __future__ import annotations

import math

PERIODS = 365.0


def compounded_growth(daily: float, days: int = 365) -> float:
    """Multiple of starting capital after `days` at a constant daily rate."""
    return (1.0 + daily) ** days


def sharpe_for_daily(daily_mean: float, daily_vol: float, *,
                     periods: float = PERIODS) -> float:
    if daily_vol <= 0:
        raise ValueError("daily vol must be positive")
    return daily_mean / daily_vol * math.sqrt(periods)


def daily_mean_from_sharpe(sharpe_ann: float, daily_vol: float, *,
                           periods: float = PERIODS) -> float:
    return sharpe_ann * daily_vol / math.sqrt(periods)


def vol_required(daily_mean: float, sharpe_ann: float, *,
                 periods: float = PERIODS) -> float:
    """Daily vol a strategy would need for this Sharpe to equal daily_mean."""
    if sharpe_ann <= 0:
        raise ValueError("sharpe must be positive to imply a positive mean")
    return daily_mean * math.sqrt(periods) / sharpe_ann


def hurdle_verdict(*, best_sharpe: float, max_drawdown: float,
                   daily_low: float = 0.02, daily_high: float = 0.03) -> dict:
    """Compare the best measured result with a 2–3%/day owner wish.

    A strategy whose worst peak-to-trough loss is `max_drawdown` cannot
    also have a typical daily move as large as the vol required to turn
    `best_sharpe` into a 2%/day mean. That contradiction is a fail.
    """
    needed = vol_required(daily_low, best_sharpe)
    # A 2-sigma day larger than the whole max drawdown means the
    # measured path is much quieter than a 2%/day book.
    contradictory = needed > max_drawdown
    return {
        "daily_low": daily_low,
        "daily_high": daily_high,
        "growth_1y_at_2pct": compounded_growth(daily_low),
        "growth_1y_at_3pct": compounded_growth(daily_high),
        "best_sharpe_ann": best_sharpe,
        "max_drawdown": max_drawdown,
        "daily_vol_required_for_2pct": needed,
        "contradiction": contradictory,
        "verdict": "HURDLE_UNMET" if contradictory or best_sharpe < 1 else "REVIEW",
        "gate": "NO-GO",
    }
