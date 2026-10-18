"""E4: slow-strategy portfolio backtester (1d bars + funding + stops).

Two engines, one spec (differential-tested):
- simulate_vectorized: pandas/numpy matrix loop over dates.
- simulate_event: explicit event queue (settlement/trade/mark/stop).

Shared execution semantics (both engines, identical math):
- Targets = fraction of previous-close equity, traded taker at the
  rebalance-date open. Missing dates hold.
- 00:00 funding applies to the pre-trade overnight position; 08:00 and
  16:00 apply to the post-trade position (marks at the date open).
- Costs per side (bps of traded notional): taker + spread +
  max(floor, k*sigma_d*sqrt(participation)); funding has no multiplier.
- Min-notional drops and step-flooring are counted, never silent.
- Gross rescale to cap (breaches counted). Isolated-liq proxy: adverse
  excursion from last execution > 30% force-closes. Delists exit at the
  last close. B5 stops trigger on hourly closes. SPOT:* keys use spot
  bars/fees, earn no funding, never liquidate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from cryptobot.risk.rounding import floor_to_step

PERIODS = 365
FALLBACK_SIGMA_D = 0.05
FALLBACK_ADV = 1e7


@dataclass
class CostModel:
    taker_bps: float = 7.5
    spot_taker_bps: float = 15.0
    spread_bps: float = 1.0
    slip_floor_bps: float = 1.0
    slip_k: float = 0.5
    adverse_mult: float = 1.0


@dataclass
class SimConfig:
    initial_equity: float = 1000.0
    min_notional: float = 6.0
    qty_step: float = 0.001
    gross_cap: float = 2.0
    liq_adverse: float = 0.30


@dataclass
class BacktestResult:
    equity: pd.Series
    final_equity: float
    total_costs: float
    costs: dict[str, float]
    turnover_oneway: float
    sharpe: float
    max_dd: float
    final_positions: dict[str, float]
    drops: int = 0
    gross_breaches: int = 0
    max_gross: float = 0.0
    flags: list[str] = field(default_factory=list)


def _is_spot(key: str) -> bool:
    return key.startswith("SPOT:")


def _sym_of(key: str) -> str:
    return key[5:] if _is_spot(key) else key


def _slip_bps(notional: float, sigma_d: float, adv: float,
              costs: CostModel) -> float:
    impact = costs.slip_k * sigma_d * 10000.0 * np.sqrt(
        max(notional, 0.0) / max(adv, 1.0))
    return max(costs.slip_floor_bps, float(impact))


def _side_cost_bps(notional: float, sigma_d: float, adv: float,
                   taker_bps: float, costs: CostModel) -> float:
    return (taker_bps + costs.spread_bps
            + _slip_bps(notional, sigma_d, adv, costs)) * costs.adverse_mult


def _trail_stats(frames: dict[str, pd.DataFrame], sym: str,
                 d: pd.Timestamp, window: int = 30):
    df = frames.get(sym)
    if df is None:
        return FALLBACK_SIGMA_D, FALLBACK_ADV
    past = df[df["open_time"] < d].tail(window)
    if len(past) < 10:
        return FALLBACK_SIGMA_D, float(
            past["quote_volume"].mean()) if len(past) else FALLBACK_ADV
    rets = np.log(past["close"].astype(float)).diff().dropna()
    sd = float(rets.std(ddof=1)) if len(rets) >= 2 else FALLBACK_SIGMA_D
    adv = float(past["quote_volume"].mean())
    return (sd if sd > 0 else FALLBACK_SIGMA_D,
            adv if adv > 0 else FALLBACK_ADV)


def _bar_on(frames: dict[str, pd.DataFrame], sym: str,
            d: pd.Timestamp) -> dict | None:
    df = frames.get(sym)
    if df is None:
        return None
    hit = df[df["open_time"] == d]
    if hit.empty:
        return None
    return hit.iloc[0].to_dict()


def _last_bar_before(frames: dict[str, pd.DataFrame], sym: str,
                     d: pd.Timestamp) -> dict | None:
    df = frames.get(sym)
    if df is None:
        return None
    past = df[df["open_time"] < d]
    if past.empty:
        return None
    return past.iloc[-1].to_dict()


def _settle(frames_f: dict[str, pd.DataFrame], sym: str, ts: pd.Timestamp):
    df = frames_f.get(sym)
    if df is None:
        return []
    return [float(r) for r in
            df[df["calc_time"] == ts]["last_funding_rate"].tolist()]


def _settle_window(frames_f: dict[str, pd.DataFrame], sym: str, lo, hi):
    df = frames_f.get(sym)
    if df is None:
        return []
    m = df[(df["calc_time"] > lo) & (df["calc_time"] < hi)]
    return [float(r) for r in m["last_funding_rate"].tolist()]


class _Book:
    """Shared position/cash ledger used by both engines."""

    def __init__(self, equity: float) -> None:
        self.cash = float(equity)
        self.qty: dict[str, float] = {}
        self.entry: dict[str, float] = {}
        self.costs = {"fees": 0.0, "spread": 0.0, "slip": 0.0,
                      "funding": 0.0}
        self.traded = 0.0
        self.drops = 0
        self.gross_breaches = 0
        self.max_gross = 0.0
        self.flags: list[str] = []

    def trade(self, key: str, new_qty: float, px: float, sigma_d: float,
              adv: float, costs: CostModel) -> None:
        old = self.qty.get(key, 0.0)
        delta = new_qty - old
        if delta == 0.0:
            return
        notional = abs(delta) * px
        taker = costs.spot_taker_bps if _is_spot(key) else costs.taker_bps
        fee = notional * taker / 1e4 * costs.adverse_mult
        spr = notional * costs.spread_bps / 1e4 * costs.adverse_mult
        slp = notional * _slip_bps(notional, sigma_d, adv, costs) / 1e4 \
            * costs.adverse_mult
        self.costs["fees"] += fee
        self.costs["spread"] += spr
        self.costs["slip"] += slp
        self.cash += -delta * px - (fee + spr + slp)
        self.traded += notional
        if new_qty == 0.0:
            self.qty.pop(key, None)
            self.entry.pop(key, None)
        else:
            self.qty[key] = new_qty
            self.entry[key] = px

    def fund(self, key: str, mark: float, rate: float) -> None:
        q = self.qty.get(key, 0.0)
        if q == 0.0:
            return
        pnl = -q * mark * rate
        self.cash += pnl
        self.costs["funding"] += -pnl

    def equity(self, marks: dict[str, float]) -> float:
        return self.cash + sum(
            q * marks.get(k, 0.0) for k, q in self.qty.items())


def _desired_quantities(desired: dict[str, float], equity: float,
                        opens: dict[str, float], book: _Book,
                        cfg: SimConfig) -> dict[str, float]:
    notionals = {k: v * equity for k, v in desired.items()}
    gross = sum(abs(v) for v in notionals.values()) / max(equity, 1e-12)
    if gross > cfg.gross_cap and gross > 0:
        f = cfg.gross_cap / gross
        notionals = {k: v * f for k, v in notionals.items()}
        book.gross_breaches += 1
    out: dict[str, float] = {}
    for key, notion in notionals.items():
        if key not in opens:
            if notion != 0.0:
                book.drops += 1
            continue
        if abs(notion) < cfg.min_notional:
            if notion != 0.0:
                book.drops += 1
            out[key] = 0.0
            continue
        raw = notion / opens[key]
        floored = float(np.sign(raw) * floor_to_step(abs(raw), cfg.qty_step)) \
            if raw != 0 else 0.0
        if floored == 0.0:
            book.drops += 1
        out[key] = floored
    return out


def _finish(book: _Book, idx: list, equity_vals: list,
            cfg: SimConfig) -> BacktestResult:
    eq = pd.Series(equity_vals, index=pd.DatetimeIndex(idx))
    rets = eq.pct_change().dropna()
    sd = float(rets.std(ddof=1)) if len(rets) >= 2 else 0.0
    sharpe = (float(rets.mean()) / sd * np.sqrt(PERIODS)) if sd > 0 else 0.0
    dd = float((eq / eq.cummax() - 1.0).min()) if len(eq) else 0.0
    years = max(len(eq) / 365.0, 1 / 365.0)
    avg_eq = float(eq.mean()) if len(eq) else cfg.initial_equity
    turnover = book.traded / max(avg_eq, 1e-12) / years
    flags = list(book.flags)
    if sharpe > 3.0 and "leak-investigate" not in flags:
        flags.append("leak-investigate")
    total = sum(book.costs.values())
    return BacktestResult(
        equity=eq, final_equity=float(eq.iloc[-1]) if len(eq) else cfg.initial_equity,
        total_costs=total, costs=dict(book.costs), turnover_oneway=turnover,
        sharpe=sharpe, max_dd=dd,
        final_positions={k: v for k, v in book.qty.items() if v != 0.0},
        drops=book.drops, gross_breaches=book.gross_breaches,
        max_gross=book.max_gross, flags=flags)


def _stop_touch(hourly: dict[str, pd.DataFrame], sym: str, d: pd.Timestamp,
                nxt: pd.Timestamp, side: int, stop: float):
    """First hourly close beyond the stop inside [d, nxt), else None."""
    df = hourly.get(sym)
    if df is None:
        return None
    win = df[(df["open_time"] >= d) & (df["open_time"] < nxt)]
    for _, row in win.iterrows():
        c = float(row["close"])
        if (side > 0 and c <= stop) or (side < 0 and c >= stop):
            return c
    return None


def simulate_vectorized(targets: dict, daily: dict, funding: dict, *,
                        costs: CostModel | None = None,
                        config: SimConfig | None = None,
                        spot: dict | None = None,
                        hourly: dict | None = None,
                        stops: dict | None = None) -> BacktestResult:
    costs, config = costs or CostModel(), config or SimConfig()
    spot, hourly, stops = spot or {}, hourly or {}, stops or {}
    frames = dict(daily)
    dates = sorted({t for df in daily.values() for t in df["open_time"]})
    book = _Book(config.initial_equity)
    idx: list = []
    vals: list = []
    marks: dict[str, float] = {}
    for n, d in enumerate(dates):
        nxt = dates[n + 1] if n + 1 < len(dates) else d + pd.Timedelta(days=1)
        # 1. overnight funding at 00:00 on pre-trade positions.
        for key in list(book.qty):
            if _is_spot(key):
                continue
            for rate in _settle(funding, _sym_of(key), d):
                book.fund(key, marks.get(key, 0.0) or _open_px(
                    frames, spot, key, d), rate)
        # 2. rebalance at open.
        if d in targets:
            opens = _opens_on(frames, spot, targets[d], d)
            want = _desired_quantities(targets[d], vals[-1] if vals else
                                       config.initial_equity, opens, book,
                                       config)
            for key, q in want.items():
                if key not in opens:
                    continue
                sd, adv = _trail_stats(
                    spot if _is_spot(key) else frames, _sym_of(key), d)
                book.trade(key, q, opens[key], sd, adv, costs)
        # 3. intraday funding 08:00/16:00 on post-trade positions.
        for key in list(book.qty):
            if _is_spot(key):
                continue
            for rate in _settle_window(funding, _sym_of(key), d, nxt):
                book.fund(key, _open_px(frames, spot, key, d), rate)
        # 4. B5 stops on hourly closes.
        for key in list(book.qty):
            if _is_spot(key):
                continue
            rule = stops.get(_sym_of(key))
            if not rule or d > rule.get("expiry", d):
                continue
            side = 1 if book.qty[key] > 0 else -1
            hit = _stop_touch(hourly, _sym_of(key), d, nxt, side,
                              rule["stop"])
            if hit is not None:
                sd, adv = _trail_stats(frames, _sym_of(key), d)
                book.trade(key, 0.0, hit, sd, adv, costs)
                book.flags.append(f"stop:{_sym_of(key)}")
        # 5. liq proxy + 6. delist + 7. mark.
        _supervise_and_mark(book, frames, spot, dates, n, d, costs, config,
                            marks)
        idx.append(d)
        vals.append(book.equity(marks))
    return _finish(book, idx, vals, config)


def _open_px(frames, spot, key: str, d: pd.Timestamp) -> float:
    src = spot if _is_spot(key) else frames
    bar = _bar_on(src, _sym_of(key), d)
    if bar is not None:
        return float(bar["open"])
    last = _last_bar_before(src, _sym_of(key), d)
    return float(last["close"]) if last is not None else 0.0


def _opens_on(frames, spot, want: dict, d: pd.Timestamp) -> dict[str, float]:
    out = {}
    for key in want:
        src = spot if _is_spot(key) else frames
        bar = _bar_on(src, _sym_of(key), d)
        if bar is not None:
            out[key] = float(bar["open"])
    return out


def _supervise_and_mark(book: _Book, frames, spot, dates, n: int,
                        d: pd.Timestamp, costs: CostModel, cfg: SimConfig,
                        marks: dict[str, float]) -> None:
    for key in list(book.qty):
        src = spot if _is_spot(key) else frames
        bar = _bar_on(src, _sym_of(key), d)
        if bar is None:
            df = src.get(_sym_of(key))
            last_date = df["open_time"].max() if df is not None and len(
                df) else None
            if last_date is not None and d > last_date:
                px = float(df[df["open_time"] == last_date].iloc[0]["close"])
                sd, adv = _trail_stats(src, _sym_of(key), d)
                book.trade(key, 0.0, px, sd, adv, costs)
                book.flags.append(f"delisted-exit:{_sym_of(key)}")
            continue
        marks[key] = float(bar["close"])
        if _is_spot(key):
            continue
        entry = book.entry.get(key)
        if entry:
            side = 1 if book.qty[key] > 0 else -1
            adverse = side * (entry - marks[key]) / entry
            if adverse > cfg.liq_adverse:
                sd, adv = _trail_stats(src, _sym_of(key), d)
                book.trade(key, 0.0, marks[key], sd, adv, costs)
                book.flags.append(f"liquidation:{_sym_of(key)}")
    eq = book.equity(marks)
    gross = sum(abs(q) * marks.get(k, 0.0)
                for k, q in book.qty.items()) / max(eq, 1e-12)
    book.max_gross = max(book.max_gross, gross)


@dataclass
class _Event:
    ts: pd.Timestamp
    kind: str  # settle-overnight | trade | settle-day | stop | mark
    payload: Any = None


def simulate_event(targets: dict, daily: dict, funding: dict, *,
                   costs: CostModel | None = None,
                   config: SimConfig | None = None,
                   spot: dict | None = None,
                   hourly: dict | None = None,
                   stops: dict | None = None) -> BacktestResult:
    costs, config = costs or CostModel(), config or SimConfig()
    spot, hourly, stops = spot or {}, hourly or {}, stops or {}
    frames = dict(daily)
    dates = sorted({t for df in daily.values() for t in df["open_time"]})
    book = _Book(config.initial_equity)
    idx: list = []
    vals: list = []
    marks: dict[str, float] = {}
    for n, d in enumerate(dates):
        nxt = dates[n + 1] if n + 1 < len(dates) else d + pd.Timedelta(days=1)
        queue = [_Event(d, "settle-overnight")]
        if d in targets:
            queue.append(_Event(d, "trade", targets[d]))
        queue.append(_Event(d, "settle-day"))
        queue.append(_Event(d, "stop"))
        queue.append(_Event(d, "mark"))
        for ev in queue:
            if ev.kind == "settle-overnight":
                for key in list(book.qty):
                    if _is_spot(key):
                        continue
                    for rate in _settle(funding, _sym_of(key), d):
                        book.fund(key, marks.get(key, 0.0) or _open_px(
                            frames, spot, key, d), rate)
            elif ev.kind == "trade":
                opens = _opens_on(frames, spot, ev.payload, d)
                want = _desired_quantities(
                    ev.payload, vals[-1] if vals else config.initial_equity,
                    opens, book, config)
                for key, q in want.items():
                    if key not in opens:
                        continue
                    sd, adv = _trail_stats(
                        spot if _is_spot(key) else frames, _sym_of(key), d)
                    book.trade(key, q, opens[key], sd, adv, costs)
            elif ev.kind == "settle-day":
                for key in list(book.qty):
                    if _is_spot(key):
                        continue
                    for rate in _settle_window(funding, _sym_of(key), d, nxt):
                        book.fund(key, _open_px(frames, spot, key, d), rate)
            elif ev.kind == "stop":
                for key in list(book.qty):
                    if _is_spot(key):
                        continue
                    rule = stops.get(_sym_of(key))
                    if not rule or d > rule.get("expiry", d):
                        continue
                    side = 1 if book.qty[key] > 0 else -1
                    hit = _stop_touch(hourly, _sym_of(key), d, nxt, side,
                                      rule["stop"])
                    if hit is not None:
                        sd, adv = _trail_stats(frames, _sym_of(key), d)
                        book.trade(key, 0.0, hit, sd, adv, costs)
                        book.flags.append(f"stop:{_sym_of(key)}")
            elif ev.kind == "mark":
                _supervise_and_mark(book, frames, spot, dates, n, d, costs,
                                    config, marks)
        idx.append(d)
        vals.append(book.equity(marks))
    return _finish(book, idx, vals, config)


def shift_targets(targets: dict, dates, k: int) -> dict:
    dates = list(dates)
    pos = {d: i for i, d in enumerate(dates)}
    out: dict = {}
    for d, w in targets.items():
        j = pos[d] + k
        if 0 <= j < len(dates):
            out[dates[j]] = w
    return out


def shuffle_labels(daily: dict[str, pd.DataFrame], seed: int = 99):
    rng = np.random.default_rng(seed)
    out = {}
    for sym, df in daily.items():
        df = df.sort_values("open_time").reset_index(drop=True)
        lr = np.log(df["close"].astype(float)).diff().iloc[1:].to_numpy(
            copy=True)
        rng.shuffle(lr)
        closes = [float(df["close"].iloc[0])]
        for r in lr:
            closes.append(closes[-1] * float(np.exp(r)))
        closes = np.array(closes)
        opens = np.concatenate([[float(df["open"].iloc[0])], closes[:-1]])
        out[sym] = pd.DataFrame({
            "open_time": df["open_time"], "open": opens,
            "high": np.maximum(opens, closes),
            "low": np.minimum(opens, closes), "close": closes,
            "quote_volume": df["quote_volume"].to_numpy()})
    return out


def capital_sweep(targets: dict, daily: dict, funding: dict, *,
                  equities=(120.0, 1000.0, 10000.0),
                  costs: CostModel | None = None, **kw) -> dict:
    out = {}
    for eq in equities:
        r = simulate_vectorized(targets, daily, funding, costs=costs,
                                config=SimConfig(initial_equity=float(eq),
                                                 **kw))
        out[float(eq)] = {"final_equity": r.final_equity,
                          "drops": r.drops, "turnover_oneway": r.turnover_oneway,
                          "feasible": r.drops == 0}
    return out


__all__ = ["CostModel", "SimConfig", "BacktestResult", "PERIODS",
           "simulate_vectorized", "simulate_event", "shift_targets",
           "shuffle_labels", "capital_sweep"]
