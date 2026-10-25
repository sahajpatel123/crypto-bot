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
from collections.abc import Callable

import numpy as np
import pandas as pd

__all__ = ["sharpe", "sortino", "max_drawdown", "stationary_bootstrap_ci",
           "deflated_sharpe", "dsr_detail", "acf", "autocorr_adjusted_n",
           "newey_west_tstat", "pbo_cscv", "reality_check_pvalue",
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
                            seed: int = 7,
                            lower_q: float | None = None) -> tuple[float, float]:
    vals = list(values)
    if not vals:
        return (0.0, 0.0)
    rng = random.Random(seed)
    stats = sorted(float(stat_fn([vals[i] for i in
                                  _stationary_indices(len(vals), mean_block,
                                                      rng)]))
                   for _ in range(rounds))
    # lower_q is a one-sided order statistic (0.20 = 80% lower bound).
    # The default remains a two-sided interval at ``alpha``.
    if lower_q is None:
        lo_i = min(rounds - 1, int(alpha / 2 * rounds))
    else:
        lo_i = min(rounds - 1, int(lower_q * rounds))
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


def acf(values, lag: int = 1) -> float:
    """Sample autocorrelation at ``lag`` (0.0 when undefined)."""
    v = np.asarray(list(values), dtype=float)
    v = v[np.isfinite(v)]
    lag = int(lag)
    if len(v) <= lag + 1 or lag < 1:
        return 0.0
    e = v - v.mean()
    g0 = float((e * e).mean())
    if g0 <= 0:
        return 0.0
    return float((e[lag:] * e[:-lag]).mean() / g0)


def autocorr_adjusted_n(returns, *, max_lag: int = 30,
                        hold_days: float | None = None,
                        min_n: float = 2.0) -> float:
    """Effective sample size of a serially dependent return series.

    A daily series from a carry/basis book is mostly exact zeros with
    strongly positive autocorrelation: consecutive days are re-measurements
    of the same open position, not fresh evidence. Counting them as ``n``
    independent draws inflates every t-statistic and pushes the deflated
    Sharpe ratio toward 1 (B4's dev series: 915 days, 75% exact zeros,
    ACF(1)=0.46, iid t=6.96, Newey-West t(30)=2.20, DSR 0.9999998).

    Two estimates are combined, and the smaller wins because the point is
    never to overstate confidence:

    1. Newey-West variance inflation with Bartlett weights,
       ``infl = 1 + 2*sum_{k=1..L} (1 - k/(L+1)) * acf(k)``, hence
       ``n / infl``. The inflation factor is floored at 1.0, so a
       mean-reverting series is never credited with MORE observations
       than it has days.
    2. ``n / hold_days`` when the caller knows the holding period: a
       30-day hold is at most one independent bet per 30 days, whatever
       the day-to-day autocorrelation looks like.

    The result is floored at ``min_n`` (a DSR on one bet is meaningless,
    not small) and capped at ``n``.
    """
    v = np.asarray(list(returns), dtype=float)
    v = v[np.isfinite(v)]
    n = len(v)
    if n < 3:
        return float(n) if n > 0 else 0.0
    lag = max(1, min(int(max_lag), n - 1))
    e = v - v.mean()
    g0 = float((e * e).mean())
    if g0 <= 0:
        return float(n)
    infl = 1.0
    for k in range(1, lag + 1):
        gk = float((e[k:] * e[:-k]).mean())
        infl += 2.0 * (1.0 - k / (lag + 1.0)) * gk / g0
    infl = max(infl, 1.0)
    n_eff = n / infl
    if hold_days is not None and float(hold_days) > 0:
        n_eff = min(n_eff, n / float(hold_days))
    return float(min(max(n_eff, min_n), n))


def newey_west_tstat(values, *, max_lag: int = 30) -> float:
    """t-statistic of the mean under serial dependence (Bartlett kernel)."""
    v = np.asarray(list(values), dtype=float)
    v = v[np.isfinite(v)]
    n = len(v)
    if n < 3:
        return 0.0
    m = float(v.mean())
    e = v - m
    var = float((e * e).mean())
    lag = max(1, min(int(max_lag), n - 1))
    for k in range(1, lag + 1):
        gk = float((e[k:] * e[:-k]).mean())
        var += 2.0 * (1.0 - k / (lag + 1.0)) * gk
    if var <= 0:
        return 0.0 if m == 0 else math.copysign(math.inf, m)
    return m / math.sqrt(var / n)


