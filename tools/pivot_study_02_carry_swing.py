#!/usr/bin/env python3
"""STUDY-02 — P2 funding-carry and P3 swing economics screen (descriptive).

Preregistered measurement, frozen in reports/pivot/study02-prereg.json
BEFORE this tool produced any outcome. Mirrors STUDY-01's role: measure the
economics of the PIVOT-01 P2/P3 families on repo bytes so the owner's
10-day-capture decision is informed by numbers, not priors.

This tool creates NO strategy, NO candidate, consumes NO attempt budget,
makes NO network calls, and touches no worker-lane code. Data:
datasets/cache aggTrade parquet (transform v2, causal) + funding settlement
parquets, per reports/pivot/study02-prereg.json.

Conventions (frozen):
- 1m close = last trade price in [m, m+60s); close_time = m+60s; minutes
  with zero trades are MISSING (no forward-fill).
- 1h close = last non-missing 1m close in the hour (= last trade of hour).
- Entry (P2): first 1m close with close_time >= settlement_ts + 60s.
- Exit (P2): first 1m close with close_time >= entry_ts + H.
- Funding attribution: settlements with entry_ts < s < exit_ts (strictly
  inside the hold). SHORT collects +rate, LONG collects -rate.
- net_bps = (side_price_pnl + funding_collected) * 1e4 - 26 (cost-contract-v1).
- One position per (symbol, side); overlaps skipped and counted.
- Missing entry/exit data -> skipped and counted; never imputed.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

RT_COST_BPS = 26.0          # cost-contract-v1 taker round trip
P2_TRIGGER_BPS = 1.0        # venue baseline funding 0.01%/8h, declared a priori
P2_TRAILING = 3             # settlements (24h at 8h interval)
P2_HOLDS_H = (8, 24, 72, 168)
P3_TRIGGER_BPS = 100.0      # declared a priori, order of P3 80bps target
P3_LOOKBACK_H = 24
P3_HORIZONS_H = (4, 8, 24)
WARMUP_H = 24


# ---------------------------------------------------------------- data load

def load_funding(cache_root: Path, symbol: str) -> list[tuple[int, float]]:
    """Settlement-grade funding rows (ts_ms, rate decimal), ascending."""
    import pyarrow.parquet as pq
    rows: list[tuple[int, float]] = []
    for f in sorted((cache_root / f"symbol={symbol}" / "funding").glob("*.parquet")):
        t = pq.read_table(f, columns=["ts_ms", "rate"]).to_pandas()
        rows += list(zip(t["ts_ms"].astype("int64"), t["rate"].astype("float")))
    rows.sort()
    return rows


def load_minute_closes(cache_root: Path, symbol: str, day_dirs: list[str],
                       ) -> tuple[list[int], list[float]]:
    """Causal 1m closes from aggTrade parquet for the given ISO days.

    Returns (close_times_ms, closes) ascending; missing minutes absent.
    close of minute m = last trade in [m, m+60s); close_time = m+60s.
    """
    import pyarrow.parquet as pq
    times: list[int] = []
    closes: list[float] = []
    for day in day_dirs:
        d = cache_root / f"symbol={symbol}" / f"date={day}" / "channel=aggTrade"
        files = sorted(d.glob("*.parquet"))
        if not files:
            continue
        t = pq.read_table(files[0], columns=["ts_ms", "price"]).to_pandas()
        ts = t["ts_ms"].to_numpy("int64")
        px = t["price"].to_numpy("float64")
        # last index per minute bucket via searchsorted on bucket starts
        day_start = int(day.replace("-", ""))  # unused; bucket from ts itself
        base = (ts[0] // 60_000) * 60_000
        mins, last_px = [], []
        i = 0
        n = len(ts)
        m = base
        while i < n:
            m_end = m + 60_000
            j = i
            while j < n and ts[j] < m_end:
                j += 1
            if j > i:
                mins.append(m_end)
                last_px.append(px[j - 1])
            i = j
            m = m_end
        # guard: trades before first full minute (ts < base+60s already covered)
        times.extend(mins)
        closes.extend(last_px)
    return times, closes


def first_close_at_or_after(times: list[int], closes: list[float],
                            target_ms: int) -> tuple[int, float] | None:
    """First 1m close with close_time >= target_ms (binary search)."""
    import bisect
    i = bisect.bisect_left(times, target_ms)
    if i >= len(times):
        return None
    return times[i], closes[i]


# ---------------------------------------------------------------- core math

def funding_collected(settlements: list[tuple[int, float]], entry_ts: int,
                      exit_ts: int, side: str) -> float:
    """Sum of signed rates strictly inside (entry_ts, exit_ts).

    SHORT collects +rate (longs pay shorts when positive); LONG collects
    -rate. Settlement at the exit instant is conservatively excluded.
    """
    sign = 1.0 if side == "SHORT" else -1.0
    total = 0.0
    for ts, rate in settlements:
        if entry_ts < ts < exit_ts:
            total += sign * rate
    return total


def net_bps(price_pnl: float, funding: float) -> float:
    return (price_pnl + funding) * 1e4 - RT_COST_BPS


def p2_cells(symbol: str, settlements: list[tuple[int, float]],
             times: list[int], closes: list[float], window: tuple[int, int],
             trigger_bps: float = P2_TRIGGER_BPS,
             holds_h: tuple[int, ...] = P2_HOLDS_H) -> list[dict]:
    """Preregistered P2 signal cells for one symbol."""
    out: list[dict] = []
    trig = trigger_bps / 1e4
    w_start, w_end = window
    sig_start = w_start + WARMUP_H * 3_600_000
    for side in ("SHORT", "LONG"):
        for hold_h in holds_h:
            last_exit = -1  # one-position rule is PER CELL (prereg: "of the same cell")
            cell = {"symbol": symbol, "family": "P2", "side": side,
                    "hold_h": hold_h, "n_signals": 0, "n_entered": 0,
                    "n_skipped_overlap": 0, "n_skipped_missing": 0,
                    "gross_bps": [], "funding_bps": [], "price_bps": []}
            hold_ms = hold_h * 3_600_000
            for i in range(P2_TRAILING, len(settlements)):
                ts_i, _ = settlements[i]
                if ts_i < sig_start or ts_i >= w_end:
                    continue
                trail = sum(r for _, r in settlements[i - P2_TRAILING:i]) / P2_TRAILING
                if side == "SHORT" and trail < trig:
                    continue
                if side == "LONG" and trail > -trig:
                    continue
                cell["n_signals"] += 1
                ent = first_close_at_or_after(times, closes, ts_i + 60_000)
                if ent is None:
                    cell["n_skipped_missing"] += 1
                    continue
                entry_ts, entry_px = ent
                if entry_ts >= w_end:
                    cell["n_skipped_missing"] += 1
                    continue
                if entry_ts < last_exit:
                    cell["n_skipped_overlap"] += 1
                    continue
                ext = first_close_at_or_after(times, closes, entry_ts + hold_ms)
                if ext is None:
                    cell["n_skipped_missing"] += 1
                    continue
                exit_ts, exit_px = ext
                last_exit = exit_ts
                pnl = ((entry_px - exit_px) / entry_px if side == "SHORT"
                       else (exit_px - entry_px) / entry_px)
                fund = funding_collected(settlements, entry_ts, exit_ts, side)
                cell["n_entered"] += 1
                cell["price_bps"].append(pnl * 1e4)
                cell["funding_bps"].append(fund * 1e4)
                cell["gross_bps"].append((pnl + fund) * 1e4)
            out.append(cell)
    return out


def hour_closes(times: list[int], closes: list[float],
                ) -> tuple[list[int], list[float]]:
    """1h closes: last non-missing 1m close in each hour."""
    out_t: list[int] = []
    out_p: list[float] = []
    n = len(times)
    i = 0
    while i < n:
        h_end = (times[i] // 3_600_000) * 3_600_000 + 3_600_000
        j = i
        while j < n and times[j] < h_end:
            j += 1
        out_t.append(h_end)
        out_p.append(closes[j - 1])
        i = j
    return out_t, out_p


def p3_screen(symbol: str, htimes: list[int], hcloses: list[float],
              window: tuple[int, int]) -> list[dict]:
    """Preregistered P3 volatility-vs-cost arithmetic (all hours)."""
    out = []
    w_start, w_end = window
    for h in P3_HORIZONS_H:
        rets = []
        for i in range(len(htimes)):
            ts = htimes[i]
            if ts < w_start or ts > w_end - h * 3_600_000:
                continue
            j = i + h
            if j >= len(htimes) or htimes[j] != ts + h * 3_600_000:
                continue  # gap in hours -> skip, no imputation
            rets.append((hcloses[j] / hcloses[i] - 1) * 1e4)
        if not rets:
            out.append({"symbol": symbol, "family": "P3-screen", "h": h,
                        "n": 0})
            continue
        mu = sum(rets) / len(rets)
        var = sum((r - mu) ** 2 for r in rets) / len(rets)
        ab = sorted(abs(r) for r in rets)
        out.append({
            "symbol": symbol, "family": "P3-screen", "h": h, "n": len(rets),
            "stdev_bps": math.sqrt(var),
            "median_abs_move_bps": ab[len(ab) // 2],
            "p90_abs_move_bps": ab[int(0.9 * (len(ab) - 1))],
            "frac_ge_hurdle": sum(1 for a in ab if a >= RT_COST_BPS) / len(ab),
            "frac_ge_target80": sum(1 for a in ab if a >= 80.0) / len(ab),
        })
    return out


def p3_cells(symbol: str, settlements: list[tuple[int, float]],
             htimes: list[int], hcloses: list[float],
             window: tuple[int, int],
             trigger_bps: float = P3_TRIGGER_BPS,
             ) -> list[dict]:
    """Preregistered P3 continuation signal cells for one symbol."""
    out: list[dict] = []
    trig = trigger_bps / 1e4
    w_start, w_end = window
    sig_start = w_start + WARMUP_H * 3_600_000
    for side in ("LONG", "SHORT"):
        for k in P3_HORIZONS_H:
            last_exit = -1  # per-cell tracking, consistent with P2 frozen wording
            cell = {"symbol": symbol, "family": "P3", "side": side,
                    "hold_h": k, "n_signals": 0, "n_entered": 0,
                    "n_skipped_overlap": 0, "n_skipped_missing": 0,
                    "gross_bps": [], "funding_bps": [], "price_bps": []}
            for i in range(len(htimes)):
                ts = htimes[i]
                if ts < sig_start or ts > w_end - k * 3_600_000:
                    continue
                j = i - P3_LOOKBACK_H
                if j < 0 or htimes[j] != ts - P3_LOOKBACK_H * 3_600_000:
                    continue  # lookback bar missing -> skip
                ret24 = hcloses[i] / hcloses[j] - 1
                if side == "LONG" and ret24 < trig:
                    continue
                if side == "SHORT" and ret24 > -trig:
                    continue
                if i + k >= len(htimes) or htimes[i + k] != ts + k * 3_600_000:
                    cell["n_signals"] += 1
                    cell["n_skipped_missing"] += 1
                    continue
                cell["n_signals"] += 1
                entry_ts, entry_px = ts, hcloses[i]
                if entry_ts < last_exit:
                    cell["n_skipped_overlap"] += 1
                    continue
                exit_ts, exit_px = htimes[i + k], hcloses[i + k]
                last_exit = exit_ts
                pnl = ((exit_px - entry_px) / entry_px if side == "LONG"
                       else (entry_px - exit_px) / entry_px)
                fund = funding_collected(settlements, entry_ts, exit_ts, side)
                cell["n_entered"] += 1
                cell["price_bps"].append(pnl * 1e4)
                cell["funding_bps"].append(fund * 1e4)
                cell["gross_bps"].append((pnl + fund) * 1e4)
            out.append(cell)
    return out


# ---------------------------------------------------------------- summaries

def summarize(cell: dict) -> dict:
    g, f, p = cell["gross_bps"], cell["funding_bps"], cell["price_bps"]
    n = len(g)
    s = {k: cell[k] for k in ("symbol", "family", "side", "hold_h",
                              "n_signals", "n_entered", "n_skipped_overlap",
                              "n_skipped_missing")}
    if n == 0:
        s.update({"net_mean_bps": None, "net_median_bps": None,
                  "hit_rate": None, "gross_mean_bps": None,
                  "funding_mean_bps": None, "price_mean_bps": None})
        return s
    nets = sorted(x - RT_COST_BPS for x in g)
    s.update({
        "net_mean_bps": sum(nets) / n,
        "net_median_bps": nets[n // 2] if n % 2 else (nets[n // 2 - 1] + nets[n // 2]) / 2,
        "hit_rate": sum(1 for x in nets if x > 0) / n,
        "gross_mean_bps": sum(g) / n,
        "funding_mean_bps": sum(f) / n,
        "price_mean_bps": sum(p) / n,
    })
    return s


def funding_stats(settlements: list[tuple[int, float]],
                  window: tuple[int, int]) -> dict:
    rates = [r * 1e4 for ts, r in settlements
             if window[0] <= ts < window[1]]
    if not rates:
        return {"n": 0}
    sr = sorted(rates)
    n = len(rates)
    mean = sum(rates) / n
    # persistence: trailing-3 mean vs next settlement rate
    xs, ys = [], []
    for i in range(P2_TRAILING, n):
        xs.append(sum(sr[i - P2_TRAILING:i]) / P2_TRAILING)
        ys.append(sr[i])
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    vx = sum((a - mx) ** 2 for a in xs)
    vy = sum((b - my) ** 2 for b in ys)
    pearson = cov / math.sqrt(vx * vy) if vx > 0 and vy > 0 else None
    sign_match = (sum(1 for a, b in zip(xs, ys) if (a > 0) == (b > 0)) / len(xs))
    fpd = mean / 8 * 24  # bps per day (8h settlements)
    return {
        "n": n,
        "mean_bps_per_8h": mean,
        "median_bps_per_8h": sr[n // 2],
        "p10_bps": sr[int(0.1 * (n - 1))],
        "p90_bps": sr[int(0.9 * (n - 1))],
        "min_bps": sr[0],
        "max_bps": sr[-1],
        "frac_positive": sum(1 for r in rates if r > 0) / n,
        "annualized_pct": mean / 8 * 24 * 365 / 100,
        "funding_per_day_bps": fpd,
        "breakeven_hold_days": RT_COST_BPS / fpd if fpd > 0 else None,
        "persistence_pearson_trail3_vs_next": pearson,
        "persistence_sign_match": sign_match,
    }


# ---------------------------------------------------------------- self-check

def self_check() -> None:
    """Synthetic fixture asserting sign conventions and causal boundaries."""
    # trades: minute closes at known prices
    times = [m * 60_000 + 60_000 for m in range(0, 200)]
    closes = [100.0 + 0.01 * m for m in range(200)]  # rising 1bp/min... 0.01/100=1bp/min
    # settlements: positive rate at t=3.6M (1h), entry must exclude it
    settlements = [(3_600_000, 0.0001), (2 * 3_600_000, 0.0002),
                   (5 * 3_600_000, -0.0001)]
    # SHORT entry after settlement 1 (ts 3.6M+60s -> close_time 3.66M? our
    # times are minute ends; first >= 3_660_000 is 3_660_000)
    ent = first_close_at_or_after(times, closes, 3_600_000 + 60_000)
    assert ent is not None and ent[0] == 3_660_000, ent
    # hold 90 min -> exit at 5_400_000... settlement at 5.4M excluded (strict)
    ext = first_close_at_or_after(times, closes, ent[0] + 5_400_000)
    assert ext is not None
    f_short = funding_collected(settlements, ent[0], ext[0], "SHORT")
    # inside (3.66M, ext): settlement 2 at 7.2M? no — settlements are at
    # 3.6M (excluded: < entry), 7.2M (2*3600s=7.2M — inside if exit>7.2M), ...
    # use explicit tiny case instead:
    s2 = [(1_000, 0.0001), (2_000, 0.0002), (3_000, -0.0001)]

    def close(a: float, b: float) -> bool:
        return abs(a - b) < 1e-12

    assert close(funding_collected(s2, 1_000, 3_000, "SHORT"), 0.0002)
    assert close(funding_collected(s2, 1_000, 3_000, "LONG"), -0.0002)
    assert close(funding_collected(s2, 999, 3_000, "SHORT"), 0.0003)
    assert close(funding_collected(s2, 1_000, 3_001, "SHORT"), 0.0001)
    assert close(net_bps(0.0, 0.0026), 0.0)  # funding exactly covers RT
    # one-position overlap logic is exercised in unit tests (test_pivot_study02)
    print("SELF-CHECK OK")


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cache-root", type=Path, default=None,
                    help="datasets/cache directory (parquet layout)")
    ap.add_argument("--out", type=Path, default=None, help="results JSON")
    ap.add_argument("--self-check", action="store_true")
    ap.add_argument("--window-start", default="2026-09-11")
    ap.add_argument("--window-end", default="2026-10-11")
    ap.add_argument("--sensitivity", action="store_true",
                    help="POST-HOC labeled arms; never decision-relevant")
    args = ap.parse_args()

    if args.self_check:
        self_check()
        return 0
    if args.cache_root is None or args.out is None:
        ap.error("--cache-root and --out are required without --self-check")

    import datetime as dt

    def ms(day: str) -> int:
        d = dt.date.fromisoformat(day)
        return int(dt.datetime(d.year, d.month, d.day,
                               tzinfo=dt.timezone.utc).timestamp() * 1000)

    w_start, w_end = ms(args.window_start), ms(args.window_end)
    window = (w_start, w_end)
    # day dirs inside the window (UTC days)
    days = []
    d0 = dt.date.fromisoformat(args.window_start)
    d1 = dt.date.fromisoformat(args.window_end)
    d = d0
    while d <= d1:
        days.append(d.isoformat())
        d += dt.timedelta(days=1)

    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ZECUSDT",
               "NEARUSDT", "STRKUSDT", "XRPUSDT", "WUSDT"]
    full_funding = {"BTCUSDT", "ETHUSDT"}

    results: dict = {
        "study": "STUDY-02",
        "prereg": "reports/pivot/study02-prereg.json",
        "window_utc": [args.window_start, args.window_end],
        "rt_cost_bps": RT_COST_BPS,
        "funding_stats": {},
        "p2_cells": [],
        "p3_screen": [],
        "p3_cells": [],
        "posthoc_sensitivity": None,
    }

    for sym in symbols:
        settlements = load_funding(args.cache_root, sym)
        times, closes = load_minute_closes(args.cache_root, sym, days)
        if settlements:
            stats = funding_stats(settlements, window)
            stats["symbol"] = sym
            stats["funding_coverage"] = ("full-window" if sym in full_funding
                                         else "september-only")
            results["funding_stats"][sym] = stats
        htimes, hcloses = hour_closes(times, closes)
        results["p3_screen"] += p3_screen(sym, htimes, hcloses, window)
        if sym in full_funding:
            results["p2_cells"] += [summarize(c) for c in
                                    p2_cells(sym, settlements, times, closes,
                                             window)]
        elif settlements:
            # supplementary September-only cells (declared in prereg)
            sep_end = ms("2026-09-30") + 86_400_000
            results["p2_cells"] += [summarize(c) for c in
                                    p2_cells(sym, settlements, times, closes,
                                             (w_start, sep_end))]
        results["p3_cells"] += [summarize(c) for c in
                                p3_cells(sym, settlements, htimes, hcloses,
                                         window)]

    if args.sensitivity:
        post: list[dict] = []
        for sym in sorted(full_funding):
            settlements = load_funding(args.cache_root, sym)
            times, closes = load_minute_closes(args.cache_root, sym, days)
            htimes, hcloses = hour_closes(times, closes)
            for t in (0.5, 2.0):
                post += [{"label": f"POST-HOC P2 T={t}bp"} |
                         summarize(c) for c in
                         p2_cells(sym, settlements, times, closes, window,
                                  trigger_bps=t)]
            for tb in (50.0, 200.0):
                post += [{"label": f"POST-HOC P3 trig={tb}bps"} |
                         summarize(c) for c in
                         p3_cells(sym, settlements, htimes, hcloses, window,
                                  trigger_bps=tb)]
        results["posthoc_sensitivity"] = post

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=1))
    print(f"WROTE {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
