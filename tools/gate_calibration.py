#!/usr/bin/env python3
"""Synthetic calibration and independent audit of the Family B gates.

No market files are loaded. The study injects generated daily P&L into the
production B4b decision evaluator while replacing its market simulator and
trial-vector loader with deterministic synthetic inputs.
"""
from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _finite(values):
    return [float(x) for x in values if math.isfinite(float(x))]


def oracle_sharpe(values, periods=365):
    x = [float(v) for v in values]
    if len(x) < 2:
        return 0.0
    mu = sum(x) / len(x)
    var = sum((v - mu) ** 2 for v in x) / (len(x) - 1)
    sd = math.sqrt(var)
    if sd <= 0 or sd < 1e-9:
        return 0.0
    return mu / sd * math.sqrt(periods)


def _oracle_n_eff(x, max_lag=30, hold_days=None, min_n=2.0):
    n = len(x)
    if n < 3:
        return float(n)
    mu = sum(x) / n
    e = [v - mu for v in x]
    g0 = sum(v * v for v in e) / n
    if g0 <= 0:
        return float(n)
    lag = max(1, min(int(max_lag), n - 1))
    inflation = 1.0
    for k in range(1, lag + 1):
        gk = sum(e[i] * e[i - k] for i in range(k, n)) / (n - k)
        inflation += 2.0 * (1.0 - k / (lag + 1.0)) * gk / g0
    n_eff = n / max(inflation, 1.0)
    if hold_days is not None and float(hold_days) > 0:
        n_eff = min(n_eff, n / float(hold_days))
    return float(min(max(n_eff, min_n), n))


def oracle_dsr(returns, annualized_trial_sharpes, periods=365, *,
               max_lag=30, hold_days=None, adjust_n=True):
    """Naive-loop Bailey/Lopez de Prado DSR using NormalDist, not repo helpers."""
    x = _finite(returns)
    n = len(x)
    if n < 2:
        return 0.5
    mu = sum(x) / n
    sd = math.sqrt(sum((v - mu) ** 2 for v in x) / (n - 1))
    if sd <= 0:
        return 1.0 if mu > 0 else (0.0 if mu < 0 else 0.5)
    sr = mu / sd
    scale = math.sqrt(periods)
    trials = [float(t) / scale for t in annualized_trial_sharpes
              if math.isfinite(float(t))]
    expected_max = 0.0
    if len(trials) > 1:
        tm = sum(trials) / len(trials)
        tvar = sum((v - tm) ** 2 for v in trials) / (len(trials) - 1)
        if tvar > 0:
            nd = NormalDist()
            k = len(trials)
            expected_max = math.sqrt(tvar) * (
                (1 - 0.5772156649) * nd.inv_cdf(1 - 1 / k)
                + 0.5772156649 * nd.inv_cdf(1 - 1 / (k * math.e)))
    z = [(v - mu) / sd for v in x]
    skew = sum(v ** 3 for v in z) / n
    kurt = sum(v ** 4 for v in z) / n
    inner = 1.0 - skew * sr + (kurt - 1.0) * sr * sr / 4.0
    if inner <= 0:
        return 1.0 if sr > expected_max else 0.0
    n_eff = _oracle_n_eff(x, max_lag, hold_days) if adjust_n else float(n)
    statistic = (sr - expected_max) * math.sqrt(n_eff - 1) / math.sqrt(inner)
    return NormalDist().cdf(statistic)


def _plain_sr(values):
    x = [float(v) for v in values]
    if len(x) < 2:
        return 0.0
    mu = sum(x) / len(x)
    sd = math.sqrt(sum((v - mu) ** 2 for v in x) / (len(x) - 1))
    return mu / sd if sd > 0 else 0.0


