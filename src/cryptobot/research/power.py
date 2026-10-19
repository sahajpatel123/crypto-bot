"""F4.4: power analysis for confirmation data planning.

Estimates the number of trades needed for 80% power to reject
``mean <= 0`` at a 95% one-sided confidence level, using the dev mean
and standard deviation:

    n = ceil(((z_0.95 + z_0.80) * sigma / mean)^2)

Then converts to days with the observed trade rate. The autopilot
records the ETA; >120 days is IMPRACTICAL and is reported with the
numbers rather than hidden.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

Z_ALPHA = 1.6448536269514722  # one-sided 95%
Z_POWER = 0.8416212335729143  # 80%


@dataclass(frozen=True)
class PowerEstimate:
    mean_bps: float
    stdev_bps: float
    trades_per_day: float
    required_trades: int | None
    days_required: float | None
    status: str
    reason: str

    def as_dict(self) -> dict:
        return {"mean_bps": self.mean_bps, "stdev_bps": self.stdev_bps,
                "trades_per_day": self.trades_per_day,
                "required_trades": self.required_trades,
                "days_required": self.days_required,
                "status": self.status, "reason": self.reason}


def estimate_power(trades_bps: list[float], *,
                   trades_per_day: float,
                   impractical_days: float = 120.0) -> PowerEstimate:
    values = [float(v) for v in trades_bps]
    if len(values) < 2:
        return PowerEstimate(0.0, 0.0, float(trades_per_day), None, None,
                             "IMPOSSIBLE", "fewer than 2 dev trades")
    mean = statistics.fmean(values)
    stdev = statistics.pstdev(values)
    if not math.isfinite(mean) or not math.isfinite(stdev):
        return PowerEstimate(mean, stdev, float(trades_per_day), None, None,
                             "IMPOSSIBLE", "non-finite dev statistics")
    if mean <= 0:
        return PowerEstimate(mean, stdev, float(trades_per_day), None, None,
                             "IMPOSSIBLE",
                             "dev mean <= 0: more data cannot create power")
    if stdev <= 0:
        return PowerEstimate(mean, stdev, float(trades_per_day), 2, 0.0,
                             "FEASIBLE", "zero dev variance")
    if trades_per_day <= 0:
        return PowerEstimate(mean, stdev, float(trades_per_day), None, None,
                             "IMPOSSIBLE", "trade rate must be positive")
    n = math.ceil(((Z_ALPHA + Z_POWER) * stdev / mean) ** 2)
    n = max(2, n)
    days = n / float(trades_per_day)
    status = "IMPRACTICAL" if days > impractical_days else "FEASIBLE"
    return PowerEstimate(mean, stdev, float(trades_per_day), n, days,
                         status,
                         f"{days:.1f} days at {trades_per_day:.1f} trades/day"
                         if status == "FEASIBLE" else
                         f"needs {days:.1f} days > {impractical_days:.0f}-day budget")


__all__ = ["PowerEstimate", "estimate_power"]
