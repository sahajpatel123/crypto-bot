"""E1.4: point-in-time universe, listing age, no-lookahead proof."""
from __future__ import annotations

import pandas as pd
import pytest

pytest.importorskip("pandas")


def _panel(symbols_days_vol):
    """{symbol: DataFrame(open_time, close, quote_volume)} synthetic."""
    frames = {}
    for sym, start, days, vol in symbols_days_vol:
        idx = pd.date_range("2023-01-01", periods=300, freq="D", tz="UTC")
        qv = [vol] * 300
        frames[sym] = pd.DataFrame({
            "open_time": idx, "close": 100.0, "quote_volume": qv})
        frames[sym] = frames[sym].iloc[start:start + days].reset_index(drop=True)
    return frames


def test_eligible_uses_trailing_data_only():
    from cryptobot.research.universe import eligible_universe

    frames = _panel([("OLD", 0, 300, 1e6), ("NEW", 200, 100, 1e9)])
    asof = pd.Timestamp("2023-06-01", tz="UTC")
    # NEW lists later with huge volume; asof is before its listing.
    out = eligible_universe(asof, frames, top_n=5, min_listing_age_days=90)
    assert "OLD" in out and "NEW" not in out


def test_no_lookahead_future_volume_ignored():
    from cryptobot.research.universe import eligible_universe

    frames = _panel([("A", 0, 300, 1e6), ("B", 0, 300, 1e6)])
    # B explodes AFTER asof; A is steady. Trailing-30d at asof ties.
    asof = pd.Timestamp("2023-03-01", tz="UTC")
    later = frames["B"]["open_time"] > asof
    frames["B"].loc[later, "quote_volume"] = 1e12
    out = eligible_universe(asof, frames, top_n=1, min_listing_age_days=30)
    # Tie broken deterministically (by symbol name), NOT by future volume.
    assert out == ["A"]
    out2 = eligible_universe(pd.Timestamp("2023-05-01", tz="UTC"), frames,
                             top_n=1, min_listing_age_days=30)
    assert out2 == ["B"]  # once the volume is trailing, B wins


def test_listing_age_and_floor_enforced():
    from cryptobot.research.universe import eligible_universe

    frames = _panel([("OLD", 0, 300, 1e6), ("YOUNG", 250, 50, 1e9)])
    asof = pd.Timestamp("2023-10-01", tz="UTC")
    out = eligible_universe(asof, frames, top_n=5, min_listing_age_days=90,
                            min_quote_volume_30d=1e7)
    assert "YOUNG" not in out  # listed ~40d before asof
    out = eligible_universe(asof, frames, top_n=5, min_listing_age_days=90,
                            min_quote_volume_30d=1e12)
    assert out == []  # floor above everyone


def test_universe_history_is_deterministic_and_causal():
    from cryptobot.research.universe import universe_history

    frames = _panel([("A", 0, 300, 1e6), ("B", 100, 200, 2e6)])
    dates = [pd.Timestamp("2023-03-01", tz="UTC"),
             pd.Timestamp("2023-06-01", tz="UTC")]
    h1 = universe_history(dates, frames, top_n=5, min_listing_age_days=30)
    h2 = universe_history(dates, frames, top_n=5, min_listing_age_days=30)
    assert h1 == h2
    assert h1[dates[0]] == ["A"]  # B not yet listed
    assert set(h1[dates[1]]) == {"A", "B"}


def test_liquidity_table_sums_quote_volume():
    from cryptobot.research.universe import liquidity_table

    frames = _panel([("A", 0, 10, 1e6), ("B", 0, 10, 2e6)])
    tab = liquidity_table(frames)
    assert tab["B"] == pytest.approx(2e7)
    assert tab["A"] == pytest.approx(1e7)
