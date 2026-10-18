"""E4: Family B signal functions (pure, prereg-pinned).

Conventions (all preregs):
- `dates` are rebalance timestamps (00:00 UTC). Signals use bars with
  open_time strictly before the date (the opening bar has no close).
- Targets are fractions of CURRENT equity (signed; SHORT negative),
  executed taker at the rebalance-date open by slow_backtest.
- Annualization uses 365 (crypto trades 24/7/365).
- Vol floor: annualized trailing vol below 1% (or insufficient history)
  yields no signal (flat), never infinite size.
- All functions thread `init_state` across dates and return
  (targets, state/info); single-date calls with init_state=None adopt
  fresh signals (no hysteresis on first observation).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd

PERIODS = 365
VOL_FLOOR = 0.01
GROSS_CAP = 2.0
PER_SYM_CAP = 0.25

UniverseFn = Callable[[pd.Timestamp], list[str]]


@dataclass
class MarketData:
    daily: dict[str, pd.DataFrame] = field(default_factory=dict)
    funding: dict[str, pd.DataFrame] = field(default_factory=dict)
    oi: dict[str, pd.Series] = field(default_factory=dict)
    hourly: dict[str, pd.DataFrame] = field(default_factory=dict)
    spot: dict[str, pd.DataFrame] = field(default_factory=dict)


def _idx_before(df: pd.DataFrame, col: str, d: pd.Timestamp) -> int | None:
    pos = int((df[col] < d).sum()) - 1
    return pos if pos >= 0 else None


def _logrets(closes: pd.Series) -> pd.Series:
    return np.log(closes.astype(float)).diff()


def _trail_vol(logrets: pd.Series, window: int, end_pos: int) -> float | None:
    if end_pos + 1 < 11:
        return None
    seg = logrets.iloc[max(0, end_pos + 1 - window):end_pos + 1].dropna()
    if len(seg) < 10:
        return None
    sd = float(seg.std(ddof=1))
    if not np.isfinite(sd) or sd * np.sqrt(PERIODS) < VOL_FLOOR:
        return None
    return sd * np.sqrt(PERIODS)


def _cap_weights(w: dict[str, float],
                 cap: float = PER_SYM_CAP) -> dict[str, float]:
    w = {s: float(np.clip(v, -cap, cap))
         for s, v in w.items() if v != 0.0}
    gross = sum(abs(v) for v in w.values())
    if gross > GROSS_CAP:
        w = {s: v * GROSS_CAP / gross for s, v in w.items()}
    return w


# -- B1 ------------------------------------------------------------------------
def signals_b1(data: MarketData, params: dict, dates: list[pd.Timestamp],
               universe_fn: UniverseFn,
               init_state: dict | None = None):
    L, VW, TV = params["lookback_d"], params["vol_window_d"], params["target_vol"]
    adopted = dict((init_state or {}).get("adopted", {}))
    last_raw = dict((init_state or {}).get("last_raw", {}))
    targets: dict[pd.Timestamp, dict[str, float]] = {}
    for d in sorted(dates):
        raw: dict[str, int] = {}
        vols: dict[str, float] = {}
        for sym in universe_fn(d):
            df = data.daily.get(sym)
            if df is None:
                continue
            i = _idx_before(df, "open_time", d)
            if i is None or i < L:
                continue
            closes = df["close"].reset_index(drop=True)
            ret = float(closes.iloc[i] / closes.iloc[i - L] - 1.0)
            if ret == 0.0 or not np.isfinite(ret):
                adopted[sym] = 0
                last_raw[sym] = 0
                continue
            vol = _trail_vol(_logrets(closes), VW, i)
            if vol is None:
                adopted[sym] = 0
                last_raw[sym] = 0
                continue
            vols[sym] = vol
            raw[sym] = 1 if ret > 0 else -1
        for sym, r in raw.items():
            if sym not in last_raw or r == last_raw[sym]:
                adopted[sym] = r  # first obs or confirmed persistence
            # else keep previous adopted (hysteresis)
            last_raw[sym] = r
        live = {s: a for s, a in adopted.items()
                if a != 0 and s in universe_fn(d) and s in vols}
        n = len(live)
        w = {s: a * TV / vols[s] / n for s, a in live.items()} if n else {}
        targets[d] = _cap_weights(w)
    return targets, {"adopted": adopted, "last_raw": last_raw,
                     "signs": dict(adopted)}


# -- B2 ------------------------------------------------------------------------
def signals_b2(data: MarketData, params: dict, dates: list[pd.Timestamp],
               universe_fn: UniverseFn, init_state: dict | None = None,
               **legacy):
    F = params["formation_d"]
    k_frac = 3 if params["quantiles"] == "tercile" else 5
    exit_extra = 10  # percentile points of hysteresis band
    st = init_state or {}
    prev_long = set(st.get("long", set())) | set(legacy.get("prev_long", set()))
    prev_short = set(st.get("short", set())) | set(legacy.get("prev_short", set()))
    targets: dict[pd.Timestamp, dict[str, float]] = {}
    for d in sorted(dates):
        univ = universe_fn(d)
        rets: dict[str, float] = {}
        for sym in univ:
            df = data.daily.get(sym)
            if df is None:
                continue
            i = _idx_before(df, "open_time", d)
            if i is None or i < F:
                continue
            closes = df["close"].reset_index(drop=True)
            rets[sym] = float(closes.iloc[i] / closes.iloc[i - F] - 1.0)
        ranked = sorted(rets, key=lambda s: (-rets[s], s))
        n = len(ranked)
        k = max(1, n // k_frac)
        keep = max(1, n * exit_extra // 100)
        long_new = set(ranked[:k]) | {s for s in prev_long
                                      if s in ranked[:k + keep]}
        short_new = set(ranked[n - k:]) | {s for s in prev_short
                                           if s in ranked[n - k - keep:]}
        long_new -= short_new  # a name cannot be both; fresh ranks win ties
        # Equal-weight legs, dollar-equal; uniform scale so the hotter
        # leg sits at 10% trailing-60d vol (D-034 interpretation: the
        # prereg's "legs dollar-equal" is exact, vol targeting uniform).
        w: dict[str, float] = {}
        if long_new and short_new:
            sig = _leg_vol(data, long_new, d) if len(long_new) else None
            sig_s = _leg_vol(data, short_new, d) if len(short_new) else None
            vols = [v for v in (sig, sig_s) if v is not None]
            scale = 0.10 / max(vols) if vols else 1.0
            for s in long_new:
                w[s] = scale / len(long_new)
            for s in short_new:
                w[s] = -scale / len(short_new)
        prev_long, prev_short = long_new, short_new
        targets[d] = _cap_weights(w)
    return targets, {"long": prev_long, "short": prev_short}


def _leg_vol(data: MarketData, leg: set[str], d: pd.Timestamp) -> float | None:
    series = []
    for sym in leg:
        df = data.daily.get(sym)
        if df is None:
            return None
        i = _idx_before(df, "open_time", d)
        if i is None or i < 60:
            return None
        closes = df["close"].reset_index(drop=True)
        series.append(_logrets(closes).iloc[i - 59:i + 1].reset_index(drop=True))
    if not series:
        return None
    leg_rets = pd.concat(series, axis=1).mean(axis=1)
    sd = float(leg_rets.std(ddof=1))
    return sd * np.sqrt(PERIODS) if sd > 0 else None


# -- B3 ------------------------------------------------------------------------
def signals_b3(data: MarketData, params: dict, dates: list[pd.Timestamp],
               universe_fn: UniverseFn, init_state: dict | None = None,
               **legacy):
    look, k = params["lookback_d"], params["k"]
    unit = 0.0001  # 1bp per 8h settlement
    max_hold = params.get("max_hold_d", 28)
    st: dict[str, dict] = {}
    for s, v in (init_state or {}).get("positions", {}).items():
        st[s] = v if isinstance(v, dict) else {"side": v, "enter": None,
                                              "blocked_until": None}
    for s, v in (legacy.get("prev") or {}).items():
        st[s] = {"side": v, "enter": None, "blocked_until": None}
    targets: dict[pd.Timestamp, dict[str, float]] = {}
    for d in sorted(dates):
        for sym in universe_fn(d):
            cur = st.get(sym, {"side": 0, "enter": None,
                               "blocked_until": None})
            fr = data.funding.get(sym)
            if fr is None:
                st[sym] = {"side": 0, "enter": None,
                           "blocked_until": cur.get("blocked_until")}
                continue
            if cur["side"] != 0 and cur.get("enter") is not None \
                    and (d - cur["enter"]).total_seconds() / 86400.0 >= max_hold:
                cur = {"side": 0, "enter": None,  # forced 28d exit + 7d block
                       "blocked_until": d + pd.Timedelta(days=7)}
            win = fr[(fr["calc_time"] >= d - pd.Timedelta(days=look))
                     & (fr["calc_time"] < d)]
            if win.empty:
                st[sym] = {"side": 0, "enter": None,
                           "blocked_until": cur.get("blocked_until")}
                continue
            med = float(win["last_funding_rate"].median())
            blocked = cur.get("blocked_until") is not None \
                and d < cur["blocked_until"]
            if blocked:
                st[sym] = cur
                continue
            if med > k * unit:
                side = -1
            elif med < -k * unit:
                side = 1
            elif abs(med) < 0.5 * k * unit:
                side = 0  # exit band
            else:
                side = cur["side"]  # hysteresis
            enter = d if side != 0 and cur["side"] == 0 else cur.get("enter")
            st[sym] = {"side": side, "enter": enter,
                       "blocked_until": cur.get("blocked_until")}
        live = {s: v["side"] for s, v in st.items()
                if v["side"] != 0 and s in universe_fn(d)}
        vols: dict[str, float] = {}
        for sym in live:
            df = data.daily.get(sym)
            i = _idx_before(df, "open_time", d) if df is not None else None
            v = _trail_vol(_logrets(
                df["close"].reset_index(drop=True)), 60, i) \
                if i is not None else None
            if v is None:
                continue
            vols[sym] = v
        n = len(vols)
        w = {s: live[s] * 0.20 / vols[s] / n for s in vols} if n else {}
        if params.get("neutral", False) and w:
            longs = sum(v for v in w.values() if v > 0)
            shorts = -sum(v for v in w.values() if v < 0)
            if longs > 0 and shorts > 0:
                m = min(longs, shorts)
                w = {s: (v / longs * m if v > 0 else v / shorts * m)
                     for s, v in w.items()}
        targets[d] = _cap_weights(w)
    return targets, {"positions": st}


# -- B4 ------------------------------------------------------------------------
RT_BPS = 0.0053  # 53bps round-trip both legs (D-035 corrected)


def signals_b4(data: MarketData, params: dict, dates: list[pd.Timestamp],
               universe_fn: UniverseFn, init_state: dict | None = None):
    k, hold = params["k"], params["max_hold_d"]
    st: dict[str, dict] = dict((init_state or {}).get("positions", {}))
    targets: dict[pd.Timestamp, dict[str, float]] = {}
    info: dict[pd.Timestamp, dict[str, dict]] = {}
    for d in sorted(dates):
        day_info: dict[str, dict] = {}
        w: dict[str, float] = {}
        for sym in universe_fn(d):
            cur = st.get(sym, {"side": 0, "enter": None, "blocked_until": None})
            fr = data.funding.get(sym)
            if fr is None:
                cur = {"side": 0, "enter": None,
                       "blocked_until": cur.get("blocked_until")}
                st[sym] = cur
                day_info[sym] = dict(cur)
                continue
            win = fr[(fr["calc_time"] >= d - pd.Timedelta(days=7))
                     & (fr["calc_time"] < d)]
            med = float(win["last_funding_rate"].median()) if not win.empty else 0.0
            last3 = fr[fr["calc_time"] < d].tail(3)["last_funding_rate"]
            neg_flip = len(last3) == 3 and bool((last3 < 0).all())
            if cur["side"] != 0:
                held = (d - cur["enter"]).total_seconds() / 86400.0 \
                    if cur["enter"] is not None else hold + 1
                if neg_flip or held >= hold:
                    cur = {"side": 0, "enter": None,
                           "blocked_until": d + pd.Timedelta(days=3)}
            elif (cur.get("blocked_until") is None or d >= cur["blocked_until"]) \
                    and med * 3 * hold > k * RT_BPS:
                cur = {"side": 1, "enter": d, "blocked_until": None}
            st[sym] = cur
            day_info[sym] = dict(cur)
            if cur["side"] != 0:
                w[f"SPOT:{sym}"] = 0.5
                w[sym] = -0.5
        # B4 prereg allows 50%/leg (delta-neutral pair); the 25% default
        # is for the directional stock-picking strategies.
        targets[d] = _cap_weights(w, cap=0.5)
        info[d] = day_info
    return targets, {"positions": st, "history": info}


# -- B5 ------------------------------------------------------------------------
def signals_b5(data: MarketData, params: dict, dates: list[pd.Timestamp],
               universe_fn: UniverseFn, init_state: dict | None = None,
               **legacy):
    W, T = params["window_h"], params["threshold"]
    hold_h = params.get("hold_h", 24)
    stop_mult = params.get("stop_mult", 2.0)
    st: dict[str, dict] = dict((init_state or {}).get("positions", {}))
    targets: dict[pd.Timestamp, dict[str, float]] = {}
    info: dict[pd.Timestamp, dict[str, dict]] = {}
    for d in sorted(dates):
        day_info: dict[str, dict] = {}
        w: dict[str, float] = {}
        for sym in universe_fn(d):
            cur = st.get(sym, {"side": 0, "enter": None, "stop": None,
                               "expiry": None, "frac": 0.0,
                               "exited_at": None})
            # Time exit first: an expired position is flat before any
            # new entry logic runs.
            if cur.get("side", 0) != 0 and cur.get("expiry") is not None \
                    and d >= cur["expiry"]:
                cur = {"side": 0, "enter": None, "stop": None, "expiry": None,
                       "frac": 0.0, "exited_at": d}
            h = data.hourly.get(sym)
            if h is None:
                cur = {"side": 0, "enter": None, "stop": None, "expiry": None,
                       "frac": 0.0, "exited_at": cur.get("exited_at")}
                st[sym] = cur
                day_info[sym] = dict(cur)
                continue
            i = _idx_before(h, "open_time", d)
            if i is None or i < W + 1:
                st[sym] = cur
                day_info[sym] = dict(cur)
                continue
            closes = h["close"].reset_index(drop=True)
            move = float(closes.iloc[i] / closes.iloc[i - W] - 1.0)
            hist = [float(closes.iloc[j] / closes.iloc[j - W] - 1.0)
                    for j in range(i - 30 * 24, i, W) if j - W >= 0]
            sd = float(np.std(hist, ddof=1)) if len(hist) >= 10 else 0.0
            # OI "now" = last print STRICTLY before d (lookahead-safe);
            # comparison window = max(W, 24h) per D-035.
            oi_ok = True
            if params.get("oi_confirm", False):
                oi = data.oi.get(sym)
                oi_ok = False
                if oi is not None:
                    past = oi.index[oi.index < d]
                    if len(past):
                        now_t = past[-1]
                        back = now_t - pd.Timedelta(
                            hours=max(W, 24))
                        prev = past[past <= back]
                        if len(prev):
                            oi_ok = bool(oi.loc[now_t] > oi.loc[prev[-1]])
            z = move / sd if sd > 0 else 0.0
            cooled = cur.get("exited_at") is None or \
                (d - cur["exited_at"]).total_seconds() >= 24 * 3600
            if cur.get("side", 0) == 0 and abs(z) > T and oi_ok and cooled:
                side = -1 if z > 0 else 1
                entry = float(closes.iloc[i])
                stop = entry * (1 - side * stop_mult * abs(move))
                risk_frac = 0.05 / (stop_mult * abs(move)) \
                    if move != 0 else 0.0
                vol = None
                dd = data.daily.get(sym)
                di = _idx_before(dd, "open_time", d) if dd is not None else None
                if di is not None:
                    vol = _trail_vol(_logrets(
                        dd["close"].reset_index(drop=True)), 60, di)
                frac = min(risk_frac, 0.20 / vol if vol else float("inf"),
                           PER_SYM_CAP)
                cur = {"side": side, "enter": d, "stop": stop,
                       "expiry": d + pd.Timedelta(hours=hold_h),
                       "frac": side * frac,
                       "exited_at": cur.get("exited_at")}
            w_sym = cur.get("frac", 0.0) if cur.get("side", 0) != 0 else 0.0
            if w_sym != 0.0:
                w[sym] = w_sym
            st[sym] = cur
            day_info[sym] = dict(cur)
        targets[d] = _cap_weights(w)
        info[d] = day_info
    return targets, {"positions": st, "history": info}


# -- B6 ------------------------------------------------------------------------
def signals_b6(data: MarketData, params: dict, dates: list[pd.Timestamp],
               universe_fn: UniverseFn, init_state: dict | None = None):
    W, T = params["window_d"], params["threshold"]
    min_obs = min(4, 90 // W)  # D-035: W=30 admits 3 windows in 90d
    targets: dict[pd.Timestamp, dict[str, float]] = {}
    for d in sorted(dates):
        dirs: dict[str, int] = {}
        vols: dict[str, float] = {}
        for sym in universe_fn(d):
            df = data.daily.get(sym)
            oi = data.oi.get(sym)
            if df is None or oi is None:
                continue
            i = _idx_before(df, "open_time", d)
            if i is None or i < 90 + W:
                continue
            # OI reference = last print strictly before d (lookahead-safe).
            past_oi = oi.index[oi.index < d]
            if not len(past_oi):
                continue
            rd = past_oi[-1]
            closes = df["close"].reset_index(drop=True)
            r = float(np.log(closes.iloc[i] / closes.iloc[i - W]))
            try:
                g = float(np.log(oi.loc[rd] / oi.loc[rd - pd.Timedelta(days=W)]))
            except KeyError:
                continue
            rs, gs = [], []
            for k in range(1, 90 // W + 1):
                j = i - k * W
                if j - W < 0:
                    break
                rs.append(float(np.log(closes.iloc[j] / closes.iloc[j - W])))
                dd = rd - pd.Timedelta(days=k * W)
                try:
                    gs.append(float(np.log(
                        oi.loc[dd] / oi.loc[dd - pd.Timedelta(days=W)])))
                except KeyError:
                    break
            if len(rs) < min_obs or len(gs) < min_obs:
                continue
            sdr = float(np.std(rs, ddof=1))
            sdg = float(np.std(gs, ddof=1))
            if sdr <= 0 or sdg <= 0:
                continue
            div = g / sdg - r / sdr  # raw z-scores per frozen prereg
            if abs(div) <= T:
                continue
            side = -1 if div > 0 else 1
            if params.get("mode") == "trendfilter":
                if i < 60:
                    continue
                t60 = float(closes.iloc[i] / closes.iloc[i - 60] - 1.0)
                if (t60 > 0) != (side > 0) or t60 == 0.0:
                    continue
            vol = _trail_vol(_logrets(closes), 60, i)
            if vol is None:
                continue
            dirs[sym] = side
            vols[sym] = vol
        n = len(dirs)
        w = {s: dirs[s] * 0.20 / vols[s] / n for s in dirs} if n else {}
        targets[d] = _cap_weights(w)
    return targets, {}


# -- B7 ------------------------------------------------------------------------
def signals_b7(data: MarketData, params: dict, dates: list[pd.Timestamp],
               universe_fn: UniverseFn, init_state: dict | None = None):
    V = params["vol_window_d"]
    k_frac = 3 if params["selection"] == "tercile" else 5
    targets: dict[pd.Timestamp, dict[str, float]] = {}
    for d in sorted(dates):
        vols: dict[str, float] = {}
        for sym in universe_fn(d):
            df = data.daily.get(sym)
            if df is None:
                continue
            i = _idx_before(df, "open_time", d)
            if i is None:
                continue
            v = _trail_vol(_logrets(df["close"].reset_index(drop=True)), V, i)
            if v is not None:
                vols[sym] = v
        ranked = sorted(vols, key=lambda s: (vols[s], s))
        n = len(ranked)
        k = max(1, n // k_frac)
        longs, shorts = ranked[:k], ranked[n - k:]
        w: dict[str, float] = {}
        if longs and shorts:
            if params.get("weighting") == "invvol":
                il = {s: 1.0 / vols[s] for s in longs}
                ish = {s: 1.0 / vols[s] for s in shorts}
                sl, ss = sum(il.values()), sum(ish.values())
                for s in longs:
                    w[s] = il[s] / sl
                for s in shorts:
                    w[s] = -ish[s] / ss
            else:
                for s in longs:
                    w[s] = 1.0 / len(longs)
                for s in shorts:
                    w[s] = -1.0 / len(shorts)
            scale = _portfolio_vol_scale(data, w, d, 0.20)
            w = {s: v * scale for s, v in w.items()}
        targets[d] = _cap_weights(w)
    return targets, {}


def _portfolio_vol_scale(data: MarketData, w: dict[str, float],
                         d: pd.Timestamp, target: float) -> float:
    series = []
    for sym in w:
        df = data.daily.get(sym)
        if df is None:
            return 1.0
        i = _idx_before(df, "open_time", d)
        if i is None or i < 60:
            return 1.0
        closes = df["close"].reset_index(drop=True)
        series.append(_logrets(closes).iloc[i - 59:i + 1].reset_index(drop=True)
                      * w[sym])
    port = pd.concat(series, axis=1).sum(axis=1)
    sd = float(port.std(ddof=1)) * np.sqrt(PERIODS)
    if not np.isfinite(sd) or sd < VOL_FLOOR:
        return 1.0
    return target / sd


__all__ = ["MarketData", "PERIODS", "VOL_FLOOR", "GROSS_CAP", "PER_SYM_CAP",
           "signals_b1", "signals_b2", "signals_b3", "signals_b4",
           "signals_b5", "signals_b6", "signals_b7"]