def dsr_detail(selected_returns, trial_sharpes_ann,
               periods_per_year: int = 365, *,
               max_lag: int = 30, hold_days: float | None = None,
               adjust_n: bool = True) -> dict:
    """Deflated Sharpe ratio with its full intermediate arithmetic.

    Returns ``dsr`` plus the numbers a reader needs to check it: the
    observation count ``n``, the autocorrelation-adjusted ``n_eff`` used
    in place of ``n``, the non-annualized Sharpe, the expected maximum
    from ``len(trial_sharpes_ann)`` trials, and the higher-moment term.
    """
    r = np.asarray(list(selected_returns), dtype=float)
    r = r[np.isfinite(r)]
    n = len(r)
    out = {"n": int(n), "n_eff": float(n), "acf1": 0.0, "sr": 0.0,
           "sr_ann": 0.0, "expected_max": 0.0, "inner": 1.0,
           "skew": 0.0, "kurt": 3.0, "n_trials": 0, "dsr": 0.5}
    if n < 2:
        return out
    mu, sd = float(r.mean()), float(r.std(ddof=1))
    out["acf1"] = acf(r, 1)
    if sd <= 0:
        out["dsr"] = 1.0 if mu > 0 else (0.0 if mu < 0 else 0.5)
        return out
    sr = mu / sd
    out["sr"], out["sr_ann"] = sr, sr * math.sqrt(periods_per_year)
    scale = math.sqrt(periods_per_year)
    trials = [float(t) / scale for t in trial_sharpes_ann
              if math.isfinite(float(t))]
    k = len(trials)
    out["n_trials"] = k
    expected_max = 0.0
    if k > 1:
        var_t = float(np.var(trials, ddof=1))
        if var_t > 0:
            gamma = 0.5772156649
            expected_max = math.sqrt(var_t) * (
                (1 - gamma) * _phi_inv(1 - 1 / k)
                + gamma * _phi_inv(1 - 1 / (k * math.e)))
    out["expected_max"] = expected_max
    z = (r - mu) / sd
    skew = float((z ** 3).mean())
    kurt = float((z ** 4).mean())  # Pearson (normal = 3)
    out["skew"], out["kurt"] = skew, kurt
    inner = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
    out["inner"] = inner
    if inner <= 0:
        out["dsr"] = 1.0 if sr > expected_max else 0.0
        return out
    n_eff = (autocorr_adjusted_n(r, max_lag=max_lag, hold_days=hold_days)
             if adjust_n else float(n))
    out["n_eff"] = n_eff
    stat = (sr - expected_max) * math.sqrt(n_eff - 1) / math.sqrt(inner)
    out["dsr"] = _phi(stat)
    return out


def deflated_sharpe(selected_returns, trial_sharpes_ann,
                    periods_per_year: int = 365, *,
                    max_lag: int = 30, hold_days: float | None = None,
                    adjust_n: bool = True) -> float:
    """Deflated Sharpe ratio (Bailey & Lopez de Prado 2014).

    ``trial_sharpes_ann`` are annualized (the same units ``sharpe()``
    returns). The formula itself uses the non-annualized Sharpe
    mean/std: the sqrt(T-1) factor is derived for that scaling.
    Plugging the annualized number in inflates DSR toward 1.

    Since the fix for the B4 overstatement, the sqrt(T-1) factor uses an
    autocorrelation-adjusted effective sample size
    (:func:`autocorr_adjusted_n`) instead of the raw observation count:
    a 30-day carry measured daily is a few dozen bets, not hundreds of
    independent draws. ``adjust_n=False`` restores the naive count and
    exists only to reproduce the old, overstated numbers.
    """
    return dsr_detail(selected_returns, trial_sharpes_ann,
                      periods_per_year, max_lag=max_lag,
                      hold_days=hold_days,
                      adjust_n=adjust_n)["dsr"]


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
    Non-finite returns make the ranking undefined and are rejected rather
    than silently turning an invalid comparison into a finite PBO.
    """
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
                        embargo_days: int = 5,
                        max_hold_d: int = 0):
    """Anchored yearly folds -> (tr0, tr1, te0, te1, eval0).

    Train is [start, test_start - gap); OOS P&L attribution starts at
    eval0 = test_start + gap (boundary-spanning positions wash out).
    gap = max(purge + embargo, 2 * max_hold_d) per the preregs
    (B3: 56d, B4-30d: 60d, default 35d). In anchored mode the embargo
    extends the purge gap (past tests legitimately join later trains).
    """
    dates = pd.DatetimeIndex(dates)
    folds = []
    gap = max(int(purge_days) + int(embargo_days), 2 * int(max_hold_d))
    for year in test_years:
        start = pd.Timestamp(f"{year}-01-01", tz=dates.tz)
        stop = pd.Timestamp(f"{year + 1}-01-01", tz=dates.tz)
        te0 = int(dates.searchsorted(start))
        te1 = int(dates.searchsorted(stop)) - 1
        if te1 < te0:
            continue
        cutoff = dates[te0] - pd.Timedelta(days=gap)
        tr1 = int(dates.searchsorted(cutoff)) - 1
        eval0 = int(dates.searchsorted(dates[te0] + pd.Timedelta(days=gap)))
        folds.append((0, tr1, te0, te1, eval0))
    return folds


def plateau_fraction(cell_sharpes: dict) -> float:
    """Fraction of Hamming-1 neighbors of the best cell with SR > 0."""
    if not cell_sharpes:
        return 0.0
    keys = list(cell_sharpes)
    best = max(keys, key=lambda k: cell_sharpes[k])
    neigh = [k for k in keys if k != best and sum(
        1 for a, b in zip(k, best, strict=True) if a != b) == 1]
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