def oracle_pbo(trial_returns, n_partitions=8):
    """Literal CSCV enumeration and rank count, independent of numpy/production."""
    if any(not math.isfinite(float(value))
           for trial in trial_returns for value in trial):
        raise ValueError("PBO requires finite returns")
    k = len(trial_returns)
    if k < 2:
        return 0.5
    n = min(len(t) for t in trial_returns)
    s = int(n_partitions)
    if s % 2 or s < 2:
        raise ValueError("n_partitions must be even and >= 2")
    edges = [i * n // s for i in range(s + 1)]
    blocks = [list(range(edges[i], edges[i + 1])) for i in range(s)]
    below = total = 0
    for chosen in itertools.combinations(range(s), s // 2):
        train_idx = [i for b in chosen for i in blocks[b]]
        test_idx = [i for b in range(s) if b not in chosen for i in blocks[b]]
        ins = [_plain_sr([t[i] for i in train_idx]) for t in trial_returns]
        best = max(range(k), key=lambda i: ins[i])
        oos = [_plain_sr([t[i] for i in test_idx]) for t in trial_returns]
        rank = 1 + sum(1 for v in oos if v > oos[best])
        below += int(rank / (k + 1) > 0.5)
        total += 1
    return below / total if total else 0.5


def _oracle_stationary_indices(n, mean_block, rng):
    result = []
    p = 1.0 / max(float(mean_block), 1.0)
    while len(result) < n:
        start = rng.randrange(n)
        length = 1
        while rng.random() > p:
            length += 1
        for j in range(length):
            result.append((start + j) % n)
    return result[:n]


def oracle_stationary_ci(values, *, mean_block=5.0, rounds=1000,
                         alpha=0.05, seed=7, lower_q=None):
    x = list(values)
    if not x:
        return (0.0, 0.0)
    rng = random.Random(seed)
    sample = []
    for _ in range(rounds):
        ix = _oracle_stationary_indices(len(x), mean_block, rng)
        sample.append(sum(x[j] for j in ix) / len(ix))
    sample.sort()
    lo = min(rounds - 1, int((alpha / 2 if lower_q is None else lower_q) * rounds))
    hi = min(rounds - 1, int((1 - alpha / 2) * rounds))
    return sample[lo], sample[hi]


def oracle_month_share(returns: pd.Series) -> float:
    monthly = defaultdict(float)
    for stamp, value in returns.items():
        if math.isfinite(float(value)):
            monthly[(stamp.year, stamp.month)] += float(value)
    return (sum(v > 0 for v in monthly.values()) / len(monthly)
            if monthly else 0.0)


def oracle_positive_year_count(returns: pd.Series, years: list[int]) -> int:
    return sum(1 for y in years if math.fsum(
        float(value) for stamp, value in returns.items()
        if stamp.year == y and math.isfinite(float(value))) > 0)


def _family_b4b_module():
    path = ROOT / "tools" / "forward_b4b.py"
    spec = importlib.util.spec_from_file_location("_g1_forward_b4b", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _draw_trade_returns(rng, count, family, edge_bps):
    sd = 20.0
    if family in ("iid_gaussian", "multiple_testing"):
        noise = rng.normal(0.0, sd, count)
    elif family == "student_t3":
        noise = rng.standard_t(3, count) * sd / math.sqrt(3.0)
    elif family == "garch":
        var = sd * sd
        noise = np.empty(count)
        for i in range(count):
            var = 8.0 + 0.08 * (noise[i - 1] ** 2 if i else sd * sd) + 0.90 * var
            noise[i] = rng.normal(0.0, math.sqrt(var))
    elif family == "positive_ar":
        noise = np.empty(count)
        prev = 0.0
        innovation_sd = sd * math.sqrt(1 - 0.45 ** 2)
        for i in range(count):
            prev = 0.45 * prev + rng.normal(0.0, innovation_sd)
            noise[i] = prev
    elif family == "regime_switch":
        noise = rng.normal(0.0, sd, count)
        state = 1.0
        drift = np.empty(count)
        for i in range(count):
            if rng.random() < 0.04:
                state *= -1.0
            drift[i] = state * 5.0
        drift -= drift.mean()  # population drift is exactly balanced in this path
        noise = noise + drift
    else:
        raise ValueError(family)
    return np.asarray(noise, dtype=float) + float(edge_bps)


def _daily_stream(rng, trade_returns_bps):
    """Four-year 2020-23 stream; event counts cluster by synthetic month."""
    dates = pd.date_range("2020-01-01", "2023-12-31", freq="D", tz="UTC")
    months = pd.period_range("2020-01", "2023-12", freq="M")
    weights = rng.dirichlet(np.full(len(months), 2.5))
    monthly_counts = rng.multinomial(len(trade_returns_bps), weights)
    daily_bps = np.zeros(len(dates), dtype=float)
    event_day_ix = []
    event_values = []
    cursor = 0
    for month_ix, (month, n_month) in enumerate(zip(months, monthly_counts, strict=True)):
        month_days = dates[(dates.year == month.year) & (dates.month == month.month)]
        if n_month:
            choices = rng.integers(0, len(month_days), size=n_month)
            for local_ix in choices:
                event_day_ix.append(int(dates.get_loc(month_days[int(local_ix)])))
            event_values.extend(trade_returns_bps[cursor:cursor + n_month])
        cursor += n_month
    # Preserve the generated event-order return process while assigning the
    # monthly cluster counts to dates; pair values in month/event order.
    for day_ix, bps in zip(event_day_ix, event_values, strict=True):
        daily_bps[day_ix] += float(bps)
    net = daily_bps / 10_000.0
    dates_by_day = [str(d.date()) for d in dates]
    return dates, net, dates_by_day, event_day_ix, np.asarray(event_values)


def _generate_candidate_set(rng, *, family, events, edge_bps, k):
    streams = []
    for i in range(k):
        edge = edge_bps if i == 0 else 0.0
        trades = _draw_trade_returns(rng, events, family, edge)
        streams.append(_daily_stream(rng, trades))
    # Selection is external to B4b's single-cell evaluator: it represents
    # selection that happened before this one-shot forward screen.
    sr = [oracle_sharpe(x[1]) for x in streams]
    best = max(range(k), key=lambda i: sr[i])
    others = [sr[i] for i in range(k) if i != best]
    return streams[best], others, streams


def _synthetic_eval(mod, stream, other_trial_sharpes, *, bootstrap_rounds):
    dates, base_net, _days, event_ix, _event_values = stream
    # Stress one extra 1 bp/trade at 2x cost. This is a transparent synthetic
    # stress input, not a claim about any venue's fee schedule.
    event_counts = np.bincount(event_ix, minlength=len(base_net))
    adverse_net = base_net - event_counts * 1e-4

    def rows_for(net):
        equity = float(mod.DEFAULT_CONFIG.e0)
        rows = []
        for date, ret in zip(dates, net, strict=True):
            equity *= 1.0 + float(ret)
            rows.append({"day": str(date.date()), "net_ret": float(ret),
                         "equity": equity})
        return rows

    n_events = len(event_ix)
    fills = [{"participation": 0.001, "notional": 1_000.0,
              "adv20": 1_000_000.0} for _ in range(max(n_events, 1) * 2)]
    base = {"rows": rows_for(base_net), "round_trips": n_events,
            "fills": fills, "mean_hold_days": 3.0}
    adverse = {"rows": rows_for(adverse_net), "round_trips": n_events,
               "fills": fills, "mean_hold_days": 3.0}
    saved_sim, saved_trials = mod.run_both_costs, mod.trial_sharpes
    saved_boot = mod.BOOTSTRAP_ROUNDS
    mod.run_both_costs = lambda _frames, _cfg=None: {"base": base,
                                                      "adverse": adverse}
    mod.trial_sharpes = lambda: list(other_trial_sharpes[:9])
    mod.BOOTSTRAP_ROUNDS = int(bootstrap_rounds)
    extras = list(other_trial_sharpes[9:])
    try:
        return mod.evaluate_frames({}, extra_trials=extras,
                                   as_of="synthetic")
    finally:
        mod.run_both_costs, mod.trial_sharpes = saved_sim, saved_trials
        mod.BOOTSTRAP_ROUNDS = saved_boot


def run_study(*, paths=40, seed=20261025, bootstrap_rounds=64):
    mod = _family_b4b_module()
    rng = np.random.default_rng(seed)
    families = ["iid_gaussian", "student_t3", "garch", "positive_ar",
                "regime_switch"]
    event_counts = [100, 300, 1000, 3000]
    edges = [2, 5, 10, 20, 40, 80, 120, 200]
    rows = []
    # Main power/false-GO grid: the current frozen program-level N is 10.
    for family in families:
        edge_grid = [0] + edges
        for n_events in event_counts:
            for edge in edge_grid:
                go = 0
                for _ in range(paths):
                    candidate, other, _all = _generate_candidate_set(
                        rng, family=family, events=n_events,
                        edge_bps=edge, k=10)
                    result = _synthetic_eval(mod, candidate, other,
                                             bootstrap_rounds=bootstrap_rounds)
                    go += result["status"] == "PASS"
                rows.append({"family": family, "events": n_events,
                             "edge_bps": edge, "N": 10, "paths": paths,
                             "go": int(go), "rate": go / paths})
    # N sensitivity is run on iid null plus a planted 20-bps edge, at each
    # event count; that isolates the DSR multiplicity penalty without
    # multiplying the expensive distributional grid by three.
    for n_trials in (50, 100):
        for n_events in event_counts:
            for edge in (0, 20):
                go = 0
                for _ in range(paths):
                    candidate, other, _all = _generate_candidate_set(
                        rng, family="iid_gaussian", events=n_events,
                        edge_bps=edge, k=n_trials)
                    result = _synthetic_eval(mod, candidate, other,
                                             bootstrap_rounds=bootstrap_rounds)
                    go += result["status"] == "PASS"
                rows.append({"family": "iid_gaussian", "events": n_events,
                             "edge_bps": edge, "N": n_trials,
                             "paths": paths, "go": int(go), "rate": go / paths})
    # Required best-of-K stress. K=10/50 are already in the null grid; add
    # K=200 at the most informative count, 3000 events, with N=200 correction.
    go = 0
    for _ in range(paths):
        candidate, other, _all = _generate_candidate_set(
            rng, family="multiple_testing", events=3000, edge_bps=0, k=200)
        result = _synthetic_eval(mod, candidate, other,
                                 bootstrap_rounds=bootstrap_rounds)
        go += result["status"] == "PASS"
    rows.append({"family": "multiple_testing", "events": 3000,
                 "edge_bps": 0, "N": 200, "paths": paths,
                 "go": int(go), "rate": go / paths})
    return {"seed": seed, "paths": paths,
            "bootstrap_rounds": bootstrap_rounds,
            "current_program_N": 10, "rows": rows}


def _comparison_suite(n=200, seed=20261025):
    from cryptobot.research import slow_stats, stats_edge, verdict

    rng = np.random.default_rng(seed)
    report = {"seed": seed, "cases_per_metric": n, "counts": {},
              "findings": []}
    shapes = ["normal", "t3", "skew", "ar", "ties", "tiny", "empty",
              "nan", "constant"]

    def sample(i, max_n=80):
        mode = shapes[i % len(shapes)]
        size = int(rng.integers(0, max_n + 1))
        if mode == "empty":
            return np.array([], dtype=float)
        if mode == "tiny":
            size = int(rng.integers(0, 3))
        if mode == "constant":
            return np.full(size, float(rng.choice([-1, 0, 1])))
        if mode == "ties":
            return rng.choice([-0.01, 0.0, 0.01], size=size)
        if mode == "t3":
            x = rng.standard_t(3, size=size)
        elif mode == "skew":
            x = rng.exponential(1.0, size=size) - 1.0
        elif mode == "ar":
            x = np.zeros(size)
            for j in range(1, size):
                x[j] = 0.7 * x[j - 1] + rng.normal()
        else:
            x = rng.normal(size=size)
        if mode == "nan" and size:
            x[::7] = np.nan
        return x

    for i in range(n):
        x = sample(i)
        trials = rng.normal(0, 2, size=int(rng.integers(0, 18))).tolist()
        if i % 11 == 0:
            trials.append(float("nan"))
        hold = None if i % 3 == 0 else float(rng.choice([1, 7, 30]))
        prod = slow_stats.dsr_detail(x, trials, hold_days=hold)["dsr"]
        ref = oracle_dsr(x, trials, hold_days=hold)
        if not (math.isnan(prod) and math.isnan(ref)) and not math.isclose(
                prod, ref, rel_tol=2e-8, abs_tol=2e-8):
            report["findings"].append({"metric": "DSR", "case": i,
                                       "production": prod, "oracle": ref})
    report["counts"]["DSR"] = n

    pbo_nonfinite = 0
    for i in range(n):
        k = int(rng.integers(0, 13))
        size = int(rng.integers(0, 65))
        matrix = []
        for j in range(k):
            x = sample(i + j * 3, 64)[:size]
            if i % 19 == 0 and len(x):
                x[0] = np.nan
            matrix.append(x.tolist())
        pbo_nonfinite += int(any(not math.isfinite(v)
                                 for trial in matrix for v in trial))
        parts = int(rng.choice([4, 8]))
        try:
            prod = slow_stats.pbo_cscv(matrix, n_partitions=parts)
            prod_error = None
        except ValueError as exc:
            prod, prod_error = None, str(exc)
        try:
            ref = oracle_pbo(matrix, n_partitions=parts)
            ref_error = None
        except ValueError as exc:
            ref, ref_error = None, str(exc)
        if prod_error != ref_error or (prod_error is None and
                not math.isclose(prod, ref, abs_tol=1e-12)):
            report["findings"].append({"metric": "PBO", "case": i,
                                       "production": prod, "oracle": ref,
                                       "class": "input-validation mismatch"})
    report["counts"]["PBO"] = n
    report["pbo_nonfinite_cases_rejected"] = pbo_nonfinite

    for i in range(n):
        x = sample(i, 72).tolist()
        # Keep NaN cases to expose, not silently sanitize, behavior.
        block = float(rng.choice([1, 2, 5, 15]))
        rounds = 64
        prod = slow_stats.stationary_bootstrap_ci(
            x, lambda v: float(np.mean(v)), mean_block=block,
            rounds=rounds, seed=i + 7, lower_q=0.20)
        ref = oracle_stationary_ci(
            x, mean_block=block, rounds=rounds, seed=i + 7,
            lower_q=0.20)
        for leg, a, b in zip(("lo", "hi"), prod, ref, strict=True):
            if not (math.isnan(a) and math.isnan(b)) and not math.isclose(
                    a, b, rel_tol=1e-12, abs_tol=1e-12):
                report["findings"].append({"metric": "bootstrap_" + leg,
                                           "case": i, "production": a,
                                           "oracle": b})
    report["counts"]["day_block_bootstrap_CI"] = n

    for i in range(n):
        x = sample(i, 100)
        prod = slow_stats.sharpe(x)
        ref = oracle_sharpe(x)
        if not (math.isnan(prod) and math.isnan(ref)) and not math.isclose(
                prod, ref, rel_tol=1e-12, abs_tol=1e-12):
            report["findings"].append({"metric": "Sharpe", "case": i,
                                       "production": prod, "oracle": ref})
    report["counts"]["Sharpe_1x_and_2x_cost_series"] = n

    for i in range(n):
        size = 300
        net = rng.normal(0.5, 12, size=size).tolist()
        extra_cost = rng.uniform(0, 10, size=size)
        adverse = (np.asarray(net) - extra_cost).tolist()
        days = [f"d{j % 3}" for j in range(size)]
        prod = verdict.evaluate_trades(
            net, adverse_bps=adverse, days=days, max_dd_bps=100,
            dd_budget_bps=3500, family_size=1)
        if not math.isclose(prod["expectancy_bps"],
                            sum(net) / len(net), rel_tol=1e-12, abs_tol=1e-12):
            report["findings"].append({"metric": "expectancy_1x", "case": i})
        if not math.isclose(prod["expectancy_adverse_bps"],
                            sum(adverse) / len(adverse), rel_tol=1e-12,
                            abs_tol=1e-12):
            report["findings"].append({"metric": "expectancy_2x", "case": i})
    report["counts"]["expectancy_1x_and_2x_cost"] = n

    for i in range(n):
        dates = pd.date_range("2020-01-01", periods=120, freq="12D", tz="UTC")
        x = sample(i, 120)
        if len(x) < 120:
            x = np.resize(x, 120)
        series = pd.Series(x, index=dates)
        years = [2019, 2020, 2021, 2022, 2023]
        prod = stats_edge.positive_year_count(series, years)
        ref = oracle_positive_year_count(series, years)
        if prod != ref:
            report["findings"].append({"metric": "positive_DEV_year_count",
                                       "case": i, "production": prod,
                                       "oracle": ref})
    report["counts"]["positive_DEV_year_count"] = n
    report["positive_month_rule"] = {
        "independent_metric_cases": n,
        "production_counterpart": None,
        "finding": "No positive-calendar-month-share function or threshold was found in the production gate or reviewed frozen preregistration files; treated as an unimplemented/ambiguous requested rule, not invented here.",
    }
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", action="store_true", help="run 200-case independent comparisons")
    parser.add_argument("--study", action="store_true", help="run the seeded synthetic production-gate study")
    parser.add_argument("--paths", type=int, default=40, help="Monte Carlo paths per study cell")
    parser.add_argument("--bootstrap-rounds", type=int, default=64,
                        help="resamples per synthetic study path; lower than production default for runtime")
    parser.add_argument("--seed", type=int, default=20261025)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    result = {}
    if args.audit or not (args.audit or args.study):
        result["audit"] = _comparison_suite(seed=args.seed)
    if args.study:
        result["study"] = run_study(paths=args.paths, seed=args.seed,
                                    bootstrap_rounds=args.bootstrap_rounds)
    encoded = json.dumps(result, indent=2, sort_keys=True, allow_nan=True)
    if args.out:
        args.out.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0 if not result.get("audit", {}).get("findings") else 1


if __name__ == "__main__":
    raise SystemExit(main())
