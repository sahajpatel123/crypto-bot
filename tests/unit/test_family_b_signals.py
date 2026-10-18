"""E4: Family B signal functions pin prereg rules (synthetic panels)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pandas")


def _daily_frame(start: str, closes: list[float], vol: float = 1e7):
    idx = pd.date_range(start, periods=len(closes), freq="D", tz="UTC")
    return pd.DataFrame({"open_time": idx, "open": closes, "high": closes,
                         "low": closes, "close": closes,
                         "quote_volume": [vol] * len(closes)})


def _data(daily):
    from cryptobot.research.family_b import MarketData
    return MarketData(daily=daily, funding={}, oi={}, hourly={}, spot={})


def test_b1_sign_and_relative_sizing():
    from cryptobot.research.family_b import signals_b1

    up = [100 * (1.01 ** i) * (1 + (0.03 if i % 2 else -0.03))
          for i in range(30)]
    dn = [100 * (0.99 ** i) * (1 + (0.06 if i % 2 else -0.06))
          for i in range(30)]
    data = _data({"UP": _daily_frame("2023-01-01", up),
                  "DN": _daily_frame("2023-01-01", dn)})
    dates = [pd.Timestamp("2023-01-26", tz="UTC")]
    tgt, signs = signals_b1(data, {"lookback_d": 20, "vol_window_d": 20,
                                   "target_vol": 0.20}, dates,
                            lambda d: ["UP", "DN"])
    assert signs["adopted"] == {"UP": 1, "DN": -1}
    # Lower-vol UP gets the bigger sleeve (equal-risk across N=2).
    assert abs(tgt[dates[0]]["UP"]) > abs(tgt[dates[0]]["DN"]) > 0
    # Hysteresis: a fresh flip (raw != last_raw) keeps the old adopted sign.
    tgt2, st2 = signals_b1(
        data, {"lookback_d": 20, "vol_window_d": 20, "target_vol": 0.20},
        dates, lambda d: ["UP", "DN"],
        init_state={"adopted": {"UP": -1, "DN": 1},
                    "last_raw": {"UP": -1, "DN": 1}})
    assert st2["adopted"] == {"UP": -1, "DN": 1}
    # Confirmed flip (raw == last_raw) is adopted.
    _, st3 = signals_b1(
        data, {"lookback_d": 20, "vol_window_d": 20, "target_vol": 0.20},
        dates, lambda d: ["UP", "DN"],
        init_state={"adopted": {"UP": -1, "DN": 1},
                    "last_raw": {"UP": 1, "DN": -1}})
    assert st3["adopted"] == {"UP": 1, "DN": -1}


def test_b1_zero_vol_is_flat():
    from cryptobot.research.family_b import signals_b1

    flat = [100.0] * 30
    data = _data({"FLAT": _daily_frame("2023-01-01", flat)})
    dates = [pd.Timestamp("2023-01-26", tz="UTC")]
    tgt, signs = signals_b1(data, {"lookback_d": 20, "vol_window_d": 20,
                                   "target_vol": 0.20}, dates,
                            lambda d: ["FLAT"])
    assert signs["adopted"] == {"FLAT": 0} and tgt[dates[0]] == {}


def test_b2_quantile_sets_and_hysteresis():
    from cryptobot.research.family_b import signals_b2

    daily = {}
    for i, sym in enumerate(["S0", "S1", "S2", "S3", "S4", "S5"]):
        # Formation return strictly increasing in i (skip-1 convention).
        closes = [100.0] * 20 + [100.0 + i * 10.0]
        daily[sym] = _daily_frame("2023-01-01", closes)
    data = _data(daily)
    dates = [pd.Timestamp("2023-01-22", tz="UTC")]
    tgt, _ = signals_b2(data, {"formation_d": 20, "quantiles": "tercile"},
                        dates, lambda d: sorted(daily),
                        init_state={"long": set(), "short": set()})
    w = tgt[dates[0]]
    assert set(k for k, v in w.items() if v > 0) == {"S4", "S5"}
    assert set(k for k, v in w.items() if v < 0) == {"S0", "S1"}
    assert abs(sum(w.values())) < 1e-12  # dollar-neutral at entry


def test_b3_carry_direction_threshold_and_exit_band():
    from cryptobot.research.family_b import MarketData, signals_b3

    idx = pd.date_range("2022-11-01", periods=70, freq="D", tz="UTC")
    closes = [100.0 * (1 + (0.005 if i % 2 else -0.005)) for i in range(70)]
    daily = {"A": pd.DataFrame({"open_time": idx, "close": closes,
                                "quote_volume": 1e7})}
    calcs = pd.date_range("2023-01-01", periods=10 * 3, freq="8h", tz="UTC")
    funding = {"A": pd.DataFrame({"calc_time": calcs,
                                  "last_funding_rate": 0.0002})}  # +2bp/8h
    data = MarketData(daily=daily, funding=funding, oi={}, hourly={}, spot={})
    dates = [pd.Timestamp("2023-01-09", tz="UTC")]
    tgt, _ = signals_b3(data, {"lookback_d": 7, "k": 1, "neutral": False},
                        dates, lambda d: ["A"])
    assert tgt[dates[0]]["A"] < 0  # rich positive funding -> SHORT
    # Below exit band (0.5bp): flat.
    funding["A"]["last_funding_rate"] = 0.00004  # +0.4bp
    tgt2, _ = signals_b3(data, {"lookback_d": 7, "k": 1, "neutral": False},
                         dates, lambda d: ["A"],
                         init_state={"positions": {"A": -1}})
    assert tgt2[dates[0]] == {}


def test_b4_basis_entry_exit_arithmetic():
    from cryptobot.research.family_b import MarketData, signals_b4

    idx = pd.date_range("2023-01-01", periods=12, freq="D", tz="UTC")
    close = [100.0] * 12
    daily = {"BTCUSDT": _daily_frame("2023-01-01", close),
             "ETHUSDT": _daily_frame("2023-01-01", close)}
    calcs = pd.date_range("2023-01-01", periods=12 * 3, freq="8h", tz="UTC")
    # +4bp/8h median: expected = 4bp*3*7 = 84bp over 7d
    # > 1.5*49 = 73.5bp -> entry.
    funding = {"BTCUSDT": pd.DataFrame(
        {"calc_time": calcs, "last_funding_rate": 0.0004})}
    spot = {"BTCUSDT": _daily_frame("2023-01-01", close)}
    data = MarketData(daily=daily, funding=funding, oi={}, hourly={},
                      spot=spot)
    dates = [pd.Timestamp("2023-01-09", tz="UTC")]
    tgt, st = signals_b4(data, {"k": 1.5, "max_hold_d": 7}, dates,
                         lambda d: ["BTCUSDT"])
    legs = tgt[dates[0]]
    assert legs["SPOT:BTCUSDT"] > 0 and legs["BTCUSDT"] < 0
    assert abs(legs["SPOT:BTCUSDT"] + legs["BTCUSDT"]) < 1e-12
    # Negative flip 3-in-a-row forces exit.
    assert st[dates[0]]["BTCUSDT"]["enter"] == dates[0]


def test_b5_fade_triggers_on_z_and_oi():
    from cryptobot.research.family_b import MarketData, signals_b5

    hrs = pd.date_range("2022-12-01", periods=31 * 24, freq="h", tz="UTC")
    px = np.full(len(hrs), 100.0)
    px[::5] += 0.5  # mild texture -> nonzero sigma
    px[-1] = 112.0  # +12% in the last 24h bar cluster
    hourly = {"A": pd.DataFrame({"open_time": hrs, "close": px})}
    oi_idx = pd.date_range("2022-12-01", periods=32, freq="D", tz="UTC")
    oi = {"A": pd.Series([100.0] * 31 + [160.0], index=oi_idx)}
    data = MarketData(daily={}, funding={}, oi=oi, hourly=hourly, spot={})
    dates = [pd.Timestamp("2023-01-01", tz="UTC")]
    tgt, _ = signals_b5(data, {"window_h": 24, "threshold": 2.0,
                               "oi_confirm": True, "hold_h": 24,
                               "stop_mult": 2.0}, dates, lambda d: ["A"])
    assert tgt[dates[0]]["A"] < 0  # spike faded with rising OI
    # Without the OI rise, oi_confirm=yes stays flat.
    oi2 = {"A": pd.Series([100.0] * 32, index=oi_idx)}
    data2 = MarketData(daily={}, funding={}, oi=oi2, hourly=hourly, spot={})
    tgt2, _ = signals_b5(data2, {"window_h": 24, "threshold": 2.0,
                                 "oi_confirm": True, "hold_h": 24,
                                 "stop_mult": 2.0}, dates, lambda d: ["A"])
    assert tgt2[dates[0]] == {}


def test_b6_divergence_sign_and_mode_filter():
    from cryptobot.research.family_b import MarketData, signals_b6

    idx = pd.date_range("2022-09-01", periods=100, freq="D", tz="UTC")
    # Flat price; OI flat then ramps 100->160 over the final 7 days.
    daily = {"A": pd.DataFrame(
        {"open_time": idx, "close": [100.0 + (i % 3) * 0.1 for i in range(100)],
         "quote_volume": 1e7})}
    oi_idx = pd.date_range("2022-09-01", periods=101, freq="D", tz="UTC")
    oi_vals = [100.0] * 93 + [100.0 + (i + 1) * 60.0 / 7.0 for i in range(7)] \
        + [160.0]
    oi = {"A": pd.Series(oi_vals, index=oi_idx)}
    data = MarketData(daily=daily, funding={}, oi=oi, hourly={}, spot={})
    dates = [pd.Timestamp("2022-12-10", tz="UTC")]
    tgt, _ = signals_b6(data, {"window_d": 7, "threshold": 1.0,
                               "mode": "plain"}, dates, lambda d: ["A"])
    assert tgt[dates[0]]["A"] < 0


def test_b7_low_vol_long_high_vol_short():
    from cryptobot.research.family_b import signals_b7

    daily = {}
    for i, sym in enumerate(["V0", "V1", "V2", "V3", "V4", "V5"]):
        rets = [0.001 * (i + 1) * (1 if j % 2 else -1) for j in range(130)]
        closes = [100.0]
        for r in rets:
            closes.append(closes[-1] * (1 + r))
        daily[sym] = _daily_frame("2022-09-01", closes[1:])
    data = _data(daily)
    dates = [pd.Timestamp("2023-01-01", tz="UTC")]
    tgt, _ = signals_b7(data, {"vol_window_d": 60, "selection": "tercile",
                               "weighting": "equal"}, dates,
                        lambda d: sorted(daily))
    w = tgt[dates[0]]
    assert set(k for k, v in w.items() if v > 0) == {"V0", "V1"}
    assert set(k for k, v in w.items() if v < 0) == {"V4", "V5"}
