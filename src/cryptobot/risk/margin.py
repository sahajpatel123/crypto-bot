"""Tiered maintenance margin + isolated liquidation (T1.8).

Binance USD-M leverage brackets: each tier caps notional and carries a
maintenance-margin ratio plus a cumulative amount (cum), so
``maintenance_margin = notional * ratio - cum`` for the active tier.
Isolated liquidation solves ``equity == maintenance margin`` for the
mark price with the position's isolated wallet as the only buffer.
"""
from __future__ import annotations

import math


def _finite(value: float, name: str) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return float(value)


def maintenance_margin(notional_usdt: float,
                       brackets: list[dict]) -> float:
    """Tiered maintenance margin for ``notional_usdt`` (USDT)."""
    notional = _finite(notional_usdt, "notional_usdt")
    if notional < 0:
        raise ValueError("notional_usdt must be >= 0")
    if not brackets:
        raise ValueError("leverage brackets required")
    for tier in sorted(brackets, key=lambda b: float(b["notionalCap"])):
        if notional <= float(tier["notionalCap"]):
            return max(0.0, notional * float(tier["maintMarginRatio"])
                       - float(tier.get("cum", 0.0)))
    top = max(brackets, key=lambda b: float(b["notionalCap"]))
    return max(0.0, notional * float(top["maintMarginRatio"])
               - float(top.get("cum", 0.0)))


def liquidation_price_isolated(*, entry: float, qty: float,
                               isolated_margin: float,
                               maint_margin: float) -> float:
    """Isolated liquidation mark for a position opened at ``entry``.

    Long: entry - (margin - maint)/qty. Short mirrors. The venue also
    nets funding/fees intraday; this is the admission-time estimate the
    gate uses (conservative direction comes from the 3x rule below).
    """
    entry = _finite(entry, "entry")
    qty = _finite(qty, "qty")
    if qty == 0:
        raise ValueError("qty must be non-zero")
    buffer = _finite(isolated_margin, "isolated_margin") \
        - _finite(maint_margin, "maint_margin")
    return entry - buffer / qty


def liquidation_ok(*, entry: float, stop: float, liq: float,
                   stressed_slippage_bps: float, side: str) -> bool:
    """Admission gate: liquidation >=3x stop distance and beyond the
    stop plus stressed slippage (so the stop fires first, with room)."""
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    liq = _finite(liq, "liq")
    slip = _finite(stressed_slippage_bps, "stressed_slippage_bps")
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return False
    liq_dist = abs(entry - liq)
    if liq_dist < 3.0 * stop_dist:
        return False
    slip_abs = entry * slip / 10000.0
    if side == "LONG":
        return liq < stop - slip_abs
    if side == "SHORT":
        return liq > stop + slip_abs
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def bracket_admission_check(*, entry: float, stop: float, qty: float,
                            side: str, leverage: float,
                            brackets: list[dict] | None,
                            observed_ms: int | None,
                            now_ms: int,
                            max_age_ms: int = 300_000,
                            stressed_slippage_bps: float = 50.0) -> dict:
    """Live admission gate for tiered maintenance margin + liquidation.

    Fail-closed semantics (F0.4a): missing, empty, malformed or stale
    bracket data rejects with ``margin:brackets-*``. A stale bracket can
    understate maintenance margin after a venue tier change, so it is
    never silently used.
    """
    if not brackets:
        return {"ok": False, "reason": "margin:brackets-missing"}
    if observed_ms is None:
        return {"ok": False, "reason": "margin:brackets-unobserved"}
    try:
        age = int(now_ms) - int(observed_ms)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "margin:brackets-invalid-timestamp"}
    if age < 0:
        return {"ok": False, "reason": "margin:brackets-future-timestamp"}
    if age > int(max_age_ms):
        return {"ok": False, "reason": "margin:brackets-stale",
                "age_ms": age, "max_age_ms": int(max_age_ms)}
    try:
        entry_f = _finite(entry, "entry")
        stop_f = _finite(stop, "stop")
        qty_f = _finite(qty, "qty")
        lev_f = _finite(leverage, "leverage")
    except ValueError as exc:
        return {"ok": False, "reason": f"margin:invalid-input:{exc}"}
    if qty_f <= 0 or lev_f <= 0 or entry_f <= 0:
        return {"ok": False, "reason": "margin:invalid-input"}
    if side not in ("LONG", "SHORT"):
        return {"ok": False, "reason": "margin:invalid-side"}
    notional = qty_f * entry_f
    try:
        maintenance = maintenance_margin(notional, brackets)
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "reason": "margin:brackets-malformed"}
    margin = notional / lev_f
    liq = liquidation_price_isolated(
        entry=entry_f, qty=qty_f if side == "LONG" else -qty_f,
        isolated_margin=margin, maint_margin=maintenance)
    ok = liquidation_ok(entry=entry_f, stop=stop_f, liq=liq,
                        stressed_slippage_bps=stressed_slippage_bps,
                        side=side)
    return {"ok": ok,
            "reason": "margin:ok" if ok else "margin:liquidation-too-close",
            "notional_usdt": notional,
            "maintenance_margin_usdt": maintenance,
            "isolated_margin_usdt": margin,
            "liquidation_price": liq,
            "leverage": lev_f}


def minimum_viable_equity(*, min_notional_usdt: float,
                          stop_dist_frac: float,
                          loss_budget_pct: float = 0.00125,
                          stressed_cost_frac: float = 0.0) -> float:
    """Smallest equity whose loss budget funds a minimum legal order.

    At the minimum notional, the stop loss is
    ``min_notional * (stop_dist_frac + stressed_cost_frac)``; equity is
    viable only when ``loss_budget_pct * equity`` covers it. Below this
    equity every legal order risks more than the budget — reject clean.
    """
    min_notional = _finite(min_notional_usdt, "min_notional_usdt")
    dist = _finite(stop_dist_frac, "stop_dist_frac")
    budget = _finite(loss_budget_pct, "loss_budget_pct")
    costs = _finite(stressed_cost_frac, "stressed_cost_frac")
    if min_notional <= 0 or dist <= 0 or budget <= 0 or costs < 0:
        raise ValueError("minimum_viable_equity needs positive "
                         "min_notional/stop_dist/loss_budget")
    return min_notional * (dist + costs) / budget
