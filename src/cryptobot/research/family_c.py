"""C1 / B4b targets. Turnover is limited by the rules, not by a budget.

Weights are fractions of equity. While a hedge is inside the drift
band the weights move with price so the quantities stay put. A day
inside the band does not trade back to 50%.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from cryptobot.research.family_b import MarketData, _cap_weights, _idx_before

RT = 0.0053
PER_LEG = 0.5


def hurdle_apr(k: float, *, rt: float = RT, amortize_days: float = 7.0) -> float:
    return float(k) * rt * 365.0 / amortize_days


def trailing_median(funding: pd.DataFrame, day: pd.Timestamp,
                    *, lookback_days: int = 7) -> float | None:
    window = funding[(funding["calc_time"] >= day - pd.Timedelta(days=lookback_days))
                     & (funding["calc_time"] < day)]
    if window.empty:
        return None
    return float(window["last_funding_rate"].median())


def _px(frame: pd.DataFrame | None, day: pd.Timestamp) -> float | None:
    if frame is None or frame.empty:
        return None
    pos = _idx_before(frame, "open_time", day)
    if pos is None:
        return None
    return float(frame["close"].iloc[pos])


def capital_feasibility(equity: float, price: float, *,
                        per_leg: float = PER_LEG, qty_step: float = 0.001,
                        min_notional: float = 6.0) -> dict:
    notional = per_leg * float(equity)
    raw_qty = notional / float(price) if price else 0.0
    qty = np.floor(raw_qty / qty_step) * qty_step
    return {
        "equity": float(equity),
        "price": float(price),
        "target_notional": notional,
        "qty": float(qty),
        "min_notional": min_notional,
        "feasible": bool(qty >= qty_step and qty * price >= min_notional),
    }


def signals_c1(data: MarketData, params: dict, dates: list[pd.Timestamp],
               symbols: list[str], init_state: dict | None = None):
    k = float(params["k"])
    band = float(params["drift_band"])
    hurdle = hurdle_apr(k)
    exit_line = 0.5 * hurdle
    st: dict[str, dict] = dict((init_state or {}).get("positions", {}))
    targets: dict[pd.Timestamp, dict[str, float]] = {}
    for day in sorted(dates):
        weights: dict[str, float] = {}
        for sym in symbols:
            cur = dict(st.get(sym) or {"side": 0, "enter": None, "below": 0,
                                       "spot_px": None, "perp_px": None})
            funding = data.funding.get(sym)
            med = trailing_median(funding, day) if funding is not None else None
            apr = None if med is None else med * 3.0 * 365.0
            spot_px = _px(data.spot.get(sym), day)
            perp_px = _px(data.daily.get(sym), day)
            if cur["side"] and cur.get("enter") is not None:
                held = (day - cur["enter"]).days
                if held >= 7 and (med is None or med < 0 or (
                        apr is not None and apr < exit_line
                        and int(cur.get("below") or 0) >= 2)):
                    # The third weak day is this one: below was already 2.
                    cur = {"side": 0, "enter": None, "below": 0,
                           "spot_px": None, "perp_px": None}
                else:
                    if apr is not None and apr < exit_line:
                        cur["below"] = int(cur.get("below") or 0) + 1
                    else:
                        cur["below"] = 0
                    spot_w = PER_LEG
                    perp_w = -PER_LEG
                    if cur.get("spot_px") and spot_px:
                        spot_w = PER_LEG * spot_px / float(cur["spot_px"])
                    if cur.get("perp_px") and perp_px:
                        perp_w = -PER_LEG * perp_px / float(cur["perp_px"])
                    drift = abs(spot_w - abs(perp_w))
                    if drift > band and spot_px and perp_px:
                        spot_w, perp_w = PER_LEG, -PER_LEG
                        cur["spot_px"] = spot_px
                        cur["perp_px"] = perp_px
                    weights[f"SPOT:{sym}"] = spot_w
                    weights[sym] = perp_w
            elif apr is not None and apr > hurdle and med is not None and med > 0 \
                    and spot_px and perp_px:
                cur = {"side": 1, "enter": day, "below": 0,
                       "spot_px": spot_px, "perp_px": perp_px}
                weights[f"SPOT:{sym}"] = PER_LEG
                weights[sym] = -PER_LEG
            st[sym] = cur
        # 0.5 is the entry size. Clipping back to 0.5 every day would
        # trade on every price move. The gross cap of 2 still applies.
        targets[day] = _cap_weights(weights, cap=2.0)
    return targets, {"positions": st}


__all__ = [
    "RT", "capital_feasibility", "hurdle_apr", "signals_c1", "trailing_median",
]
