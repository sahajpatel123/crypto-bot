"""E5: reusable statistics for Family B (no I/O, no holdout access).

Sharpe ratios reported to callers are annualized with 365 periods.
The deflated Sharpe uses the per-period Sharpe (mean/std), matching
Bailey & López de Prado (2014): the sqrt(T-1) factor assumes that
scaling. Raw kurtosis is the non-excess moment (Gaussian = 3).

A 24-month holdout cannot prove a true Sharpe near 1. Screen helpers
below are gates, not proof. See research/prereg/SPLIT.md.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

import numpy as np
import pandas as pd

PERIODS = 365
_EULER = 0.5772156649015329
_NORMAL = NormalDist()

# Preregistered anchors. Hypothesis configs may only tighten a leg or
# substitute the year-count the prereg already adjusted (B1: 2 of 3).
DEV_PROMOTION = {
    "oos_sharpe": 0.7,
    "adverse_sharpe": 0.3,
    "dsr": 0.8,
    "pbo": 0.3,
    "min_positive_years": 3,
    "year_window": 4,
    "plateau": 0.7,
    "max_drawdown": 0.35,
}
HOLDOUT_SCREEN = {
    "point_sharpe": 0.3,
    "dev_fraction": 0.5,
    "lb80": -0.3,
    "adverse_positive": True,
    "max_drawdown": 0.35,
}


def sharpe_ratio(returns, *, periods: int = PERIODS) -> float:
    """Annualized Sharpe. Zero when undefined. +inf only if mean > 0 and std = 0."""
    r = _finite(returns)
    if r.size < 2:
        return 0.0
    sd = float(r.std(ddof=1))
    mu = float(r.mean())
    if sd == 0.0:
        if mu > 0:
            return math.inf
        if mu < 0:
            return -math.inf
        return 0.0
    return mu / sd * math.sqrt(periods)


def period_sharpe(returns) -> float:
    """Non-annualized Sharpe (mean/std). This is the DSR input."""
    r = _finite(returns)
    if r.size < 2:
        return 0.0
    sd = float(r.std(ddof=1))
    if sd == 0.0:
        return 0.0
    return float(r.mean()) / sd


def _finite(returns) -> np.ndarray:
    r = np.asarray(returns, dtype=float).reshape(-1)
    return r[np.isfinite(r)]


def _moments(returns) -> tuple[float, float, float, int]:
    r = _finite(returns)
    n = int(r.size)
    if n < 3:
        return 0.0, 3.0, 0.0, n
    mu = float(r.mean())
    centered = r - mu
    m2 = float(np.mean(centered ** 2))
    if m2 <= 0:
        return 0.0, 3.0, 0.0, n
    m3 = float(np.mean(centered ** 3))
    m4 = float(np.mean(centered ** 4))
    skew = m3 / (m2 ** 1.5)
    kurt = m4 / (m2 ** 2)  # raw
    sr = mu / math.sqrt(m2)
    return skew, kurt, sr, n


def expected_maximum_sharpe(n_trials: int, sr_std: float) -> float:
    """Expected max per-period Sharpe under a zero-mean null (N trials)."""
    if n_trials < 2 or sr_std <= 0 or not math.isfinite(sr_std):
        return 0.0
    z1 = _NORMAL.inv_cdf(1.0 - 1.0 / n_trials)
    z2 = _NORMAL.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    return float(sr_std * ((1.0 - _EULER) * z1 + _EULER * z2))


def deflated_sharpe_ratio(selected_returns, trial_period_sharpes: list[float]) -> float:
    """Probability that the selected Sharpe exceeds the trial-max null.

    ``trial_period_sharpes`` must include every trial in the family,
    selected strategy included. N=1 compares against a zero benchmark.
    """
    skew, kurt, sr, n = _moments(selected_returns)
    if n < 3:
        return 0.0
    trials = [float(x) for x in trial_period_sharpes if math.isfinite(x)]
    n_trials = max(1, len(trials))
    sr_std = float(np.std(trials, ddof=1)) if n_trials >= 2 else 0.0
    sr0 = expected_maximum_sharpe(n_trials, sr_std)
    denom_inner = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr * sr
    if denom_inner <= 1e-12:
        return 0.0
    stat = (sr - sr0) * math.sqrt(n - 1) / math.sqrt(denom_inner)
    if stat > 8:
        return 1.0
    if stat < -8:
        return 0.0
    return float(_NORMAL.cdf(stat))


def max_drawdown(returns) -> float:
    """Positive drawdown magnitude of a simple-return series (0.35 = 35%)."""
    r = _finite(returns)
    if r.size == 0:
        return 0.0
    equity = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(equity)
    dd = 1.0 - equity / peak
    return float(np.max(dd))


def tail_metrics(returns) -> dict[str, float]:
    r = _finite(returns)
    if r.size < 5:
        return {"skew": 0.0, "raw_kurtosis": 3.0, "q05": 0.0, "cvar05": 0.0}
    skew, kurt, _, _ = _moments(r)
    q05 = float(np.quantile(r, 0.05))
    tail = r[r <= q05]
    cvar = float(tail.mean()) if tail.size else q05
    return {"skew": skew, "raw_kurtosis": kurt, "q05": q05, "cvar05": cvar}


def capacity_notional(adv: float, sigma_daily: float, *,
                      slip_budget_bps: float = 5.0, slip_k: float = 0.5,
                      participation_cap: float = 0.01) -> float:
    """Max order notional whose sqrt-impact stays inside the slip budget.

    Also capped at ``participation_cap`` of ADV. Zero when inputs are
    non-positive.
    """
    if adv <= 0 or sigma_daily <= 0 or slip_budget_bps <= 0 or slip_k <= 0:
        return 0.0
    ratio = slip_budget_bps / (slip_k * sigma_daily * 10000.0)
    by_slip = adv * ratio * ratio
    by_part = adv * participation_cap
    return float(max(0.0, min(by_slip, by_part)))


def stationary_indices(n: int, mean_block: int, rng: np.random.Generator) -> np.ndarray:
    """Politis-Romano stationary bootstrap indices (circular)."""
    if n <= 0:
        return np.array([], dtype=int)
    p = 1.0 / max(int(mean_block), 1)
    idx = np.empty(n, dtype=int)
    idx[0] = int(rng.integers(0, n))
    for t in range(1, n):
        if rng.random() < p:
            idx[t] = int(rng.integers(0, n))
        else:
            idx[t] = (idx[t - 1] + 1) % n
    return idx


def bootstrap_sharpe_bounds(returns, *, q_low: float = 0.20, n_boot: int = 400,
                            block: int = 20, seed: int = 0,
                            periods: int = PERIODS) -> dict[str, float]:
    """Stationary-block bootstrap of the annualized Sharpe.

    ``q_low=0.20`` is the 80% lower bound used by the holdout screen.
    """
    r = _finite(returns)
    point = sharpe_ratio(r, periods=periods)
    if r.size < 5:
        return {"point": point, "low": point, "high": point, "n_boot": 0}
    rng = np.random.default_rng(seed)
    stats = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        sample = r[stationary_indices(r.size, block, rng)]
        stats[i] = sharpe_ratio(sample, periods=periods)
    stats.sort()
    lo = int(np.clip(math.floor(q_low * n_boot), 0, n_boot - 1))
    hi = int(np.clip(math.floor((1.0 - q_low) * n_boot), 0, n_boot - 1))
    return {"point": point, "low": float(stats[lo]), "high": float(stats[hi]),
            "n_boot": n_boot, "block": int(block)}


def _column_sharpes(matrix: np.ndarray) -> np.ndarray:
    out = np.zeros(matrix.shape[1], dtype=float)
    for j in range(matrix.shape[1]):
        out[j] = period_sharpe(matrix[:, j])
    return out


def probability_backtest_overfitting(returns_matrix: np.ndarray, *,
                                     n_splits: int = 8) -> float:
    """CSCV probability of backtest overfitting (Bailey et al.).

    ``returns_matrix`` is T x N. PBO is the fraction of symmetric
    train/test splits where the in-sample-best column is at or below
    the out-of-sample median. N=1 returns 0 (no selection).
    """
    mat = np.asarray(returns_matrix, dtype=float)
    if mat.ndim != 2:
        raise ValueError("returns_matrix must be T x N")
    t_obs, n_strat = mat.shape
    if n_strat < 2 or t_obs < n_splits:
        return 0.0
    if n_splits < 2 or n_splits % 2 != 0:
        raise ValueError("n_splits must be even and >= 2")
    usable = (t_obs // n_splits) * n_splits
    mat = mat[:usable]
    slices = np.array_split(mat, n_splits)
    from itertools import combinations
    over = 0
    total = 0
    half = n_splits // 2
    for train_ix in combinations(range(n_splits), half):
        test_ix = [i for i in range(n_splits) if i not in train_ix]
        train = np.concatenate([slices[i] for i in train_ix], axis=0)
        test = np.concatenate([slices[i] for i in test_ix], axis=0)
        is_sr = _column_sharpes(train)
        oos_sr = _column_sharpes(test)
        best = int(np.argmax(is_sr))
        # Rank 0 = worst. Median and below counts as overfit.
        worse = int(np.sum(oos_sr < oos_sr[best]))
        better = int(np.sum(oos_sr > oos_sr[best]))
        tied = n_strat - worse - better
        # Mid-rank of the tied group. omega < 0.5 iff logit < 0.
        # A complete tie sits at 0.5 and is not overfitting.
        mid = worse + (tied - 1) / 2.0
        omega = mid / (n_strat - 1)
        over += int(omega < 0.5)
        total += 1
    return float(over / total) if total else 0.0


def _spa_weights(means: np.ndarray, sigmas: np.ndarray, n_obs: int) -> np.ndarray:
    """Hansen recentering: keep clearly negative means, null-out the rest."""
    thresh = -math.sqrt(2.0 * math.log(math.log(max(n_obs, 3)))) 
    tstats = np.sqrt(n_obs) * means / np.maximum(sigmas, 1e-12)
    keep = tstats < thresh
    return np.where(keep, means, 0.0)


def hansen_spa(returns_matrix: np.ndarray, *, n_boot: int = 300,
               block: int = 20, seed: int = 0) -> dict[str, float]:
    """Hansen SPA p-value for H0: every column has mean <= 0.

    Studentized, recentered. Also reports White's Reality Check p-value
    on the same bootstrap (no studentization, full recentering to 0).
    """
    mat = np.asarray(returns_matrix, dtype=float)
    t_obs, n_strat = mat.shape
    means = mat.mean(axis=0)
    sigmas = mat.std(axis=0, ddof=1)
    sigmas = np.where(sigmas > 0, sigmas, 1e-12)
    t_obs_stat = math.sqrt(t_obs) * means / sigmas
    observed = float(np.max(t_obs_stat))
    observed_white = float(np.max(means))
    recenter = _spa_weights(means, sigmas, t_obs)
    centered_white = mat - means
    centered_spa = mat - recenter
    rng = np.random.default_rng(seed)
    spa_hits = 0
    white_hits = 0
    for _ in range(n_boot):
        idx = stationary_indices(t_obs, block, rng)
        sample_spa = centered_spa[idx]
        sample_white = centered_white[idx]
        spa_t = math.sqrt(t_obs) * sample_spa.mean(axis=0) / sigmas
        if float(np.max(spa_t)) >= observed:
            spa_hits += 1
        if float(np.max(sample_white.mean(axis=0))) >= observed_white:
            white_hits += 1
    return {
        "spa_pvalue": (spa_hits + 1) / (n_boot + 1),
        "white_pvalue": (white_hits + 1) / (n_boot + 1),
        "observed_t": observed,
        "n_boot": n_boot,
    }


def hamming_neighbors(cells: list[dict]) -> dict[str, list[str]]:
    """Map cell id -> ids that differ in exactly one parameter value."""
    if not cells:
        return {}
    keys = sorted({k for c in cells for k in c if k != "id"})
    ids = [c["id"] for c in cells]
    out = {i: [] for i in ids}
    for i, a in enumerate(cells):
        for b in cells[i + 1:]:
            diffs = sum(a.get(k) != b.get(k) for k in keys)
            if diffs == 1:
                out[a["id"]].append(b["id"])
                out[b["id"]].append(a["id"])
    return out


def plateau_fraction(scores: dict[str, float], neighbors: dict[str, list[str]],
                     center: str) -> float:
    """Fraction of Hamming-1 neighbors with score > 0. 1.0 if no neighbors."""
    neigh = neighbors.get(center, [])
    if not neigh:
        return 1.0
    good = sum(1 for n in neigh if scores.get(n, -1.0) > 0.0)
    return good / len(neigh)


@dataclass
class Fold:
    year: int
    train: pd.DatetimeIndex
    test: pd.DatetimeIndex


def anchored_yearly_folds(index: pd.DatetimeIndex, test_years: list[int], *,
                          purge_days: int, embargo_days: int,
                          train_start: str = "2020-01-01") -> list[Fold]:
    """Anchored walk-forward. Test drops the first ``purge_days`` of the
    year. Train ends ``embargo_days`` before the year starts.
    """
    index = pd.DatetimeIndex(index)
    if index.tz is None:
        index = index.tz_localize("UTC")
    else:
        index = index.tz_convert("UTC")
    start = pd.Timestamp(train_start, tz="UTC")
    folds: list[Fold] = []
    for year in test_years:
        year_start = pd.Timestamp(f"{year}-01-01", tz="UTC")
        test_lo = year_start + pd.Timedelta(days=int(purge_days))
        test_hi = pd.Timestamp(f"{year + 1}-01-01", tz="UTC")
        train_hi = year_start - pd.Timedelta(days=int(embargo_days))
        train = index[(index >= start) & (index < train_hi)]
        test = index[(index >= test_lo) & (index < test_hi)]
        folds.append(Fold(year=year, train=train, test=test))
    return folds


def calendar_year_table(returns: pd.Series) -> dict[int, dict[str, float]]:
    series = _as_series(returns)
    out: dict[int, dict[str, float]] = {}
    for year, chunk in series.groupby(series.index.year):
        out[int(year)] = {
            "sharpe": sharpe_ratio(chunk.to_numpy()),
            "net": float(np.nansum(chunk.to_numpy())),
            "n": int(np.isfinite(chunk.to_numpy()).sum()),
        }
    return out


def regime_sharpe(strategy: pd.Series, benchmark: pd.Series, *,
                  window: int = 90) -> dict[str, float]:
    """Bull = trailing ``window`` sum of benchmark > 0, else bear."""
    strat = _as_series(strategy)
    bench = _as_series(benchmark).reindex(strat.index)
    trail = bench.rolling(window, min_periods=window).sum()
    bull = strat[trail > 0]
    bear = strat[trail <= 0]
    return {"bull_sharpe": sharpe_ratio(bull.to_numpy()),
            "bear_sharpe": sharpe_ratio(bear.to_numpy()),
            "bull_n": int(bull.shape[0]), "bear_n": int(bear.shape[0])}


def _as_series(returns) -> pd.Series:
    if isinstance(returns, pd.Series):
        s = returns.copy()
        if not isinstance(s.index, pd.DatetimeIndex):
            raise ValueError("returns series needs a DatetimeIndex")
        if s.index.tz is None:
            s.index = s.index.tz_localize("UTC")
        return s.sort_index()
    raise ValueError("expected a DatetimeIndex Series")


def positive_year_count(returns: pd.Series, years: list[int]) -> int:
    table = calendar_year_table(returns)
    return sum(1 for y in years if table.get(y, {}).get("net", -1.0) > 0.0)


def promotion_failures(*, oos_sharpe: float, adverse_sharpe: float, dsr: float,
                       pbo: float, positive_years: int, plateau: float,
                       max_dd: float, turnover: float, turnover_budget: float,
                       anchors: dict | None = None) -> list[str]:
    """Names of failed DEV-promotion legs. Empty means the cell passes."""
    a = dict(DEV_PROMOTION)
    if anchors:
        a.update(anchors)
    fails: list[str] = []
    if not (oos_sharpe >= a["oos_sharpe"]):
        fails.append(f"oos_sharpe {oos_sharpe:.3f} < {a['oos_sharpe']}")
    if not (adverse_sharpe > a["adverse_sharpe"]):
        fails.append(f"adverse_sharpe {adverse_sharpe:.3f} <= {a['adverse_sharpe']}")
    if not (dsr >= a["dsr"]):
        fails.append(f"dsr {dsr:.3f} < {a['dsr']}")
    if not (pbo <= a["pbo"]):
        fails.append(f"pbo {pbo:.3f} > {a['pbo']}")
    need = int(a["min_positive_years"])
    if positive_years < need:
        fails.append(f"positive_years {positive_years} < {need}")
    if not (plateau >= a["plateau"]):
        fails.append(f"plateau {plateau:.3f} < {a['plateau']}")
    if not (max_dd <= a["max_drawdown"]):
        fails.append(f"max_dd {max_dd:.3f} > {a['max_drawdown']}")
    if turnover > turnover_budget:
        fails.append(f"turnover {turnover:.3f} > {turnover_budget}")
    return fails


def holdout_screen_failures(*, point_sharpe: float, dev_oos_sharpe: float,
                            lb80: float, adverse_sharpe: float, max_dd: float,
                            anchors: dict | None = None) -> list[str]:
    """Holdout is a screen. Failures are permanent for that hypothesis."""
    a = dict(HOLDOUT_SCREEN)
    if anchors:
        a.update(anchors)
    fails: list[str] = []
    if not (point_sharpe > a["point_sharpe"]):
        fails.append(f"point_sharpe {point_sharpe:.3f} <= {a['point_sharpe']}")
    floor = a["dev_fraction"] * dev_oos_sharpe
    if not (point_sharpe >= floor):
        fails.append(
            f"point_sharpe {point_sharpe:.3f} < {a['dev_fraction']}*dev "
            f"({floor:.3f})")
    if not (lb80 > a["lb80"]):
        fails.append(f"lb80 {lb80:.3f} <= {a['lb80']}")
    if not (adverse_sharpe > 0.0):
        fails.append(f"adverse_sharpe {adverse_sharpe:.3f} <= 0")
    if not (max_dd <= a["max_drawdown"]):
        fails.append(f"max_dd {max_dd:.3f} > {a['max_drawdown']}")
    return fails


__all__ = [
    "PERIODS", "DEV_PROMOTION", "HOLDOUT_SCREEN", "Fold",
    "sharpe_ratio", "period_sharpe", "expected_maximum_sharpe",
    "deflated_sharpe_ratio", "max_drawdown", "tail_metrics",
    "capacity_notional", "stationary_indices", "bootstrap_sharpe_bounds",
    "probability_backtest_overfitting", "hansen_spa", "hamming_neighbors",
    "plateau_fraction", "anchored_yearly_folds", "calendar_year_table",
    "regime_sharpe", "positive_year_count", "promotion_failures",
    "holdout_screen_failures",
]
