"""E5: slow-strategy statistics (reusable, tested).

Walk-forward OOS splits with purge/embargo, stationary block bootstrap,
deflated Sharpe (Bailey-Lopez de Prado 2014), PBO via CSCV, White
reality check, parameter plateau, regime/year breakdowns, drawdown and
tail metrics, capacity estimate. Stdlib + numpy/pandas only.
"""
from __future__ import annotations

import itertools
import math
import random
from typing import Callable

import numpy as np
import pandas as pd

__all__ = ["sharpe", "sortino", "max_drawdown", "stationary_bootstrap_ci",
           "deflated_sharpe", "pbo_cscv", "reality_check_pvalue",
           "walk_forward_splits", "plateau_fraction", "year_breakdown",
           "tail_metrics", "capacity_estimate"]


def sharpe(returns, periods: int = 365) -> float:
    r = np.asarray(list(returns), dtype=float)
    if len(r) < 2:
        return 0.0
    sd = float(r.std(ddof=1))
    if sd <= 0 or sd < 1e-9:
        # Numerically constant series: Sharpe undefined -> 0.
        return 0.0
    return float(r.mean() / sd * math.sqrt(periods))


def sortino(returns, periods: int = 365) -> float:
    r = np.asarray(list(returns), dtype=float)
    if len(r) < 2:
        return 0.0
    downside = r[r < 0]
    if len(downside) < 2:
        return 0.0
    sd = float(downside.std(ddof=1))
    return float(r.mean() / sd * math.sqrt(periods)) if sd > 0 else 0.0


def max_drawdown(returns) -> float:
    """Maximum peak-to-trough depth as a positive fraction."""
    eq = np.cumprod(1.0 + np.asarray(list(returns), dtype=float))
    if len(eq) == 0:
        return 0.0
    return float((1.0 - eq / np.maximum.accumulate(eq)).max())


def _stationary_indices(n: int, mean_block: float, rng: random.Random):
    idx = []
    p = 1.0 / max(mean_block, 1.0)
    while len(idx) < n:
        start = rng.randrange(n)
        length = 1
        while rng.random() > p:
            length += 1
        idx.extend((start + k) % n for k in range(length))
    return idx[:n]


def stationary_bootstrap_ci(values, stat_fn: Callable, *,
                            mean_block: float = 5.0, rounds: int = 1000,
                            alpha: float = 0.05,
                            seed: int = 7) -> tuple[float, float]:
    vals = list(values)
    if not vals:
        return (0.0, 0.0)
    rng = random.Random(seed)
    stats = sorted(float(stat_fn([vals[i] for i in
                                  _stationary_indices(len(vals), mean_block,
                                                      rng)]))
                   for _ in range(rounds))
    lo_i = min(rounds - 1, int(alpha / 2 * rounds))
    hi_i = min(rounds - 1, int((1 - alpha / 2) * rounds))
    return (stats[lo_i], stats[hi_i])


