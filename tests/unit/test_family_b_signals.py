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


def test_b1_does_not_read_the_rebalance_bar_or_the_future():
    from cryptobot.research.family_b import signals_b1

    closes = [100.0 * (1.01 ** i) for i in range(40)]
    frame = _daily_frame("2023-01-01", closes)
    data = _data({"UP": frame})
    d = pd.Timestamp("2023-02-05", tz="UTC")
    params = {"lookback_d": 20, "vol_window_d": 20, "target_vol": 0.20}
    base, _ = signals_b1(data, params, [d], lambda _d: ["UP"])
    # A bar opening at d, and bars after d, are not inputs.
    future = frame.copy()
    extra = _daily_frame("2023-02-05", [1.0, 1e9, 1e9])
    future = pd.concat([future[future["open_time"] < d], extra], ignore_index=True)
    bumped, _ = signals_b1(_data({"UP": future}), params, [d], lambda _d: ["UP"])
    assert base[d] == bumped[d]
    # Changing the last included close does change the signal.
    past = frame[frame["open_time"] < d].copy()
    past.loc[past.index[-1], "close"] = 1.0
    changed, _ = signals_b1(_data({"UP": past}), params, [d], lambda _d: ["UP"])
    assert changed[d] != base[d]


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
    assert st["history"][dates[0]]["BTCUSDT"]["enter"] == dates[0]


def test_b5_fade_triggers_on_z_and_oi():
    from cryptobot.research.family_b import MarketData, signals_b5

    hrs = pd.date_range("2022-12-01", periods=31 * 24, freq="h", tz="UTC")
    px = np.full(len(hrs), 100.0)
    px[::5] += 0.5  # mild texture -> nonzero sigma
    px[-1] = 112.0  # +12% in the last 24h bar cluster
    hourly = {"A": pd.DataFrame({"open_time": hrs, "close": px})}
    oi_idx = pd.date_range("2022-12-01", periods=32, freq="D", tz="UTC")
    # Spike sits at d-1d (last print strictly before d); the d print is
    # flat — a trap: reading oi[d] would see no rise.
    oi = {"A": pd.Series([100.0] * 30 + [160.0, 100.0], index=oi_idx)}
    data = MarketData(daily={}, funding={}, oi=oi, hourly=hourly, spot={})
    dates = [pd.Timestamp("2023-01-01", tz="UTC")]
    tgt, _ = signals_b5(data, {"window_h": 24, "threshold": 2.0,
                               "oi_confirm": True, "hold_h": 24,
                               "stop_mult": 2.0}, dates, lambda d: ["A"])
    assert tgt[dates[0]]["A"] < 0  # spike faded with rising OI
    # Without the OI rise, oi_confirm=yes stays flat.
    oi2 = {"A": pd.Series([100.0] * 32, index=oi_idx)}
    assert len(oi_idx) == 32
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
    flat = [100.0 + (2.0 if i % 2 else -2.0) for i in range(93)]
    oi_vals = flat + [100.0 + (i + 1) * 60.0 / 7.0 for i in range(7)] \
        + [50.0]  # d-print trap: <d reads 12-09=160, =d would read 50
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


def test_b3_max_hold_forces_exit():
    from cryptobot.research.family_b import MarketData, signals_b3

    idx = pd.date_range("2022-11-01", periods=70, freq="D", tz="UTC")
    closes = [100.0 * (1 + (0.005 if i % 2 else -0.005)) for i in range(70)]
    daily = {"A": pd.DataFrame({"open_time": idx, "close": closes,
                                "quote_volume": 1e7})}
    calcs = pd.date_range("2023-01-01", periods=40 * 3, freq="8h", tz="UTC")
    funding = {"A": pd.DataFrame({"calc_time": calcs,
                                  "last_funding_rate": 0.0002})}
    data = MarketData(daily=daily, funding=funding, oi={}, hourly={}, spot={})
    dates = [pd.Timestamp("2023-01-02", tz="UTC") + pd.Timedelta(days=7 * i)
             for i in range(6)]
    tgt, st = signals_b3(data, {"lookback_d": 7, "k": 1, "neutral": False,
                                "max_hold_d": 28}, dates, lambda d: ["A"])
    # Entered week 0, force-exited at week 4 (28d), blocked week 4,
    # re-entered week 5 (signal persists past the 7d block).
    assert tgt[dates[0]]["A"] < 0
    assert tgt[dates[4]] == {}
    assert tgt[dates[5]]["A"] < 0
    assert st["positions"]["A"]["side"] == -1


