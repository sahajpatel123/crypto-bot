"""E1.4: point-in-time traded universe (trailing data only).

Eligibility at `asof` uses bars with open_time strictly before `asof`
(the bar opening at `asof` has no close yet). Listing age counts from
first appearance. Ranking is trailing quote volume, ties broken by
symbol name (deterministic, no future information).
"""
from __future__ import annotations

import pandas as pd

__all__ = ["liquidity_table", "eligible_universe", "universe_history"]


def liquidity_table(frames: dict[str, pd.DataFrame]) -> dict[str, float]:
    return {sym: float(df["quote_volume"].sum())
            for sym, df in frames.items()}


def eligible_universe(asof: pd.Timestamp, frames: dict[str, pd.DataFrame], *,
                      top_n: int = 30, min_listing_age_days: int = 90,
                      min_quote_volume_30d: float = 0.0,
                      trailing_days: int = 30) -> list[str]:
    asof = pd.Timestamp(asof)
    asof = asof.tz_localize("UTC") if asof.tzinfo is None else asof.tz_convert("UTC")
    start = asof - pd.Timedelta(days=trailing_days)
    scored: list[tuple[float, str]] = []
    for sym in sorted(frames):
        df = frames[sym]
        past = df[df["open_time"] < asof]
        if past.empty:
            continue
        age_days = (asof - past["open_time"].iloc[0]).total_seconds() / 86400.0
        if age_days < min_listing_age_days:
            continue
        window = past[past["open_time"] >= start]
        vol = float(window["quote_volume"].sum())
        if vol < min_quote_volume_30d:
            continue
        scored.append((vol, sym))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [sym for _, sym in scored[:top_n]]


def universe_history(dates: list[pd.Timestamp],
                     frames: dict[str, pd.DataFrame], **kwargs) -> dict:
    return {d: eligible_universe(d, frames, **kwargs) for d in dates}
