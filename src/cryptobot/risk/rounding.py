"""One venue-rounding rule for risk, submission, fills and protection (V-008 §7).

Every stage floors quantities to the venue LOT_SIZE step with this exact
function, so a quantity admitted by risk submits, fills and protects at
the identical value. Leaf module: no package imports (adapters and
execution import it; it imports nothing).
"""
from __future__ import annotations

import math

__all__ = ["floor_to_step", "round_to_tick"]


def _step_eps(quot: float) -> float:
    """Representation-noise tolerance for a floored quotient (F1.1).

    Division/representation error scales with the quotient magnitude
    (~ulp), so a fixed epsilon either rounds UP at large ratios (the
    old multiplicative bug) or breaks idempotency for exact multiples
    (fixed additive misses by >1e-9 above quot~1e7). Two ulps cover
    correctly-rounded division error (<=0.5ulp) with margin; capped at
    1e-6 steps so genuine non-multiples (>1e-6 below the integer)
    always stay down (safe direction). Values within noise of an
    integer from below may cross UP by one step with overage <= ~ulp
    (value dust ~1e-10 relative, inside within_budget tolerance);
    anything larger always stays down.
    """
    if not math.isfinite(quot) or quot < 0:
        return 0.0
    return min(2.0 * math.ulp(quot), 1e-6)


def floor_to_step(qty: float, step: float) -> float:
    """Floor ``qty`` down to a multiple of ``step`` (venue LOT_SIZE).

    Never rounds up: the quotient gets only representation-noise
    tolerance (see _step_eps), so exact multiples survive division
    noise (0.3/0.1) while genuine non-multiples — even within 1e-6 of
    an integer — stay down. Round-12 kills representation dust, so
    results are idempotent up to qty/step < 1e9 (every venue ratio;
    beyond that the quotient ulp exceeds any safe epsilon and a
    re-floor may slip one step DOWN, never up). Returns 0.0 when
    ``qty`` sits below one step; callers own the dust policy
    (reject vs raise).
    """
    if isinstance(step, bool) or not isinstance(step, (int, float)) \
            or not math.isfinite(step) or step <= 0:
        raise ValueError(f"step must be a finite positive number, got {step!r}")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
            or not math.isfinite(qty):
        raise ValueError(f"qty must be a finite number, got {qty!r}")
    if qty <= 0:
        return 0.0
    units = math.floor(qty / step * (1 + 1e-9))
    out = round(units * step, 12)
    if out > qty:  # epsilon must never round risk UP by a whole step.
        out = round((units - 1) * step, 12)
    return min(out, qty)
    quot = qty / step
    return round(math.floor(quot + _step_eps(quot)) * step, 12)


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


def floor_to_tick(price: float, tick: float) -> float:
    """Round ``price`` DOWN to a venue tick (BUY caps never exceed the band)."""
    _check_tick_args(price, tick)
    units = math.floor(price / tick * (1 + 1e-9))
    out = round(units * tick, 12)
    if out > price:
        out = round((units - 1) * tick, 12)
    return min(out, price)
    quot = price / tick
    return round(math.floor(quot + _step_eps(quot)) * tick, 12)


def ceil_to_tick(price: float, tick: float) -> float:
    """Round ``price`` UP to a venue tick (SELL floors never dip the band)."""
    _check_tick_args(price, tick)
    units = math.ceil(price / tick * (1 - 1e-9))
    out = round(units * tick, 12)
    if out < price:
        out = round((units + 1) * tick, 12)
    return max(out, price)
    quot = price / tick
    return round(math.ceil(quot - _step_eps(quot)) * tick, 12)


def _check_tick_args(price: float, tick: float) -> None:
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) \
            or not math.isfinite(tick) or tick <= 0:
        raise ValueError(f"tick must be a finite positive number, got {tick!r}")
    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a finite positive number, got {price!r}")