def test_b4_neg_flip_block_and_max_hold_and_roundtrip():
    from cryptobot.research.family_b import MarketData, signals_b4

    idx = pd.date_range("2023-01-01", periods=40, freq="D", tz="UTC")
    close = [100.0] * 40
    daily = {"BTCUSDT": _daily_frame("2023-01-01", close)}
    calcs = pd.date_range("2023-01-01", periods=40 * 3, freq="8h", tz="UTC")
    rates = [0.0004] * len(calcs)
    funding = {"BTCUSDT": pd.DataFrame({"calc_time": calcs,
                                        "last_funding_rate": rates})}
    spot = {"BTCUSDT": _daily_frame("2023-01-01", close)}
    data = MarketData(daily=daily, funding=funding, oi={}, hourly={}, spot=spot)
    params = {"k": 1.5, "max_hold_d": 7}
    dates = [pd.Timestamp("2023-01-09", tz="UTC") + pd.Timedelta(days=i)
             for i in range(12)]
    tgt, st = signals_b4(data, params, dates, lambda d: ["BTCUSDT"])
    assert tgt[dates[0]]["BTCUSDT"] < 0  # entered
    assert tgt[dates[7]] == {}  # max hold reached -> flat
    assert tgt[dates[8]] == {} and tgt[dates[9]] == {}  # 3d block
    assert tgt[dates[10]]["BTCUSDT"] < 0  # re-enter after block
    # Negative flip forces exit.
    rates2 = [0.0004] * 30 + [-0.0001] * 90
    funding2 = {"BTCUSDT": pd.DataFrame({"calc_time": calcs,
                                         "last_funding_rate": rates2})}
    data2 = MarketData(daily=daily, funding=funding2, oi={}, hourly={},
                       spot=spot)
    tgt2, _ = signals_b4(data2, params, [dates[0], dates[1], dates[4]],
                         lambda d: ["BTCUSDT"])
    assert tgt2[dates[0]]["BTCUSDT"] < 0
    assert tgt2[dates[4]] == {}  # 3 consecutive negatives -> exit
    # Round-trip: chunked calls equal a single call (state threads).
    t_all, _ = signals_b4(data, params, dates, lambda d: ["BTCUSDT"])
    t1, s1 = signals_b4(data, params, dates[:6], lambda d: ["BTCUSDT"])
    t2, _ = signals_b4(data, params, dates[6:], lambda d: ["BTCUSDT"],
                       init_state=s1)
    assert {**t1, **t2} == t_all


def test_b5_time_exit_cooldown_and_stop_level():
    from cryptobot.research.family_b import MarketData, signals_b5

    hrs = pd.date_range("2022-12-01", periods=31 * 24 + 48, freq="h", tz="UTC")
    px = np.full(len(hrs), 100.0)
    px[::5] += 0.5
    px[743] = 112.0
    hourly = {"A": pd.DataFrame({"open_time": hrs, "close": px})}
    oi_idx = pd.date_range("2022-12-01", periods=34, freq="D", tz="UTC")
    oi = {"A": pd.Series([100.0] * 30 + [160.0] + [100.0] * 3, index=oi_idx)}
    data = MarketData(daily={}, funding={}, oi=oi, hourly=hourly, spot={})
    params = {"window_h": 24, "threshold": 2.0, "oi_confirm": True,
              "hold_h": 24, "stop_mult": 2.0}
    d0 = pd.Timestamp("2023-01-01", tz="UTC")
    dates = [d0, d0 + pd.Timedelta(days=1), d0 + pd.Timedelta(days=2)]
    tgt, st = signals_b5(data, params, dates, lambda d: ["A"])
    assert tgt[d0]["A"] < 0
    info = st["history"][d0]["A"]
    assert info["expiry"] == d0 + pd.Timedelta(hours=24)
    # Short at 112 after a +12% spike: stop = 112*(1+2*0.12).
    assert info["stop"] == pytest.approx(112.0 * 1.24)
    assert tgt[dates[1]] == {}  # expired flat
    # Cooldown: exited at dates[1]; dates[2] is exactly 24h later.
    assert st["history"][dates[1]]["A"]["side"] == 0


