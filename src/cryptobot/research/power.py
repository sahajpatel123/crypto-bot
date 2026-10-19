"""F4.4 power analysis: trades/days needed for CI95 LB > 0 at 80% power.

Normal approximation on per-trade expectancy: need
n = ((z_{1-alpha} + z_{power}) * sd / mean)^2 trades one-sided.
"""
import math

Z = {0.90: 1.2816, 0.95: 1.6449, 0.80: 0.8416}


def trades_needed(mean_bps: float, sd_bps: float, power: float = 0.80,
                  level: float = 0.95) -> float:
    if mean_bps <= 0 or sd_bps <= 0:
        return float("inf")
    z = Z.get(level, 1.6449) + Z.get(power, 0.8416)
    return (z * sd_bps / mean_bps) ** 2


def confirm_eta(mean_bps: float, sd_bps: float, trades_per_day: float,
                max_days: int = 120) -> dict:
    n = trades_needed(mean_bps, sd_bps)
    if math.isinf(n) or trades_per_day <= 0:
        return {"trades_needed": None, "days": None,
                "verdict": "IMPRACTICAL",
                "reason": "non-positive dev mean or zero trade rate"}
    days = n / trades_per_day
    return {"trades_needed": round(n, 1), "days": round(days, 1),
            "verdict": "FEASIBLE" if days <= max_days else "IMPRACTICAL",
            "reason": f"{days:.0f} days at {trades_per_day}/day "
                      f"(cap {max_days})"}
