"""Hash-bound PASS/FAIL/UNDERPOWERED verdicts (T5.4/T5.5).

No manual override: the verdict is a pure function of per-trade net
bps (realistic + adverse), day blocks, drawdown and the trial count.
PASS requires ALL of: bootstrap 95% CI lower bound > 0 at realistic
cost, expectancy > 0 at adverse (2x) cost, >=300 trades, >=60%
non-negative days, drawdown within budget. Too few trades is
UNDERPOWERED, never PASS. Holm correction is applied across the
hypothesis family by the caller via ``family_size``.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from pathlib import Path
from typing import Any


def _block_bootstrap(values: list[float], days: list[str], *, seed: int = 7,
                     rounds: int = 2000) -> list[float]:
    """Sorted bootstrap means, resampling whole DAYS with replacement.

    Trades on correlated symbols in the same day are not independent;
    resampling day blocks keeps that dependence instead of overstating
    the sample size the way an iid per-trade bootstrap does.
    """
    if not values:
        return [0.0]
    blocks: dict[str, list[float]] = {}
    for idx, val in enumerate(values):
        key = days[idx] if idx < len(days) and days[idx] else f"#{idx}"
        blocks.setdefault(key, []).append(val)
    groups = list(blocks.values())
    rng = random.Random(seed)
    k = len(groups)
    means: list[float] = []
    for _ in range(rounds):
        total, count = 0.0, 0
        for _ in range(k):
            grp = groups[rng.randrange(k)]
            total += sum(grp)
            count += len(grp)
        means.append(total / count if count else 0.0)
    means.sort()
    return means


def _bootstrap_ci(values: list[float], *, seed: int = 7,
                  rounds: int = 2000,
                  days: list[str] | None = None) -> tuple[float, float]:
    means = _block_bootstrap(values, days or [], seed=seed, rounds=rounds)
    return (means[int(0.025 * len(means))], means[int(0.975 * len(means)) - 1])


def _bootstrap_p(means: list[float]) -> float:
    """One-sided p for H0: expectancy <= 0 (add-one smoothed)."""
    return (sum(1 for m in means if m <= 0.0) + 1) / (len(means) + 1)


def _sharpe(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    sd = statistics.pstdev(values)
    return (statistics.fmean(values) / sd * math.sqrt(len(values))) \
        if sd > 0 else None


def evaluate_trades(trades_bps: list[float], *, adverse_bps: list[float],
                    days: list[str], max_dd_bps: float,
                    dd_budget_bps: float, family_size: int = 1,
                    min_trades: int = 300) -> dict[str, Any]:
    """Compute the verdict for one hypothesis (pure, deterministic)."""
    n = len(trades_bps)
    out: dict[str, Any] = {"n_trades": n, "family_size": int(family_size)}
    if n < min_trades:
        out.update({"verdict": "UNDERPOWERED",
                    "reason": f"n={n} < min_trades={min_trades}",
                    "expectancy_bps": (statistics.fmean(trades_bps)
                                       if trades_bps else None)})
        return out
    means = _block_bootstrap(trades_bps, days)
    lo, hi = means[int(0.025 * len(means))], means[int(0.975 * len(means)) - 1]
    p_value = _bootstrap_p(means)
    exp_adv = statistics.fmean(adverse_bps) if adverse_bps else None
    by_day: dict[str, float] = {}
    for day, val in zip(days, trades_bps, strict=True):
        by_day[day] = by_day.get(day, 0.0) + val
    nonneg = (sum(1 for v in by_day.values() if v >= 0) / len(by_day)
              if by_day else 0.0)
    # Holm across the family: evaluated alone, a hypothesis must beat
    # the strictest step, alpha / family_size (the step-1 threshold).
    # p comes from the day-block bootstrap, never from the CI position.
    holm_alpha = 0.05 / max(1, int(family_size))
    passed = (lo > 0 and (exp_adv or 0.0) > 0 and nonneg >= 0.60
              and max_dd_bps <= dd_budget_bps
              and p_value <= holm_alpha)
    out.update({
        "verdict": "PASS" if passed else "FAIL",
        "expectancy_bps": statistics.fmean(trades_bps),
        "expectancy_adverse_bps": exp_adv,
        "ci95": [lo, hi], "nonneg_day_frac": nonneg,
        "max_dd_bps": max_dd_bps, "sharpe": _sharpe(trades_bps),
        "holm_alpha": holm_alpha, "p_value": p_value,
        "bootstrap": "day-block"})
    return out


def verdict_document(*, hypothesis: str, result: dict[str, Any],
                     config_path: str | Path, data_manifest: str,
                     code_commit: str) -> dict[str, Any]:
    """Bind a verdict to config/data/code hashes (no manual override)."""
    cfg_hash = hashlib.sha256(
        Path(config_path).read_bytes()).hexdigest()[:16] \
        if Path(config_path).exists() else "missing"
    doc = {"hypothesis": hypothesis, **result,
           "hashes": {"config_sha256_16": cfg_hash,
                      "data_manifest": data_manifest,
                      "code_commit": code_commit}}
    doc["document_sha256"] = hashlib.sha256(
        json.dumps(doc, sort_keys=True).encode()).hexdigest()
    return doc