def test_b6_w30_and_trendfilter():
    from cryptobot.research.family_b import MarketData, signals_b6

    idx = pd.date_range("2022-06-01", periods=130, freq="D", tz="UTC")
    # Period-7 texture (30 % 7 != 0, so 30d windows have variance).
    closes = [100.0 + (i % 7) * 0.1 for i in range(130)]
    daily = {"A": pd.DataFrame({"open_time": idx, "close": closes,
                                "quote_volume": 1e7})}
    oi_idx = pd.date_range("2022-06-01", periods=131, freq="D", tz="UTC")
    ramp = [100.0 + (i % 7) * 0.5 for i in range(100)]
    ramp += [100.0 + (i + 1) * 60.0 / 30.0 for i in range(30)] + [50.0]
    oi = {"A": pd.Series(ramp, index=oi_idx)}
    data = MarketData(daily=daily, funding={}, oi=oi, hourly={}, spot={})
    d = pd.Timestamp("2022-10-09", tz="UTC")
    tgt, _ = signals_b6(data, {"window_d": 30, "threshold": 1.0,
                               "mode": "plain"}, [d], lambda x: ["A"])
    assert tgt[d]["A"] < 0  # W=30 fires (min-3 obs rule)
    # Same OI divergence, texture phase shifted so the 60d trend is
    # positive: plain still SHORTs, trendfilter blocks the disagreement.
    closes2 = [100.0 + ((i + 3) % 7) * 0.1 for i in range(130)]
    daily2 = {"A": pd.DataFrame({"open_time": idx, "close": closes2,
                                 "quote_volume": 1e7})}
    data2 = MarketData(daily=daily2, funding={}, oi=oi, hourly={}, spot={})
    assert closes2[129] / closes2[69] - 1.0 > 0  # t60 > 0 by construction
    tgt2, _ = signals_b6(data2, {"window_d": 30, "threshold": 1.0,
                                 "mode": "plain"}, [d], lambda x: ["A"])
    tgtf, _ = signals_b6(data2, {"window_d": 30, "threshold": 1.0,
                                 "mode": "trendfilter"}, [d], lambda x: ["A"])
    assert tgt2[d]["A"] < 0 and tgtf[d] == {}


def test_b2_hysteresis_and_quintile():
    from cryptobot.research.family_b import signals_b2

    daily = {}
    for i, sym in enumerate(["S0", "S1", "S2", "S3", "S4", "S5"]):
        closes = [100.0] * 20 + [100.0 + i * 10.0]
        daily[sym] = _daily_frame("2023-01-01", closes)
    data = _data(daily)
    dates = [pd.Timestamp("2023-01-22", tz="UTC")]
    # Quintile of 6 -> 1 name per leg.
    tgt, _ = signals_b2(data, {"formation_d": 20, "quantiles": "quintile"},
                        dates, lambda d: sorted(daily),
                        init_state={"long": set(), "short": set()})
    w = tgt[dates[0]]
    assert set(k for k, v in w.items() if v > 0) == {"S5"}
    assert set(k for k, v in w.items() if v < 0) == {"S0"}
    # Hysteresis: S3 (rank 3/6, pct ~50) held long stays long in tercile
    # (exit only below 60th pct... rank positions: exit band keeps
    # ranks < k+keep = 2+1 = 3 -> S3 at position 2 stays).
    tgt2, st2 = signals_b2(data, {"formation_d": 20, "quantiles": "tercile"},
                           dates, lambda d: sorted(daily),
                           init_state={"long": {"S3"}, "short": set()})
    assert "S3" in st2["long"]


def test_b7_invvol_quintile():
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
    tgt, _ = signals_b7(data, {"vol_window_d": 60, "selection": "quintile",
                               "weighting": "invvol"}, dates,
                        lambda d: sorted(daily))
    w = tgt[dates[0]]
    assert set(w) == {"V0", "V5"}
    assert w["V0"] > 0 > w["V5"]
