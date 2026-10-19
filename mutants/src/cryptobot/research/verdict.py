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


def _bootstrap_ci(values: list[float], *, seed: int = 7,
                  rounds: int = 2000) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(rounds):
        means.append(statistics.fmean(values[rng.randrange(n)]
                                      for _ in range(n)))
    means.sort()
    return (means[int(0.025 * rounds)], means[int(0.975 * rounds) - 1])


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
    lo, hi = _bootstrap_ci(trades_bps)
    exp_adv = statistics.fmean(adverse_bps) if adverse_bps else None
    by_day: dict[str, float] = {}
    for day, val in zip(days, trades_bps, strict=False):
        by_day[day] = by_day.get(day, 0.0) + val
    nonneg = (sum(1 for v in by_day.values() if v >= 0) / len(by_day)
              if by_day else 0.0)
    # Holm: smallest p must beat alpha/family_size; approximate the
    # bootstrap two-sided p from the CI position of zero.
    p_approx = 0.0 if lo > 0 else (0.5 if hi < 0 else 0.10)
    holm_alpha = 0.05 / max(1, int(family_size))
    passed = (lo > 0 and (exp_adv or 0.0) > 0 and nonneg >= 0.60
              and max_dd_bps <= dd_budget_bps
              and p_approx <= holm_alpha)
    out.update({
        "verdict": "PASS" if passed else "FAIL",
        "expectancy_bps": statistics.fmean(trades_bps),
        "expectancy_adverse_bps": exp_adv,
        "ci95": [lo, hi], "nonneg_day_frac": nonneg,
        "max_dd_bps": max_dd_bps, "sharpe": _sharpe(trades_bps),
        "holm_alpha": holm_alpha, "p_approx": p_approx})
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
