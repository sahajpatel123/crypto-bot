"""Phase B sensitivity: setup rates + cost-kill fractions with exact CIs.

Zero-trade compatible: no expectancy is imputed. Setup counts are
Poisson over eligible symbol-seconds; cost-kill fractions are binomial
over setups (Clopper-Pearson). Pure read-only analysis of scored
panels; no params touched.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

PANELS = Path("/tmp/w4-phaseb/panels")
ARMS = ["S1", "S2", "S3", "S4"]


def _poisson_ci(k: int, exposure: float) -> dict:
    """Exact Garwood CI for rate k/exposure (95%)."""
    if exposure <= 0:
        return {"rate": None, "lo": None, "hi": None}
    if k == 0:
        return {"rate": 0.0, "lo": 0.0,
                "hi": -math.log(0.025) / exposure, "method": "garwood-95"}
    from statistics import NormalDist  # noqa: F401 (kept stdlib-only)
    lo = _chi2(2 * k, 0.025) / 2 / exposure
    hi = _chi2(2 * (k + 1), 0.975) / 2 / exposure
    return {"rate": k / exposure, "lo": lo, "hi": hi,
            "method": "garwood-95"}


def _chi2(df: int, p: float) -> float:
    """Wilson-Hilferty approx of chi-square quantile (adequate here)."""
    from statistics import NormalDist
    z = NormalDist().inv_cdf(p)
    t = 1 - 2 / (9 * df) + z * math.sqrt(2 / (9 * df))
    return df * t ** 3


def _clopper_pearson(k: int, n: int) -> dict:
    """Exact 95% CI for binomial proportion (beta quantiles)."""
    if n == 0:
        return {"frac": None, "lo": None, "hi": None,
                "method": "n/a (n=0)"}
    lo = _beta_q(0.025, k, n - k + 1) if k > 0 else 0.0
    hi = _beta_q(0.975, k + 1, n - k) if k < n else 1.0
    return {"frac": k / n, "lo": lo, "hi": hi,
            "method": "clopper-pearson-95"}


def _beta_q(p: float, a: int, b: int) -> float:
    """Beta quantile via bisection on the regularized incomplete beta."""
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if _ibetainc(a, b, mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _ibetainc(a: int, b: int, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    # continued fraction (Numerical Recipes betai)
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                  + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return bt * _betacf(a, b, x) / a
    return 1 - bt * _betacf(b, a, 1 - x) / b


def _betacf(a: int, b: int, x: float) -> float:
    maxit, eps, fpmin = 200, 3e-12, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = fpmin if abs(d) < fpmin else d
    d, c, h = 1.0 / d, 1.0, 1.0 / d
    for m in range(1, maxit + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = fpmin if abs(d) < fpmin else d
        c = 1.0 + aa / c
        c = fpmin if abs(c) < fpmin else c
        d, c = 1.0 / d, c
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = fpmin if abs(d) < fpmin else d
        c = 1.0 + aa / c
        c = fpmin if abs(c) < fpmin else c
        d, c = 1.0 / d, c
        dl = d * c
        h *= dl
        if abs(dl - 1.0) < eps:
            break
    return h


def main() -> int:
    out: dict = {"cells": {}, "cross_slice": {}}
    for slice_ in ("cap30min", "cap2h"):
        for arm in ARMS:
            panel = json.loads(
                (PANELS / f"R01-{arm}-{slice_}.json").read_text())
            st = panel["funnel_stages"]
            elig = st["strategy_eligible_seconds"].get(arm, 0)
            setups = st["setup_unique_intents"]
            killed = panel["funnel_buckets"]["below_cost"]
            total_sym = panel["symbol_time"]["usable_symbol_seconds_total"]
            out["cells"][f"{arm}-{slice_}"] = {
                "setups": setups, "eligible_s": elig,
                "usable_symbol_s": total_sym,
                "coverage_elig_over_usable": (elig / total_sym
                                             if total_sym else None),
                "setup_rate_per_1000_elig_s": {
                    k: (v * 1000 if isinstance(v, (int, float)) else v)
                    for k, v in _poisson_ci(setups, elig).items()
                    if k in ("rate", "lo", "hi")},
                "cost_kill_frac": _clopper_pearson(killed, setups),
                "fills": st["filled_entries"],
            }
    for arm in ARMS:
        a = out["cells"][f"{arm}-cap30min"]
        b = out["cells"][f"{arm}-cap2h"]
        out["cross_slice"][arm] = {
            "setups_30min": a["setups"], "setups_2h": b["setups"],
            "note": "rate comparison via per-cell Garwood CIs above; "
                    "no pooling (different regimes/windows).",
        }
    dest = PANELS / "sensitivity.json"
    dest.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2)[:3000])
    print("wrote", dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
