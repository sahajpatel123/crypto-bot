#!/usr/bin/env python3
"""STUDY-03 — P2 delta-neutral basis carry + P3 momentum replication.

Preregistered in reports/pivot/study03-prereg.json (commit 16c614d) BEFORE
any fetch or run. Descriptive measurement only: no strategy, no candidate,
no attempt-budget consumption, no worker-lane files.

Arm A: spot+perp basis/carry economics for BTC/ETH on Jun-Aug 2026 Vision
monthly klines (fresh window) with settlement-grade funding. Exact two-leg
P&L, 30bps VIP0 book round trip, capital-efficiency math at perp leverage
L in {1,2,3}.

Arm B: exact replication of STUDY-02's P3 construction (imports the frozen
functions from tools/pivot_study_02_carry_swing.py) on Jun-Aug 2026 for all
8 symbols — tests whether STUDY-02's alt-momentum positives replicate or
were a regime artifact.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import sys
import zipfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

import pivot_study_02_carry_swing as S02  # noqa: E402  (frozen construction)

RT_COST_BPS = S02.RT_COST_BPS          # 26 bps perp-only reference
BOOK_RT_BPS = 30.0                     # spot 10x2 + perp 5x2, VIP0 all-taker
BOOK_RT_BNB_BPS = 24.0                 # POST-HOC labeled arm
BASIS_TRIGGER_ANN = 0.08               # a priori hurdle (prereg)
ARM_A_HOLDS_H = (72, 168, 336)
ARM_B_HORIZONS = S02.P3_HORIZONS_H     # (4, 8, 24)
REPL_SYMBOLS = ("NEARUSDT", "STRKUSDT", "WUSDT")


# ---------------------------------------------------------------- kline load

def load_1m_closes(zip_dir: Path, prefix: str, months: list[str],
                   window: tuple[int, int]) -> tuple[list[int], list[float]]:
    """Causal 1m closes from Vision monthly kline zips.

    close published at close_time (= open_time + 60s); rows with trade
    count 0 are MISSING (no forward-fill). Returns ascending
    (close_times_ms, closes) clipped to the window.
    """
    times: list[int] = []
    closes: list[float] = []
    for m in months:
        path = zip_dir / f"{prefix}-{m}.zip"
        if not path.exists():
            continue  # absent month recorded by the fetcher; never imputed
        with zipfile.ZipFile(path) as zf:
            name = [n for n in zf.namelist() if n.endswith(".csv")][0]
            with zf.open(name) as fh:
                import csv
                rows = list(csv.reader(io.TextIOWrapper(fh, encoding="utf-8")))
        if not rows:
            continue
        header = rows[0]
        if "close_time" in header and "count" in header:
            ci, cli, coi = (header.index("close"), header.index("close_time"),
                            header.index("count"))
            body = rows[1:]
        else:  # headerless legacy layout
            coi, ci, cli = 8, 4, 6
            body = rows
        if not body:
            continue
        # per-file scale decision from the first row's open_time: seconds-era
        # archives (~1.8e9) vs ms-era (~1.8e12); synthetic/small values in
        # tests use realistic ms bases
        scale = 1000 if int(body[0][0]) < 10**11 else 1
        for row in body:
            if not row:
                continue
            count = int(row[coi])
            if count == 0:
                continue  # no trades -> no price discovery -> missing
            ct = int(row[cli]) * scale
            if window[0] <= ct < window[1]:
                times.append(ct)
                closes.append(float(row[ci]))
    return times, closes


def load_funding(zip_dir: Path, symbol: str, months: list[str],
                 window: tuple[int, int]) -> list[tuple[int, float]]:
    """Settlement rows (calc_time, rate) inside the window; absent months=[]"""
    out: list[tuple[int, float]] = []
    for m in months:
        path = zip_dir / f"funding-{symbol}-{m}.zip"
        if not path.exists():
            continue
        with zipfile.ZipFile(path) as zf:
            name = [n for n in zf.namelist() if n.endswith(".csv")][0]
            with zf.open(name) as fh:
                import csv
                rows = list(csv.reader(io.TextIOWrapper(fh, encoding="utf-8")))
        header = rows[0]
        ti = header.index("calc_time")
        ri = header.index("last_funding_rate")
        for row in rows[1:]:
            ts = int(row[ti])
            if window[0] <= ts < window[1]:
                out.append((ts, float(row[ri])))
    out.sort()
    return out


# ---------------------------------------------------------------- Arm A

def basis_series(spot_t: list[int], spot_p: list[float],
                 perp_t: list[int], perp_p: list[float],
                 ) -> tuple[list[int], list[float]]:
    """b_t = (perp - spot)/spot at minutes where BOTH legs are present."""
    import bisect
    bt: list[int] = []
    bv: list[float] = []
    for i, t in enumerate(spot_t):
        j = bisect.bisect_left(perp_t, t)
        if j < len(perp_t) and perp_t[j] == t:
            bt.append(t)
            bv.append((perp_p[j] - spot_p[i]) / spot_p[i])
    return bt, bv


def arm_a_descriptive(bt: list[int], bv: list[float],
                      window: tuple[int, int]) -> dict:
    n = len(bv)
    if n == 0:
        return {"n": 0}
    sb = sorted(b * 1e4 for b in bv)
    mean_b = sum(bv) / n
    # convergence signature: corr(b_t, b_{t+8h} - b_t)
    import bisect
    step = 8 * 3_600_000
    xs, ys = [], []
    for i, t in enumerate(bt):
        j = bisect.bisect_left(bt, t + step)
        if j < len(bt) and bt[j] == t + step:
            xs.append(bv[i])
            ys.append(bv[j] - bv[i])
    pearson = None
    if len(xs) > 2:
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        vx = sum((a - mx) ** 2 for a in xs)
        vy = sum((b - my) ** 2 for b in ys)
        if vx > 0 and vy > 0:
            pearson = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) \
                / math.sqrt(vx * vy)
    span_days = (window[1] - window[0]) / 86_400_000
    return {
        "n_minutes": n,
        "coverage_frac_of_window": n / max(1, (window[1] - window[0]) // 60_000),
        "basis_mean_bps": mean_b * 1e4,
        "basis_median_bps": sb[n // 2],
        "basis_p10_bps": sb[int(0.1 * (n - 1))],
        "basis_p90_bps": sb[int(0.9 * (n - 1))],
        "basis_frac_positive": sum(1 for b in bv if b > 0) / n,
        "basis_annualized_pct": mean_b * 3 * 365 * 100,
        "convergence_corr_b_vs_8h_change": pearson,
        "n_convergence_pairs": len(xs),
        "frac_minutes_basis_ann_ge_8pct": sum(
            1 for b in bv if b * 3 * 365 >= BASIS_TRIGGER_ANN) / n,
        "span_days": span_days,
    }


def arm_a_cells(symbol: str, spot_t: list[int], spot_p: list[float],
                perp_t: list[int], perp_p: list[float],
                settlements: list[tuple[int, float]],
                window: tuple[int, int],
                trigger_ann: float = BASIS_TRIGGER_ANN,
                book_rt_bps: float = BOOK_RT_BPS,
                ) -> list[dict]:
    """Delta-neutral cells: LONG spot + SHORT perp when basis ann >= trigger."""
    import bisect
    out: list[dict] = []
    # common minutes (both legs present), ascending
    ct: list[int] = []
    sp: list[float] = []
    pp: list[float] = []
    j = 0
    for i, t in enumerate(spot_t):
        while j < len(perp_t) and perp_t[j] < t:
            j += 1
        if j < len(perp_t) and perp_t[j] == t:
            ct.append(t)
            sp.append(spot_p[i])
            pp.append(perp_p[j])
            j += 1
    for hold_h in ARM_A_HOLDS_H:
        last_exit = -1
        cell = {"symbol": symbol, "family": "P2-basis", "side": "SHORT_PERP",
                "hold_h": hold_h, "n_signals": 0, "n_entered": 0,
                "n_skipped_overlap": 0, "n_skipped_missing": 0,
                "pnl_bps": [], "funding_bps": []}
        hold_ms = hold_h * 3_600_000
        for i in range(len(ct) - 1):
            b_ann = (pp[i] - sp[i]) / sp[i] * 3 * 365
            if b_ann < trigger_ann:
                continue
            if ct[i] < last_exit:
                continue  # one position per cell
            cell["n_signals"] += 1
            e = i + 1  # entry at NEXT common close (causal)
            x_target = ct[e] + hold_ms
            k = bisect.bisect_left(ct, x_target)
            if k >= len(ct):
                cell["n_skipped_missing"] += 1
                continue
            entry_ts, exit_ts = ct[e], ct[k]
            spot_ret = (sp[k] - sp[e]) / sp[e]
            perp_ret_short = (pp[e] - pp[k]) / pp[e]
            pnl = spot_ret + perp_ret_short
            fund = S02.funding_collected(settlements, entry_ts, exit_ts,
                                         "SHORT")
            last_exit = exit_ts
            cell["n_entered"] += 1
            cell["pnl_bps"].append(pnl * 1e4)
            cell["funding_bps"].append(fund * 1e4)
        out.append(cell)
    return out


def summarize_arm_a(cell: dict, book_rt_bps: float = BOOK_RT_BPS) -> dict:
    p, f = cell["pnl_bps"], cell["funding_bps"]
    n = len(p)
    s = {k: cell[k] for k in ("symbol", "family", "side", "hold_h",
                              "n_signals", "n_entered", "n_skipped_overlap",
                              "n_skipped_missing")}
    if n == 0:
        s.update({"net_mean_bps": None, "net_median_bps": None,
                  "hit_rate": None, "funding_mean_bps": None,
                  "pnl_mean_bps": None})
        return s
    nets = sorted(p[i] + f[i] - book_rt_bps for i in range(n))
    s.update({
        "net_mean_bps": sum(nets) / n,
        "net_median_bps": nets[n // 2] if n % 2
        else (nets[n // 2 - 1] + nets[n // 2]) / 2,
        "hit_rate": sum(1 for x in nets if x > 0) / n,
        "funding_mean_bps": sum(f) / n,
        "pnl_mean_bps": sum(p) / n,
    })
    return s


def capital_efficiency(cells: list[dict]) -> list[dict]:
    """net annualized on TOTAL capital at perp-leg leverage L in {1,2,3}."""
    out = []
    for c in cells:
        if c["hold_h"] != 168 or c["net_mean_bps"] is None:
            continue
        ann_frac = (c["net_mean_bps"] / 1e4) * (365 * 24 / 168)
        for L in (1, 2, 3):
            out.append({"symbol": c["symbol"], "leverage_L": L,
                        "net_ann_on_total_pct": ann_frac / (1 + 1 / L) * 100})
    return out


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vision-dir", type=Path, required=True,
                    help="directory with fetched Vision zips")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--sensitivity", action="store_true")
    args = ap.parse_args()

    import datetime as dt

    def ms(day: str) -> int:
        d = dt.date.fromisoformat(day)
        return int(dt.datetime(d.year, d.month, d.day,
                               tzinfo=dt.timezone.utc).timestamp() * 1000)

    w0, w1 = ms("2026-06-01"), ms("2026-09-01")
    window = (w0, w1)
    months = ["2026-06", "2026-07", "2026-08"]
    months_supp = ["2026-09", "2026-10"]
    w_supp = (ms("2026-09-11"), ms("2026-10-11"))

    results: dict = {
        "study": "STUDY-03",
        "prereg": "reports/pivot/study03-prereg.json",
        "armA": {"descriptive": {}, "cells": [], "capital_efficiency": [],
                 "supplementary_prior_use": []},
        "armB": {"cells": [], "funding_coverage": {}},
        "posthoc_sensitivity": None,
    }

    # ---- Arm A: basis economics (BTC/ETH, fresh Jun-Aug window)
    for sym in ("BTCUSDT", "ETHUSDT"):
        spot_t, spot_p = load_1m_closes(args.vision_dir, f"spot-1m-{sym}",
                                        months, window)
        perp_t, perp_p = load_1m_closes(args.vision_dir, f"futures-1m-{sym}",
                                        months, window)
        settlements = load_funding(args.vision_dir, sym, months, window)
        bt, bv = basis_series(spot_t, spot_p, perp_t, perp_p)
        results["armA"]["descriptive"][sym] = arm_a_descriptive(bt, bv, window)
        cells = [summarize_arm_a(c) for c in
                 arm_a_cells(sym, spot_t, spot_p, perp_t, perp_p,
                             settlements, window)]
        results["armA"]["cells"] += cells
        # supplementary: benchmark window (prior-use labeled for perp leg;
        # spot leg freshly fetched)
        spot_t2, spot_p2 = load_1m_closes(args.vision_dir, f"spot-1m-{sym}",
                                          months_supp, w_supp)
        cells2 = [dict(summarize_arm_a(c), window="2026-09-11..2026-10-11")
                  for c in arm_a_cells(sym, spot_t2, spot_p2, perp_t, perp_p,
                                       settlements, w_supp)]
        results["armA"]["supplementary_prior_use"] += cells2
    results["armA"]["capital_efficiency"] = capital_efficiency(
        results["armA"]["cells"])

    # ---- Arm B: exact STUDY-02 P3 construction on the fresh window
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "ZECUSDT",
                "NEARUSDT", "STRKUSDT", "XRPUSDT", "WUSDT"):
        perp_t, perp_p = load_1m_closes(args.vision_dir, f"futures-1m-{sym}",
                                        months, window)
        settlements = load_funding(args.vision_dir, sym, months, window)
        results["armB"]["funding_coverage"][sym] = len(settlements)
        htimes, hcloses = S02.hour_closes(perp_t, perp_p)
        cells = [S02.summarize(c) for c in
                 S02.p3_cells(sym, settlements, htimes, hcloses, window)]
        results["armB"]["cells"] += cells

    if args.sensitivity:
        post: list[dict] = []
        for sym in ("BTCUSDT", "ETHUSDT"):
            spot_t, spot_p = load_1m_closes(args.vision_dir,
                                            f"spot-1m-{sym}", months, window)
            perp_t, perp_p = load_1m_closes(args.vision_dir,
                                            f"futures-1m-{sym}", months,
                                            window)
            settlements = load_funding(args.vision_dir, sym, months, window)
            for trig in (0.04, 0.12):
                post += [{"label": f"POST-HOC A trig={trig:.0%}"} |
                         summarize_arm_a(c, book_rt_bps=BOOK_RT_BPS)
                         for c in arm_a_cells(sym, spot_t, spot_p, perp_t,
                                              perp_p, settlements, window,
                                              trigger_ann=trig)]
            post += [{"label": "POST-HOC A bnb-costs"} |
                     summarize_arm_a(c, book_rt_bps=BOOK_RT_BNB_BPS)
                     for c in arm_a_cells(sym, spot_t, spot_p, perp_t, perp_p,
                                          settlements, window)]
            perp_only_t, perp_only_p = perp_t, perp_p
            htimes, hcloses = S02.hour_closes(perp_only_t, perp_only_p)
            for tb in (50.0, 200.0):
                post += [{"label": f"POST-HOC B trig={tb:g}bps"} |
                         S02.summarize(c)
                         for c in S02.p3_cells(sym, settlements, htimes,
                                               hcloses, window,
                                               trigger_bps=tb)]
        results["posthoc_sensitivity"] = post

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=1))
    print(f"WROTE {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
