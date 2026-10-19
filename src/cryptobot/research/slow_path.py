"""E7: slow-strategy paper path. Never submits an order.

Family A one-position scalp limits are not modified here. This module
plans a multi-leg book, slices rebalances, and sizes from the bootstrap
LOWER bound of expected return. A human arm is still required before
any live order; this code has no venue client.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PortfolioLimits:
    gross_cap: float = 2.0
    net_cap: float = 0.25
    per_symbol_cap: float = 0.50
    daily_loss_frac: float = 0.02
    weekly_loss_frac: float = 0.05
    max_leverage: float = 3.0


@dataclass
class RiskDecision:
    ok: bool
    targets: dict[str, float]
    reasons: list[str] = field(default_factory=list)


def _gross(weights: dict[str, float]) -> float:
    return sum(abs(v) for v in weights.values())


def _net(weights: dict[str, float]) -> float:
    return sum(weights.values())


def apply_risk(targets: dict[str, float], *, equity: float,
               day_pnl: float, week_pnl: float,
               limits: PortfolioLimits | None = None) -> RiskDecision:
    """Scale or flatten a target book. Does not send orders."""
    limits = limits or PortfolioLimits()
    reasons: list[str] = []
    if equity <= 0:
        return RiskDecision(False, {}, ["equity<=0 kill"])
    if day_pnl <= -limits.daily_loss_frac * equity:
        return RiskDecision(False, {}, ["daily loss stop"])
    if week_pnl <= -limits.weekly_loss_frac * equity:
        return RiskDecision(False, {}, ["weekly loss stop"])
    out = {s: float(v) for s, v in targets.items() if v != 0.0}
    for sym, w in list(out.items()):
        if abs(w) > limits.per_symbol_cap:
            out[sym] = limits.per_symbol_cap if w > 0 else -limits.per_symbol_cap
            reasons.append(f"per-symbol cap {sym}")
    gross = _gross(out)
    if gross > limits.gross_cap and gross > 0:
        scale = limits.gross_cap / gross
        out = {s: v * scale for s, v in out.items()}
        reasons.append("gross cap")
    if abs(_net(out)) > limits.net_cap and _gross(out) > 0:
        # Shrink the heavier side until net is inside the cap.
        net = _net(out)
        excess = abs(net) - limits.net_cap
        side = 1 if net > 0 else -1
        same = {s: v for s, v in out.items() if v * side > 0}
        same_gross = sum(abs(v) for v in same.values()) or 1.0
        for s, v in same.items():
            out[s] = v - side * excess * (abs(v) / same_gross)
        reasons.append("net cap")
    if _gross(out) > limits.max_leverage:
        return RiskDecision(False, {}, ["leverage cap"])
    return RiskDecision(True, out, reasons)


def twap_slices(delta_notional: float, n_slices: int) -> list[float]:
    """Equal notional slices. n_slices < 1 is refused."""
    if n_slices < 1:
        raise ValueError("n_slices must be >= 1")
    if delta_notional == 0.0:
        return []
    piece = delta_notional / n_slices
    return [piece] * n_slices


def no_trade(current: dict[str, float], target: dict[str, float],
             band: float) -> dict[str, float]:
    """Keep the current weight when the change is inside the band."""
    keys = set(current) | set(target)
    out = {}
    for sym in keys:
        cur = current.get(sym, 0.0)
        tgt = target.get(sym, 0.0)
        out[sym] = cur if abs(tgt - cur) < band else tgt
    return {s: v for s, v in out.items() if v != 0.0}


def fractional_kelly(lower_mean: float, variance: float, *,
                     fraction: float = 0.25, hard_cap: float = 0.5) -> float:
    """Kelly fraction from the LOWER bound of expected return, then capped.

    A non-positive lower bound sizes to zero. The point estimate is not
    an input.
    """
    if variance <= 0 or lower_mean <= 0 or fraction <= 0:
        return 0.0
    full = lower_mean / variance
    return float(min(hard_cap, max(0.0, fraction * full)))


def paper_attribute(*, predicted_pnl: float, realized_pnl: float,
                    predicted_cost: float, realized_cost: float) -> dict:
    """Predicted-versus-realized attribution for one paper rebalance."""
    return {
        "predicted_pnl": predicted_pnl,
        "realized_pnl": realized_pnl,
        "pnl_error": realized_pnl - predicted_pnl,
        "predicted_cost": predicted_cost,
        "realized_cost": realized_cost,
        "cost_error": realized_cost - predicted_cost,
        "orders_sent": 0,
    }


__all__ = [
    "PortfolioLimits", "RiskDecision", "apply_risk", "twap_slices",
    "no_trade", "fractional_kelly", "paper_attribute",
]
