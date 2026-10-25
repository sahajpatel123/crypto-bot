"""Family C daily/weekly perp portfolios (prereg: research/prereg/C-family-daily.md).

Pure functions: daily closes + daily funding in, per-day portfolio
returns (bps of 1.0x gross notional) out. Signals use data up to the
close of day t; the position earns day t -> t+1. Costs are charged on
notional traded at each rebalance; funding is paid by longs.
"""
from __future__ import annotations

import datetime as dt
import statistics
from collections.abc import Callable
from dataclasses import dataclass

from cryptobot.research.verdict import _block_bootstrap, _bootstrap_p

COST_BPS_PER_SIDE = 9.0  # taker 5 + half-spread 1 + slippage 3
MIN_HISTORY_DAYS = 35
LOOKBACK = 28

Weights = dict[str, float]


@dataclass(frozen=True)
class DayResult:
    day: str
    net_bps: float
    adverse_bps: float
    gross_bps: float
    turnover: float


def _eligible(closes: dict[str, dict[str, float]], days: list[str], t: int) -> list[str]:
    if t + 1 >= len(days):
        return []
    if t < MIN_HISTORY_DAYS:
        return []
    # every close a signal or the P&L reads must exist (data gaps exclude)
    need = [days[k] for k in (t - MIN_HISTORY_DAYS, t - LOOKBACK, t - 1, t, t + 1)]
    out = [sym for sym, series in closes.items()
           if all(d in series for d in need)]
    return sorted(out)


def _ret(series: dict[str, float], a: str, b: str) -> float:
    return series[b] / series[a] - 1.0


def _rank_long_short(scores: dict[str, float], *, long_low: bool) -> Weights:
    """Quintile long/short, equal weight, 0.5 gross per side."""
    if len(scores) < 5:
        return {}
    ranked = sorted(scores, key=lambda s: (scores[s], s))
    q = max(1, len(ranked) // 5)
    low, high = ranked[:q], ranked[-q:]
    longs, shorts = (low, high) if long_low else (high, low)
    w = {s: 0.5 / q for s in longs}
    w.update({s: -0.5 / q for s in shorts})
    return w


def signal_tsmom(closes, funding, days, t, syms) -> Weights:
    if not syms:
        return {}
    w = {}
    for s in syms:
        r = _ret(closes[s], days[t - LOOKBACK], days[t])
        if r:
            w[s] = (1.0 if r > 0 else -1.0) / len(syms)
    return w


def signal_xsmom(closes, funding, days, t, syms) -> Weights:
    return _rank_long_short(
        {s: _ret(closes[s], days[t - LOOKBACK], days[t]) for s in syms},
        long_low=False)


def signal_carry(closes, funding, days, t, syms) -> Weights:
    scores = {s: sum(funding.get(s, {}).get(days[k], 0.0)
                     for k in range(t - 6, t + 1)) for s in syms}
    return _rank_long_short(scores, long_low=True)


def signal_reversal(closes, funding, days, t, syms) -> Weights:
    return _rank_long_short(
        {s: _ret(closes[s], days[t - 1], days[t]) for s in syms},
        long_low=True)


@dataclass(frozen=True)
class Spec:
    name: str
    signal: Callable[..., Weights]
    weekly: bool


SPECS = {
    "C1": Spec("C1-TSMOM", signal_tsmom, weekly=False),
    "C2": Spec("C2-XSMOM", signal_xsmom, weekly=True),
    "C3": Spec("C3-CARRY", signal_carry, weekly=True),
    "C4": Spec("C4-REVERSAL", signal_reversal, weekly=False),
}


def _is_monday(day: str) -> bool:
    return dt.date.fromisoformat(day).weekday() == 0


def run(spec: Spec, closes: dict[str, dict[str, float]],
        funding: dict[str, dict[str, float]], *, start: str, end: str,
        cost_bps: float = COST_BPS_PER_SIDE) -> list[DayResult]:
    """Daily returns for days in [start, end] (the day the P&L accrues)."""
    days = sorted({d for series in closes.values() for d in series})
    held: Weights = {}
    out: list[DayResult] = []
    for t in range(len(days) - 1):
        syms = _eligible(closes, days, t)
        held = {s: w for s, w in held.items() if s in syms}  # forced exits
        target = held
        if not spec.weekly or _is_monday(days[t]) or not held:
            target = spec.signal(closes, funding, days, t, syms) if syms else {}
        turnover = sum(abs(target.get(s, 0.0) - held.get(s, 0.0))
                       for s in set(target) | set(held))
        held = target
        nxt = days[t + 1]
        if not syms or not (start <= nxt <= end):
            continue  # no tradable universe yet: not a scored day
        gross = sum(w * _ret(closes[s], days[t], nxt) for s, w in held.items()) * 1e4
        fund = sum(w * funding.get(s, {}).get(nxt, 0.0) for s, w in held.items()) * 1e4
        gross_net_funding = gross - fund
        out.append(DayResult(
            day=nxt, gross_bps=gross_net_funding, turnover=turnover,
            net_bps=gross_net_funding - turnover * cost_bps,
            adverse_bps=gross_net_funding - turnover * cost_bps * 2.0))
    return out


def _week(day: str) -> str:
    y, w, _ = dt.date.fromisoformat(day).isocalendar()
    return f"{y}-W{w:02d}"


def score(results: list[DayResult], *, rounds: int = 2000) -> dict:
    """Week-block bootstrap statistics; ``rounds`` controls Monte Carlo precision."""
    if rounds < 1:
        raise ValueError("rounds must be positive")
    if not results:
        return {"n_days": 0}
    net = [r.net_bps for r in results]
    weeks = [_week(r.day) for r in results]
    means = _block_bootstrap(net, weeks, rounds=rounds)
    lo, hi = means[int(0.025 * len(means))], means[int(0.975 * len(means)) - 1]
    sd = statistics.pstdev(net)
    by_year: dict[str, list[float]] = {}
    for r in results:
        by_year.setdefault(r.day[:4], []).append(r.net_bps)
    equity, peak, dd = 0.0, 0.0, 0.0
    for v in net:
        equity += v
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return {
        "n_days": len(net),
        "mean_net_bps": statistics.fmean(net),
        "mean_adverse_bps": statistics.fmean(r.adverse_bps for r in results),
        "mean_gross_bps": statistics.fmean(r.gross_bps for r in results),
        "mean_turnover": statistics.fmean(r.turnover for r in results),
        "ci95_week_block": [lo, hi],
        "p_value": _bootstrap_p(means),
        "sharpe_annual": (statistics.fmean(net) / sd * 365 ** 0.5) if sd else None,
        "total_net_bps": sum(net),
        "max_dd_bps": dd,
        "by_year": {y: statistics.fmean(v) for y, v in sorted(by_year.items())},
    }


def dev_pass(stats: dict, *, years: tuple[str, ...], alpha: float) -> list[str]:
    """Return failed DEV criteria (empty list = PASS)."""
    fails = []
    if stats.get("n_days", 0) < 300:
        return ["5: fewer than 300 scored days"]
    if stats["ci95_week_block"][0] <= 0:
        fails.append("1: CI95 lower bound <= 0")
    if stats["mean_adverse_bps"] <= 0:
        fails.append("2: mean <= 0 at 2x adverse cost")
    if stats["p_value"] > alpha:
        fails.append(f"3: p={stats['p_value']:.4f} > {alpha}")
    bad = [y for y in years if stats["by_year"].get(y, -1.0) <= 0]
    if bad:
        fails.append(f"4: non-positive years {bad}")
    return fails
