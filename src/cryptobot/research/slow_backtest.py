"""E4: slow-strategy portfolio backtester (1d bars + funding + stops).

Two harnesses, one spec (differential-tested):
- simulate_vectorized: pandas/numpy matrix loop over dates + _Book ledger.
- simulate_event: explicit event queue + independent _EventBook ledger
  (own cash/qty/cost accumulation; shared only: data accessors, atomic
  bps math, venue rounding). Cost FORMULAS are pinned by hand-computed
  tests; the differential test pins plumbing/logic agreement.

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
    panel = getattr(frames, "index", None)
    if panel is not None and hasattr(frames, "spot"):
        return panel.trail_of(sym, d, spot=bool(frames.spot))
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


class MarketIndex:
    """O(1) bar and funding lookups. Built once per simulation.

    Trail stats at date d use bars with open_time < d (same as the
    dataframe filter). Funding windows match _settle / _settle_window.
    """

    def __init__(self, daily: dict, spot: dict, funding: dict) -> None:
        self.daily_bar: dict[tuple, tuple[float, float]] = {}
        self.spot_bar: dict[tuple, tuple[float, float]] = {}
        self.trail: dict[tuple, tuple[float, float]] = {}
        self.spot_trail: dict[tuple, tuple[float, float]] = {}
        self.last_date: dict[str, pd.Timestamp] = {}
        self.last_close: dict[str, float] = {}
        self.spot_last_date: dict[str, pd.Timestamp] = {}
        self.spot_last_close: dict[str, float] = {}
        self.daily_times: dict[str, list] = {}
        self.daily_closes: dict[str, np.ndarray] = {}
        self.spot_times: dict[str, list] = {}
        self.spot_closes: dict[str, np.ndarray] = {}
        self.fund_exact: dict[tuple, list[float]] = {}
        self.fund_window: dict[tuple, list[float]] = {}
        self._build_bars(daily, self.daily_bar, self.trail,
                         self.last_date, self.last_close,
                         self.daily_times, self.daily_closes)
        self._build_bars(spot, self.spot_bar, self.spot_trail,
                         self.spot_last_date, self.spot_last_close,
                         self.spot_times, self.spot_closes)
        dates = sorted({t for df in daily.values() for t in df["open_time"]})
        self.dates = dates
        self._build_funding(funding, dates)

    @staticmethod
    def _build_bars(frames, bars, trail, last_date, last_close,
                    times_out, closes_out) -> None:
        for sym, df in frames.items():
            df = df.sort_values("open_time").drop_duplicates("open_time")
            opens = df["open"].to_numpy(dtype=float)
            closes = df["close"].to_numpy(dtype=float)
            highs = (df["high"].to_numpy(dtype=float)
                     if "high" in df.columns else closes)
            lows = (df["low"].to_numpy(dtype=float)
                    if "low" in df.columns else closes)
            vols = df["quote_volume"].to_numpy(dtype=float)
            times = list(df["open_time"])
            logret = np.zeros(len(closes))
            if len(closes) > 1:
                logret[1:] = np.diff(np.log(np.maximum(closes, 1e-12)))
            # Match _trail_stats: last `window` bars with open_time < d,
            # std of log-diff inside that slice, fallback if fewer than 10.
            window = 30
            for i, ts in enumerate(times):
                bars[(sym, ts)] = (float(opens[i]), float(highs[i]),
                                   float(lows[i]), float(closes[i]))
                p0 = max(0, i - window)
                n_past = i - p0
                adv_seg = vols[p0:i]
                adv = float(adv_seg.mean()) if adv_seg.size else FALLBACK_ADV
                if n_past < 10 or not np.isfinite(adv) or adv <= 0:
                    sd = FALLBACK_SIGMA_D
                    if not np.isfinite(adv) or adv <= 0:
                        adv = FALLBACK_ADV
                else:
                    seg = logret[p0 + 1:i]
                    sd = float(seg.std(ddof=1)) if seg.size >= 2 else FALLBACK_SIGMA_D
                    if not np.isfinite(sd) or sd <= 0:
                        sd = FALLBACK_SIGMA_D
                trail[(sym, ts)] = (sd, adv)
            if times:
                last_date[sym] = times[-1]
                last_close[sym] = float(closes[-1])
                times_out[sym] = times
                closes_out[sym] = closes

    def _build_funding(self, funding: dict, dates: list) -> None:
        if not dates:
            return
        nxt = {dates[i]: dates[i + 1] if i + 1 < len(dates)
               else dates[i] + pd.Timedelta(days=1)
               for i in range(len(dates))}
        for sym, df in funding.items():
            if df is None or len(df) == 0:
                continue
            ts = pd.DatetimeIndex(pd.to_datetime(df["calc_time"], utc=True))
            ts = ts.as_unit("ns")
            rates = df["last_funding_rate"].to_numpy(dtype=float)
            order = np.argsort(ts.asi8)
            ts_ns = ts.asi8[order]
            rates = rates[order]
            j = 0
            n = len(ts_ns)
            for d in dates:
                target = pd.Timestamp(d).value
                hi = pd.Timestamp(nxt[d]).value
                while j < n and ts_ns[j] < target:
                    j += 1
                k = j
                exact: list[float] = []
                while k < n and ts_ns[k] == target:
                    exact.append(float(rates[k]))
                    k += 1
                if exact:
                    self.fund_exact[(sym, d)] = exact
                w = k
                window: list[float] = []
                while w < n and ts_ns[w] < hi:
                    window.append(float(rates[w]))
                    w += 1
                if window:
                    self.fund_window[(sym, d)] = window
                j = k

    def bar(self, sym: str, d: pd.Timestamp, *, spot: bool = False):
        src = self.spot_bar if spot else self.daily_bar
        hit = src.get((sym, d))
        if hit is None:
            return None
        return {"open": hit[0], "high": hit[1], "low": hit[2], "close": hit[3]}

    def prev_close(self, sym: str, d: pd.Timestamp, *, spot: bool = False):
        import bisect
        times = (self.spot_times if spot else self.daily_times).get(sym)
        closes = (self.spot_closes if spot else self.daily_closes).get(sym)
        if not times:
            return None
        i = bisect.bisect_left(times, d)
        if i <= 0:
            return None
        return float(closes[i - 1])

    def trail_of(self, sym: str, d: pd.Timestamp, *, spot: bool = False):
        src = self.spot_trail if spot else self.trail
        return src.get((sym, d), (FALLBACK_SIGMA_D, FALLBACK_ADV))


class _Panel:
    """Perp or spot view of one MarketIndex."""

    def __init__(self, index: MarketIndex, *, spot: bool) -> None:
        self.index = index
        self.spot = spot


def _bar_on(frames, sym: str, d: pd.Timestamp) -> dict | None:
    panel = getattr(frames, "index", None)
    if panel is not None and hasattr(frames, "spot"):
        return panel.bar(sym, d, spot=bool(frames.spot))
    if isinstance(frames, MarketIndex):
        return frames.bar(sym, d)
    df = frames.get(sym)
    if df is None:
        return None
    hit = df[df["open_time"] == d]
    if hit.empty:
        return None
    return hit.iloc[0].to_dict()


def _last_bar_before(frames, sym: str, d: pd.Timestamp) -> dict | None:
    panel = getattr(frames, "index", None)
    if panel is not None and hasattr(frames, "spot"):
        px = panel.prev_close(sym, d, spot=bool(frames.spot))
        return {"close": px, "open": px} if px is not None else None
    df = frames.get(sym)
    if df is None:
        return None
    past = df[df["open_time"] < d]
    if past.empty:
        return None
    return past.iloc[-1].to_dict()


def _settle(frames_f, sym: str, ts: pd.Timestamp):
    if isinstance(frames_f, MarketIndex):
        return list(frames_f.fund_exact.get((sym, ts), ()))
    df = frames_f.get(sym)
    if df is None:
        return []
    return [float(r) for r in
            df[df["calc_time"] == ts]["last_funding_rate"].tolist()]


def _settle_window(frames_f, sym: str, lo, hi):
    if isinstance(frames_f, MarketIndex):
        # Precomputed on the same next-bar boundary the simulator uses.
        return list(frames_f.fund_window.get((sym, lo), ()))
    df = frames_f.get(sym)
    if df is None:
        return []
    m = df[(df["calc_time"] > lo) & (df["calc_time"] < hi)]
    return [float(r) for r in m["last_funding_rate"].tolist()]


def _delist_px(src, sym: str, d: pd.Timestamp) -> float | None:
    panel = getattr(src, "index", None)
    if panel is not None and hasattr(src, "spot"):
        dates = panel.spot_last_date if src.spot else panel.last_date
        closes = panel.spot_last_close if src.spot else panel.last_close
        last = dates.get(sym)
        if last is not None and d > last:
            return float(closes[sym])
        return None
    df = src.get(sym) if hasattr(src, "get") else None
    if df is not None and len(df) and d > df["open_time"].max():
        last = df["open_time"].max()
        return float(df[df["open_time"] == last].iloc[0]["close"])
    return None


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
                        stops: dict | None = None,
                        stops_by_day: dict | None = None) -> BacktestResult:
    costs, config = costs or CostModel(), config or SimConfig()
    hourly, stops = hourly or {}, stops or {}
    stops_by_day = stops_by_day or {}
    ix = MarketIndex(daily, spot or {}, funding)
    frames = _Panel(ix, spot=False)
    spot = _Panel(ix, spot=True)
    funding = ix
    dates = ix.dates
    book = _Book(config.initial_equity)
    idx: list = []
    vals: list = []
    marks: dict[str, float] = {}
    for n, d in enumerate(dates):
        nxt = dates[n + 1] if n + 1 < len(dates) else d + pd.Timedelta(days=1)
        # 1. overnight funding at 00:00 on pre-trade positions,
        # marked at the 00:00 open by definition.
        for key in list(book.qty):
            if _is_spot(key):
                continue
            for rate in _settle(funding, _sym_of(key), d):
                book.fund(key, _open_px(frames, spot, key, d), rate)
        # 2. rebalance at open. Held keys missing from targets[d] are
        # flattened (rotation strategies must not accumulate stale
        # buy-and-hold); dates absent from targets hold everything.
        if d in targets:
            want_d = dict(targets[d])
            for key in book.qty:
                want_d.setdefault(key, 0.0)
            opens = _opens_on(frames, spot, want_d, d)
            want = _desired_quantities(want_d, vals[-1] if vals else
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
            rule = (stops_by_day.get(d) or {}).get(_sym_of(key)) \
                or stops.get(_sym_of(key))
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
            px = _delist_px(src, _sym_of(key), d)
            if px is not None:
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
            # Trigger on the adverse wick (conservative: intraday
            # excursions liquidate even if the close recovers); the
            # forced exit prints at the close (disclosed simplification).
            wick = float(bar["low"]) if side > 0 else float(bar["high"])
            adverse = side * (entry - wick) / entry
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


class _EventBook:
    """Independent ledger for the event engine.

    Same SPEC as _Book, separate implementation: own cash/qty/cost
    accumulation, rescale, floor, funding, liq/delist supervision.
    Shared atoms only: _slip_bps (formula pinned by hand tests),
    floor_to_step (venue rounding), data accessors.
    """

    def __init__(self, equity: float) -> None:
        self.cash = float(equity)
        self.qty: dict[str, float] = {}
        self.entry: dict[str, float] = {}
        self.fee = 0.0
        self.spr = 0.0
        self.slp = 0.0
        self.fund = 0.0
        self.traded = 0.0
        self.drops = 0
        self.breaches = 0
        self.maxgross = 0.0
        self.flags: list[str] = []

    def execute(self, key: str, qty: float, px: float, sig: float, adv: float,
                costs: CostModel) -> None:
        delta = qty - self.qty.get(key, 0.0)
        if delta == 0.0:
            return
        notion = abs(delta) * px
        taker = costs.spot_taker_bps if _is_spot(key) else costs.taker_bps
        m = costs.adverse_mult
        self.fee += notion * taker / 1e4 * m
        self.spr += notion * costs.spread_bps / 1e4 * m
        self.slp += notion * _slip_bps(notion, sig, adv, costs) / 1e4 * m
        self.cash -= delta * px + (notion * taker / 1e4 * m
                                   + notion * costs.spread_bps / 1e4 * m
                                   + notion * _slip_bps(notion, sig, adv,
                                                        costs) / 1e4 * m)
        self.traded += notion
        if qty == 0.0:
            self.qty.pop(key, None)
            self.entry.pop(key, None)
        else:
            self.qty[key] = qty
            self.entry[key] = px

    def settle(self, key: str, mark: float, rate: float) -> None:
        q = self.qty.get(key, 0.0)
        if q == 0.0:
            return
        delta = -q * mark * rate
        self.cash += delta
        self.fund -= delta

    def size_targets(self, want: dict[str, float], equity: float,
                     opens: dict[str, float], cfg: SimConfig) -> dict[str, float]:
        notion = {k: v * equity for k, v in want.items()}
        gross = sum(abs(v) for v in notion.values()) / max(equity, 1e-12)
        if gross > cfg.gross_cap and gross > 0:
            f = cfg.gross_cap / gross
            notion = {k: v * f for k, v in notion.items()}
            self.breaches += 1
        out: dict[str, float] = {}
        for key, amt in notion.items():
            if key not in opens:
                if amt != 0.0:
                    self.drops += 1
                continue
            if abs(amt) < cfg.min_notional:
                if amt != 0.0:
                    self.drops += 1
                out[key] = 0.0
                continue
            raw = amt / opens[key]
            if raw == 0.0:
                out[key] = 0.0
                continue
            floored = float(np.sign(raw) * floor_to_step(abs(raw),
                                                         cfg.qty_step))
            if floored == 0.0:
                self.drops += 1
            out[key] = floored
        return out

    def supervise(self, frames, spot, d: pd.Timestamp, costs: CostModel,
                  cfg: SimConfig, marks: dict[str, float]) -> None:
        for key in list(self.qty):
            src = spot if _is_spot(key) else frames
            bar = _bar_on(src, _sym_of(key), d)
            if bar is None:
                px = _delist_px(src, _sym_of(key), d)
                if px is not None:
                    sig, adv = _trail_stats(src, _sym_of(key), d)
                    self.execute(key, 0.0, px, sig, adv, costs)
                    self.flags.append(f"delisted-exit:{_sym_of(key)}")
                continue
            marks[key] = float(bar["close"])
            if _is_spot(key):
                continue
            entry = self.entry.get(key)
            if entry:
                side = 1 if self.qty[key] > 0 else -1
                wick = float(bar["low"]) if side > 0 else float(bar["high"])
                adverse = side * (entry - wick) / entry
                if adverse > cfg.liq_adverse:
                    sig, adv = _trail_stats(src, _sym_of(key), d)
                    self.execute(key, 0.0, marks[key], sig, adv, costs)
                    self.flags.append(f"liquidation:{_sym_of(key)}")
        eq = self.cash + sum(
            q * marks.get(k, 0.0) for k, q in self.qty.items())
        gross = sum(abs(q) * marks.get(k, 0.0)
                    for k, q in self.qty.items()) / max(eq, 1e-12)
        self.maxgross = max(self.maxgross, gross)

    def to_result(self, idx, vals, cfg: SimConfig) -> BacktestResult:
        eq = pd.Series(vals, index=pd.DatetimeIndex(idx))
        rets = eq.pct_change().dropna()
        sd = float(rets.std(ddof=1)) if len(rets) >= 2 else 0.0
        sr = float(rets.mean() / sd * np.sqrt(PERIODS)) \
            if sd > 0 and sd >= 1e-9 else 0.0
        dd = float((1.0 - eq / eq.cummax()).max()) if len(eq) else 0.0
        years = max(len(eq) / 365.0, 1 / 365.0)
        avg = float(eq.mean()) if len(eq) else cfg.initial_equity
        flags = list(self.flags)
        if sr > 3.0 and "leak-investigate" not in flags:
            flags.append("leak-investigate")
        costs = {"fees": self.fee, "spread": self.spr, "slip": self.slp,
                 "funding": self.fund}
        return BacktestResult(
            equity=eq, final_equity=float(eq.iloc[-1]) if len(eq)
            else cfg.initial_equity, total_costs=sum(costs.values()),
            costs=costs, turnover_oneway=self.traded / max(avg, 1e-12)
            / years, sharpe=sr, max_dd=dd,
            final_positions={k: v for k, v in self.qty.items() if v != 0.0},
            drops=self.drops, gross_breaches=self.breaches,
            max_gross=self.maxgross, flags=flags)


def simulate_event(targets: dict, daily: dict, funding: dict, *,
                   costs: CostModel | None = None,
                   config: SimConfig | None = None,
                   spot: dict | None = None,
                   hourly: dict | None = None,
                   stops: dict | None = None,
                   stops_by_day: dict | None = None) -> BacktestResult:
    costs, config = costs or CostModel(), config or SimConfig()
    hourly, stops = hourly or {}, stops or {}
    stops_by_day = stops_by_day or {}
    ix = MarketIndex(daily, spot or {}, funding)
    frames = _Panel(ix, spot=False)
    spot = _Panel(ix, spot=True)
    funding = ix
    dates = ix.dates
    book = _EventBook(config.initial_equity)
    idx: list = []
    vals: list = []
    marks: dict[str, float] = {}
    for n, d in enumerate(dates):
        nxt = dates[n + 1] if n + 1 < len(dates) else d + pd.Timedelta(days=1)
        queue = [_Event(d, "settle-overnight")]
        if d in targets:
            merged = dict(targets[d])
            for key in book.qty:
                merged.setdefault(key, 0.0)
            queue.append(_Event(d, "trade", merged))
        queue.append(_Event(d, "settle-day"))
        queue.append(_Event(d, "stop"))
        queue.append(_Event(d, "mark"))
        for ev in queue:
            if ev.kind == "settle-overnight":
                for key in list(book.qty):
                    if _is_spot(key):
                        continue
                    for rate in _settle(funding, _sym_of(key), d):
                        book.settle(key, _open_px(frames, spot, key, d),
                                    rate)
            elif ev.kind == "trade":
                opens = _opens_on(frames, spot, ev.payload, d)
                want = book.size_targets(
                    ev.payload, vals[-1] if vals else config.initial_equity,
                    opens, config)
                for key, q in want.items():
                    if key not in opens:
                        continue
                    sd, adv = _trail_stats(
                        spot if _is_spot(key) else frames, _sym_of(key), d)
                    book.execute(key, q, opens[key], sd, adv, costs)
            elif ev.kind == "settle-day":
                for key in list(book.qty):
                    if _is_spot(key):
                        continue
                    for rate in _settle_window(funding, _sym_of(key), d, nxt):
                        book.settle(key, _open_px(frames, spot, key, d),
                                    rate)
            elif ev.kind == "stop":
                for key in list(book.qty):
                    if _is_spot(key):
                        continue
                    rule = (stops_by_day.get(d) or {}).get(_sym_of(key)) \
                        or stops.get(_sym_of(key))
                    if not rule or d > rule.get("expiry", d):
                        continue
                    side = 1 if book.qty[key] > 0 else -1
                    hit = _stop_touch(hourly, _sym_of(key), d, nxt, side,
                                      rule["stop"])
                    if hit is not None:
                        sd, adv = _trail_stats(frames, _sym_of(key), d)
                        book.execute(key, 0.0, hit, sd, adv, costs)
                        book.flags.append(f"stop:{_sym_of(key)}")
            elif ev.kind == "mark":
                book.supervise(frames, spot, d, costs, config, marks)
        idx.append(d)
        vals.append(book.cash + sum(
            q * marks.get(k, 0.0) for k, q in book.qty.items()))
    return book.to_result(idx, vals, config)


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


def check_turnover(result: BacktestResult, budget_oneway: float) -> dict:
    """Promotion-layer gate: realized one-way turnover within budget."""
    ok = result.turnover_oneway <= budget_oneway
    return {"ok": ok, "turnover_oneway": result.turnover_oneway,
            "budget": budget_oneway,
            "reason": "" if ok else
            f"turnover {result.turnover_oneway:.2f}x > {budget_oneway:.2f}x"}


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
           "shuffle_labels", "capital_sweep", "check_turnover"]
