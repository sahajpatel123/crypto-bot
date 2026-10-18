"""Cost model v2 + break-even tables (T5.1).

At ~26bps taker round-trip, short scalps must move far just to break
even. This module makes that arithmetic explicit per exit geometry:
break-even move (bps) and required win rate for taker vs maker, at
realistic (1x), stressed (1.5x) and adverse (2x) costs.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    maker_bps: float = 2.0    # per side, venue commissionRate when known
    taker_bps: float = 5.0
    spread_bps: float = 2.0   # measured half-spread x2 proxy (per round trip)
    slippage_bps: float = 6.0  # measured/pessimistic per round trip
    bnb_discount: bool = False

    def _fee(self, bps: float) -> float:
        return bps * (0.75 if self.bnb_discount else 1.0)

    def round_trip_bps(self, *, maker_entry: bool,
                       stress: float = 1.0) -> float:
        entry = self._fee(self.maker_bps if maker_entry else self.taker_bps)
        exit_fee = self._fee(self.taker_bps)  # exits are taker (stop mkt)
        return (entry + exit_fee + self.spread_bps
                + self.slippage_bps) * float(stress)


def breakeven_move_bps(*, maker_entry: bool, model: CostModel,
                       stress: float = 1.0) -> float:
    """Price move (bps) a trade must capture to net zero."""
    return model.round_trip_bps(maker_entry=maker_entry, stress=stress)


def required_win_rate(*, stop_bps: float, target_bps: float,
                      cost_bps: float) -> float:
    """Win rate where expectancy = 0: p*T - (1-p)*S - C = 0.

    Independent derivation (tools/breakeven_audit.py repeats it):
        EV = p*T - (1-p)*S - c
        0  = p*(T+S) - S - c
        p* = (S + c) / (T + S)

    A result > 1 means no win rate can break even: the cost exceeds the
    target. Callers must surface that as INFEASIBLE, never round it to a
    plausible-looking percentage.
    """
    denom = float(target_bps) + float(stop_bps)
    if denom <= 0:
        raise ValueError("stop+target must be positive")
    if float(target_bps) <= 0 or float(stop_bps) <= 0:
        raise ValueError("stop and target must be positive")
    if float(cost_bps) < 0:
        raise ValueError("cost must be non-negative")
    return (float(stop_bps) + float(cost_bps)) / denom


def breakeven_row(*, stop_bps: float, target_bps: float,
                  cost_bps: float) -> dict:
    """One table row with an explicit feasibility verdict."""
    p = required_win_rate(stop_bps=stop_bps, target_bps=target_bps,
                          cost_bps=cost_bps)
    feasible = p < 1.0
    return {
        "required_win_rate": round(p, 4),
        "required_win_rate_pct": round(p * 100.0, 2),
        "feasible": feasible,
        "verdict": "FEASIBLE" if feasible else "INFEASIBLE",
    }


def breakeven_table(model: CostModel | None = None) -> list[dict]:
    """Rows for common geometries at 1x/1.5x/2x, taker vs maker entry."""
    model = model or CostModel()
    rows: list[dict] = []
    for stop, target in ((25.0, 25.0), (25.0, 50.0), (50.0, 100.0),
                         (100.0, 200.0), (200.0, 400.0)):
        for maker in (False, True):
            for stress in (1.0, 1.5, 2.0):
                cost = breakeven_move_bps(maker_entry=maker, model=model,
                                          stress=stress)
                row = {
                    "stop_bps": stop, "target_bps": target,
                    "entry": "maker" if maker else "taker",
                    "stress": stress, "round_trip_bps": round(cost, 2)}
                row.update(breakeven_row(stop_bps=stop, target_bps=target,
                                         cost_bps=cost))
                rows.append(row)
    return rows