def _phi(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _phi_inv(p: float) -> float:
    """Acklam's inverse-normal approximation (|err| < 1.2e-9)."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0,1)")
    a = [-3.969683028665376e+01, 2.209460984245205e+02,
         -2.759285104469687e+02, 1.383577518672690e+02,
         -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02,
         -1.556989798598866e+02, 6.680131188771972e+01,
         -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01,
         -2.400758277161838e+00, -2.549732539343734e+00,
         4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01,
         2.445134137142996e+00, 3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    if p > phigh:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
        (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)


def deflated_sharpe(selected_returns, trial_sharpes_ann,
                    periods_per_year: int = 365) -> float:
    """Deflated Sharpe ratio (Bailey & Lopez de Prado 2014).

    H0: the selected Sharpe is the max of K chance Sharpes. Returns
    P(SR_true > 0 | data) under the paper's approximations.
    """
    r = np.asarray(list(selected_returns), dtype=float)
    trials = [float(t) for t in trial_sharpes_ann]
    k = len(trials)
    if len(r) < 2:
        return 0.5
    sr = sharpe(r, periods=periods_per_year)
    if k <= 1:
        expected_max = 0.0
    else:
        var_t = float(np.var(trials, ddof=1)) if k >= 2 else 0.0
        if var_t <= 0:
            expected_max = 0.0
        else:
            gamma = 0.5772156649
            expected_max = math.sqrt(var_t) * (
                (1 - gamma) * _phi_inv(1 - 1 / k)
                + gamma * _phi_inv(1 - 1 / (k * math.e)))
    mu, sd = float(r.mean()), float(r.std(ddof=1))
    if sd <= 0:
        return 1.0 if mu > 0 else (0.0 if mu < 0 else 0.5)
    z = (r - mu) / sd
    skew = float((z ** 3).mean())
    kurt = float((z ** 4).mean())  # Pearson (normal = 3)
    var_sr = (1 - skew * sr + (kurt - 1) / 4 * sr ** 2) / len(r)
    if var_sr <= 0:
        return 1.0 if sr > expected_max else 0.0
    return _phi((sr - expected_max) / math.sqrt(var_sr))


def _sharpe_raw(values) -> float:
    v = np.asarray(list(values), dtype=float)
    if len(v) < 2:
        return 0.0
    sd = float(v.std(ddof=1))
    return float(v.mean() / sd) if sd > 0 else 0.0


def pbo_cscv(trial_returns: list[list[float]], *, n_partitions: int = 8,
             seed: int = 7) -> float:
    """Probability of backtest overfitting via CSCV (Lopez de Prado).

    Partitions the history in S blocks; for every half/half split, the
    IS-best trial's OOS Sharpe rank fraction lambda is recorded. PBO =
    fraction of splits with logit(lambda) < 0 (IS-best below OOS median).
    """
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
    for combo in itertools.combinations(range(s), s // 2):
        is_idx = [i for b in combo for i in blocks[b]]
        oos_idx = [i for b in range(s) if b not in combo for i in blocks[b]]
        is_sr = [_sharpe_raw([t[i] for i in is_idx]) for t in trial_returns]
        best = int(np.argmax(is_sr))
        oos_sr = [_sharpe_raw([t[i] for i in oos_idx]) for t in trial_returns]
        rank = 1 + sum(1 for v in oos_sr if v > oos_sr[best])  # 1 = best
        lam = rank / (k + 1)
        total += 1
        if lam > 0.5:  # IS-best in the bottom half OOS (below median)
            below += 1
    # PBO = fraction of splits where the IS-best trial lands below the
    # OOS median. Rank 1 = best, so below-median means lam > 0.5
    # (equivalently logit(lam) > 0). Low PBO = IS skill reproduces OOS.
    return below / total if total else 0.5


def reality_check_pvalue(trial_returns: list[list[float]], *, rounds: int = 500,
                         mean_block: float = 5.0, seed: int = 7) -> float:
    """White (2000) reality check p-value for max mean return (bootstrap)."""
    mat = [np.asarray(list(t), dtype=float) for t in trial_returns]
    n = min(len(t) for t in mat)
    mat = [t[:n] for t in mat]
    observed = max(float(t.mean()) for t in mat)
    centered = [t - t.mean() for t in mat]
    rng = random.Random(seed)
    exceed = 0
    for _ in range(rounds):
        idx = _stationary_indices(n, mean_block, rng)
        m = max(float(t[idx].mean()) for t in centered)
        if m >= observed:
            exceed += 1
    return (1 + exceed) / (rounds + 1)


def walk_forward_splits(dates: pd.DatetimeIndex, *,
                        test_years=(2021, 2022, 2023),
                        purge_days: int = 30,
                        embargo_days: int = 5) -> list[tuple[int, int, int, int]]:
    """Anchored yearly folds: train [start, test_start - purge - embargo).

    In anchored (expanding) mode the embargo extends the purge gap: past
    test blocks legitimately join later trains (all past by then), so a
    separate post-test embargo would only punch holes. Total gap 35d
    covers the longest holding period (B4, 30d) plus margin.
    """
    dates = pd.DatetimeIndex(dates)
    folds = []
    gap = int(purge_days) + int(embargo_days)
    for year in test_years:
        start = pd.Timestamp(f"{year}-01-01", tz=dates.tz)
        stop = pd.Timestamp(f"{year + 1}-01-01", tz=dates.tz)
        te0 = int(dates.searchsorted(start))
        te1 = int(dates.searchsorted(stop)) - 1
        if te1 < te0:
            continue
        cutoff = dates[te0] - pd.Timedelta(days=gap)
        tr1 = int(dates.searchsorted(cutoff)) - 1
        folds.append((0, tr1, te0, te1))
    return folds


def plateau_fraction(cell_sharpes: dict) -> float:
    """Fraction of Hamming-1 neighbors of the best cell with SR > 0."""
    if not cell_sharpes:
        return 0.0
    keys = list(cell_sharpes)
    best = max(keys, key=lambda k: cell_sharpes[k])
    neigh = [k for k in keys if k != best and sum(
        1 for a, b in zip(k, best) if a != b) == 1]
    if not neigh:
        return 1.0
    return sum(1 for k in neigh if cell_sharpes[k] > 0) / len(neigh)


def year_breakdown(daily_returns: pd.Series) -> dict[int, float]:
    out: dict[int, float] = {}
    for year, grp in daily_returns.groupby(daily_returns.index.year):
        out[int(year)] = sharpe(grp.to_numpy())
    return out


def tail_metrics(returns) -> dict[str, float]:
    r = np.asarray(list(returns), dtype=float)
    q = np.quantile(r, [0.01, 0.05]) if len(r) else np.array([0.0, 0.0])
    cvar = {a: float(-r[r <= np.quantile(r, a)].mean()) if len(r) else 0.0
            for a in (0.01, 0.05)}
    z = (r - r.mean()) / r.std(ddof=1) if len(r) >= 2 and r.std(ddof=1) > 0 \
        else np.zeros_like(r)
    worst_month = 0.0
    if len(r) >= 21:
        roll = pd.Series(r).rolling(21).sum().min()
        worst_month = float(roll)
    return {"var_95": float(-q[1]), "var_99": float(-q[0]),
            "cvar_95": cvar[0.05], "cvar_99": cvar[0.01],
            "skew": float((z ** 3).mean()) if len(r) else 0.0,
            "kurt": float((z ** 4).mean()) if len(r) else 0.0,
            "worst_day": float(r.min()) if len(r) else 0.0,
            "worst_month": worst_month}


def capacity_estimate(*, median_adv: float, max_participation: float,
                      gross_turnover_per_year: float) -> float:
    """Max capital s.t. daily traded < max_participation of ADV."""
    return max_participation * median_adv * 365.0 / gross_turnover_per_year
