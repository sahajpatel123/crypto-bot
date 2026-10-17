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
    """Win rate where expectancy = 0: p*T - (1-p)*S - C = 0."""
    denom = float(target_bps) + float(stop_bps)
    if denom <= 0:
        raise ValueError("stop+target must be positive")
    return (float(stop_bps) + float(cost_bps)) / denom


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
                rows.append({
                    "stop_bps": stop, "target_bps": target,
                    "entry": "maker" if maker else "taker",
                    "stress": stress, "round_trip_bps": round(cost, 2),
                    "required_win_rate": round(required_win_rate(
                        stop_bps=stop, target_bps=target,
                        cost_bps=cost), 4)})
    return rows
