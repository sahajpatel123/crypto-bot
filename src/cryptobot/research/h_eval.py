"""Preregistered H1/H2/H3 dev evaluation (T5.4 protocol, bar level).

Dev data only (datasets/benchmark_30d, already inspected). Rules are
exactly as preregistered in research/prereg/; this module never tunes.
H1 needs top-5 book imbalance, but dev data has no quote/book channel
(pilot manifest caveat), so H1 is honestly UNEVALUABLE here, never
proxied. Verdicts come from verdict.evaluate_trades (family_size=3).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptobot.research.cost_model_v2 import CostModel
from cryptobot.research.verdict import evaluate_trades

DD_BUDGET_BPS = 1000.0  # assumption: full-notional sizing, 10% equity DD


@dataclass(frozen=True)
class Bar:
    ts_ms: int
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class Trade:
    day: str
    gross_bps: float
    net_bps: float
    adverse_bps: float
    stop_bps: float | None = None  # stop distance; sizes equity impact


def _day_of(ts_ms: int) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp(ts_ms / 1000, tz=dt.UTC).strftime("%Y-%m-%d")


def hourly_bars(symbol: str, cache_root: str | Path = "datasets/cache") -> list[Bar]:
    """Aggregate 1m mark OHLC parquets into causal hourly bars."""
    import pyarrow.parquet as pq
    root = Path(cache_root) / f"symbol={symbol}"
    bars: list[Bar] = []
    for part in sorted(root.glob("date=*/channel=markPrice/part.parquet")):
        table = pq.read_table(part, columns=["ts_ms", "open_px", "high_px", "low_px", "mark"])
        rows = table.to_pylist()
        by_hour: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            by_hour.setdefault(int(row["ts_ms"]) // 3_600_000, []).append(row)
        for hour in sorted(by_hour):
            mins = sorted(by_hour[hour], key=lambda r: int(r["ts_ms"]))
            bars.append(Bar(ts_ms=hour * 3_600_000, open=float(mins[0]["open_px"]),
                            high=max(float(r["high_px"]) for r in mins),
                            low=min(float(r["low_px"]) for r in mins),
                            close=float(mins[-1]["mark"])))
    return sorted(bars, key=lambda b: b.ts_ms)


def load_funding(symbol: str, cache_root: str | Path = "datasets/cache") -> list[tuple[int, float]]:
    import pyarrow.parquet as pq
    root = Path(cache_root) / f"symbol={symbol}" / "funding"
    out: list[tuple[int, float]] = []
    for part in sorted(root.glob("*.parquet")):
        for row in pq.read_table(part, columns=["ts_ms", "rate"]).to_pylist():
            out.append((int(row["ts_ms"]), float(row["rate"])))
    return sorted(set(out))


def _ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    k = 2.0 / (period + 1)
    cur = statistics.fmean(values[:period])
    out[period - 1] = cur
    for i in range(period, len(values)):
        cur = values[i] * k + cur * (1 - k)
        out[i] = cur
    return out


def _atr(bars: list[Bar], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(bars)
    trs: list[float] = []
    for i, bar in enumerate(bars):
        if i == 0:
            trs.append(bar.high - bar.low)
            continue
        prev = bars[i - 1].close
        trs.append(max(bar.high - bar.low, abs(bar.high - prev), abs(bar.low - prev)))
        if len(trs) >= period:
            out[i] = statistics.fmean(trs[-period:])
    return out


def _exit_bps(bars: list[Bar], start: int, direction: int, entry: float,
              stop_bps: float, target_bps: float, max_bars: int) -> tuple[float, int]:
    """Pessimistic intrabar exit: stop wins ties. Returns (gross_bps, bars_held)."""
    stop_px = entry * (1 - direction * stop_bps / 10000)
    target_px = entry * (1 + direction * target_bps / 10000)
    for j in range(start, min(len(bars), start + max_bars)):
        bar = bars[j]
        hit_stop = bar.low <= stop_px if direction > 0 else bar.high >= stop_px
        hit_tgt = bar.high >= target_px if direction > 0 else bar.low <= target_px
        if hit_stop:
            return -stop_bps, j - start + 1
        if hit_tgt:
            return target_bps, j - start + 1
    last = bars[min(len(bars), start + max_bars) - 1]
    return direction * (last.close / entry - 1) * 10000, max_bars


def _net(gross: float, maker: bool, model: CostModel) -> tuple[float, float]:
    return (gross - model.round_trip_bps(maker_entry=maker, stress=1.0),
            gross - model.round_trip_bps(maker_entry=maker, stress=2.0))


def h2_trades(bars: list[Bar], model: CostModel | None = None) -> list[Trade]:
    """H2: 1h EMA20/50 trend, ATR-pct>70 gate, 1.5x/3x ATR stop/target."""
    model = model or CostModel()
    closes = [b.close for b in bars]
    fast, slow, atr = _ema(closes, 20), _ema(closes, 50), _atr(bars)
    trades: list[Trade] = []
    i = 50
    while i < len(bars) - 1:
        if fast[i] is None or slow[i] is None or atr[i] is None:
            i += 1
            continue
        hist = [a for a in atr[: i + 1] if a is not None]
        gate = len(hist) >= 20 and atr[i] >= sorted(hist)[int(0.70 * (len(hist) - 1))]
        direction = 1 if fast[i] > slow[i] else (-1 if fast[i] < slow[i] else 0)
        if not gate or direction == 0:
            i += 1
            continue
        entry = bars[i + 1].open
        stop = 1.5 * atr[i] / entry * 10000
        target = 3.0 * atr[i] / entry * 10000
        gross, held = _exit_bps(bars, i + 1, direction, entry, stop, target, 24 * 7)
        net, adv = _net(gross, maker=False, model=model)
        trades.append(Trade(day=_day_of(bars[i + 1].ts_ms), gross_bps=gross,
                            net_bps=net, adverse_bps=adv, stop_bps=stop))
        i += 1 + held
    return trades


def h2_trades_fast(bars: list[Bar], model: CostModel | None = None) -> list[Trade]:
    """Exactly ``h2_trades`` (same rules, same output) in O(n log n).

    The ATR percentile gate keeps an incrementally sorted history
    instead of re-sorting it every bar, so multi-year series score in
    seconds. Equality with ``h2_trades`` is pinned by a unit test.
    """
    import bisect

    model = model or CostModel()
    closes = [b.close for b in bars]
    fast, slow, atr = _ema(closes, 20), _ema(closes, 50), _atr(bars)
    trades: list[Trade] = []
    hist: list[float] = []
    added = 0
    i = 50
    while i < len(bars) - 1:
        while added <= i:
            if atr[added] is not None:
                bisect.insort(hist, atr[added])
            added += 1
        if fast[i] is None or slow[i] is None or atr[i] is None:
            i += 1
            continue
        gate = len(hist) >= 20 and atr[i] >= hist[int(0.70 * (len(hist) - 1))]
        direction = 1 if fast[i] > slow[i] else (-1 if fast[i] < slow[i] else 0)
        if not gate or direction == 0:
            i += 1
            continue
        entry = bars[i + 1].open
        stop = 1.5 * atr[i] / entry * 10000
        target = 3.0 * atr[i] / entry * 10000
        gross, held = _exit_bps(bars, i + 1, direction, entry, stop, target, 24 * 7)
        net, adv = _net(gross, maker=False, model=model)
        trades.append(Trade(day=_day_of(bars[i + 1].ts_ms), gross_bps=gross,
                            net_bps=net, adverse_bps=adv, stop_bps=stop))
        i += 1 + held
    return trades


def h3_trades(bars: list[Bar], funding: list[tuple[int, float]],
              model: CostModel | None = None) -> list[Trade]:
    """H3: funding >90th pct (trailing 30d) -> fade crowd, hold 8h."""
    model = model or CostModel()
    close_at = {b.ts_ms: b.close for b in bars}
    times = sorted(close_at)
    trades: list[Trade] = []
    rates = [r for _, r in funding]
    for idx, (ts_ms, rate) in enumerate(funding):
        hist = rates[max(0, idx - 90):idx]
        if len(hist) < 30:
            continue
        hi = sorted(hist)[int(0.90 * (len(hist) - 1))]
        lo = sorted(hist)[int(0.10 * (len(hist) - 1))]
        direction = -1 if rate > hi else (1 if rate < lo else 0)
        if direction == 0:
            continue
        start = next((t for t in times if t >= ts_ms), None)
        if start is None:
            continue
        entry = close_at[start]
        window = [b for b in bars if start <= b.ts_ms < start + 8 * 3_600_000]
        if not window:
            continue
        gross, _ = _exit_bps(window, 0, direction, entry, 100.0, 200.0, len(window))
        funding_bps = -direction * rate * 10000  # short collects when rate>0
        net, adv = _net(gross + funding_bps, maker=False, model=model)
        trades.append(Trade(day=_day_of(start), gross_bps=gross + funding_bps,
                            net_bps=net, adverse_bps=adv))
    return trades


def equity_bps(trades: list[Trade], risk_bps: float = 12.5,
               lev_cap: float = 3.0) -> list[float]:
    """Per-trade equity impact under repo sizing (0.125% risk/trade).

    Notional is sized so the stop loses ``risk_bps`` of equity, capped
    at ``lev_cap`` x equity. Trades without a stop count full-notional.
    """
    out: list[float] = []
    for trade in trades:
        factor = 1.0 if not trade.stop_bps else min(lev_cap, risk_bps / trade.stop_bps)
        out.append(trade.net_bps * factor)
    return out


def max_drawdown_bps(trades: list[Trade]) -> float:
    equity, peak, worst = 0.0, 0.0, 0.0
    for trade in trades:
        equity += trade.net_bps
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def verdict_for(name: str, trades: list[Trade]) -> dict[str, Any]:
    sized = equity_bps(trades)
    sized_dd = max_drawdown_bps([Trade(day=t.day, gross_bps=v, net_bps=v,
                                       adverse_bps=v)
                                 for t, v in zip(trades, sized, strict=True)])
    result = evaluate_trades([t.net_bps for t in trades],
                             adverse_bps=[t.adverse_bps for t in trades],
                             days=[t.day for t in trades],
                             max_dd_bps=sized_dd,
                             dd_budget_bps=DD_BUDGET_BPS, family_size=3)
    result["max_dd_sized_bps"] = sized_dd
    result["mean_equity_bps_per_day"] = (
        sum(sized) / len({t.day for t in trades}) if trades else None)
    days_seen = sorted({t.day for t in trades})
    per_day = {d: sum(t.net_bps for t in trades if t.day == d) for d in days_seen}
    result.update({
        "hypothesis": name,
        "gross_expectancy_bps": (statistics.fmean([t.gross_bps for t in trades])
                                 if trades else None),
        "trading_days": len(days_seen),
        "mean_net_bps_per_active_day": (statistics.fmean(list(per_day.values()))
                                        if per_day else None),
        "best_day_bps": max(per_day.values()) if per_day else None,
        "worst_day_bps": min(per_day.values()) if per_day else None,
    })
    return result


def h4_trades(bars_by_symbol: dict[str, list[Bar]],
              model: CostModel | None = None) -> list[Trade]:
    """H4: H2 mechanics on daily causal top-3 ATR% universe (fresh data only)."""
    model = model or CostModel()
    atr_pct: dict[str, dict[str, float]] = {}
    for symbol, bars in bars_by_symbol.items():
        atr = _atr(bars)
        daily: dict[str, float] = {}
        for bar, value in zip(bars, atr, strict=True):
            if value is not None and bar.close > 0:
                daily[_day_of(bar.ts_ms)] = value / bar.close
        atr_pct[symbol] = daily
    days = sorted({d for daily in atr_pct.values() for d in daily})
    active: dict[str, set[str]] = {s: set() for s in bars_by_symbol}
    for idx, day in enumerate(days):
        ranked = []
        for symbol, daily in atr_pct.items():
            prior = [daily[d] for d in days[max(0, idx - 30):idx] if d in daily]
            if prior:
                ranked.append((statistics.fmean(prior), symbol))
        for _, symbol in sorted(ranked, reverse=True)[:3]:
            active[symbol].add(day)
    trades: list[Trade] = []
    for symbol, bars in bars_by_symbol.items():
        trades += [t for t in h2_trades(bars, model) if t.day in active[symbol]]
    return sorted(trades, key=lambda t: t.day)


def h1_result() -> dict[str, Any]:
    return {"hypothesis": "H1-maker-ofi-scalp", "verdict": "UNDERPOWERED",
            "reason": "UNEVALUABLE on dev data: no quote/book channel "
                      "(pilot manifest: 'no quote channel in futures archive "
                      "(books unevaluable)'); top-5 imbalance cannot be "
                      "computed and will not be proxied. Needs book capture.",
            "n_trades": 0}
