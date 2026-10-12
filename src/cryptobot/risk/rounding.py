"""One venue-rounding rule for risk, submission, fills and protection (V-008 §7).

Every stage floors quantities to the venue LOT_SIZE step with this exact
function, so a quantity admitted by risk submits, fills and protects at
the identical value. Leaf module: no package imports (adapters and
execution import it; it imports nothing).
"""
from __future__ import annotations

import math

__all__ = ["floor_to_step", "round_to_tick"]


def floor_to_step(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    The 1e-9 epsilon keeps exact multiples exact across float division
    (0.3/0.1), and the round-12 kills representation dust, so results
    are idempotent: floor(floor(x)) == floor(x). Returns 0.0 when ``qty``
    sits below one step; callers own the dust policy (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or not math.isfinite(step) or step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 0.0
    return round(math.floor(qty / step * (1 + 1e-9)) * step, 12)


def round_to_tick(price: float, tick: float) -> float:
    """Round ``price`` to the nearest venue PRICE_FILTER tick.

    Symmetric round-half-even via banker's round(); round-12 kills
    representation dust. Limit/conditional trigger prices use this on
    every path (sim submission and live submission identical).
    """
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")
    return round(round(price / tick) * tick, 12)
