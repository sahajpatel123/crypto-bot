"""C1 rules: hurdle entry, hysteresis exit, drift-band rebalance."""
import pandas as pd

from cryptobot.research.family_b import MarketData
from cryptobot.research.family_c import capital_feasibility, hurdle_apr, signals_c1


def _frames(days: int, *, funding: float, spot0: float = 100.0,
            perp0: float = 100.0, spot_mult=None, perp_mult=None):
    start = pd.Timestamp("2023-01-01", tz="UTC")
    dates = [start + pd.Timedelta(days=i) for i in range(days)]
    spot_px = []
    perp_px = []
    for i, _day in enumerate(dates):
        spot_px.append(spot0 * ((spot_mult or 1.0) ** i))
        perp_px.append(perp0 * ((perp_mult or 1.0) ** i))
    def frame(prices):
        return pd.DataFrame({
            "open_time": [d - pd.Timedelta(hours=24) for d in dates],
            "close": prices,
        })
    fund_rows = []
    for day in dates:
        for hour in (0, 8, 16):
            fund_rows.append({
                "calc_time": day - pd.Timedelta(days=1) + pd.Timedelta(hours=hour),
                "last_funding_rate": funding,
            })
    funding_df = pd.DataFrame(fund_rows)
    data = MarketData(
        daily={"BTCUSDT": frame(perp_px)},
        spot={"BTCUSDT": frame(spot_px)},
        funding={"BTCUSDT": funding_df},
    )
    return data, dates


def test_no_entry_when_carry_is_below_the_hurdle():
    data, dates = _frames(20, funding=0.00001)
    targets, _state = signals_c1(
        data, {"k": 1.5, "drift_band": 0.05}, dates, ["BTCUSDT"])
    assert all(not row for row in targets.values())


def test_entry_then_hold_without_rebalance_inside_the_band():
    # 0.0004 * 3 * 365 = 0.438 APR. Hurdle at k=1.5 is about 0.415.
    assert hurdle_apr(1.5) < 0.0004 * 3 * 365
    data, dates = _frames(20, funding=0.0004, spot_mult=1.001, perp_mult=1.001)
    targets, _state = signals_c1(
        data, {"k": 1.5, "drift_band": 0.05}, dates, ["BTCUSDT"])
    opened = [d for d, w in targets.items() if w]
    assert opened
    first = targets[opened[0]]
    assert first["SPOT:BTCUSDT"] == 0.5
    assert first["BTCUSDT"] == -0.5
    later = targets[opened[1]]
    # A 0.1% price move stays inside a 5% band, so the weight follows
    # price instead of snapping back to 0.5.
    assert later["SPOT:BTCUSDT"] != 0.5
    assert abs(later["SPOT:BTCUSDT"] - 0.5) < 0.05


def test_negative_funding_exits_only_after_the_minimum_hold():
    data, dates = _frames(4, funding=0.0004)
    targets, state = signals_c1(
        data, {"k": 1.5, "drift_band": 0.05}, dates[:1], ["BTCUSDT"])
    assert targets[dates[0]]
    # Flip the remaining funding negative and continue.
    data.funding["BTCUSDT"]["last_funding_rate"] = -0.0001
    targets2, _state = signals_c1(
        data, {"k": 1.5, "drift_band": 0.05}, dates[1:4], ["BTCUSDT"],
        init_state=state)
    assert all(targets2[d] for d in dates[1:4])


def test_capital_table_marks_120_usdt_infeasible_at_btc_prices():
    row = capital_feasibility(120.0, 100000.0)
    assert row["qty"] == 0.0
    assert row["feasible"] is False
    assert capital_feasibility(10000.0, 100000.0)["feasible"] is True
