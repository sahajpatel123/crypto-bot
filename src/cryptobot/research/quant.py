"""Quant toolkit: how much evidence an edge needs, and how hard to bet it.

Pure functions, stdlib only. Conventions: a "period" is one observation
(a day for Family C); Sharpe ratios are per period unless the name says
``annual``; returns are in any consistent unit (bps here).

References
- Probabilistic / Deflated Sharpe, MinTRL: Bailey & Lopez de Prado,
  "The Sharpe Ratio Efficient Frontier" (2012), "The Deflated Sharpe
  Ratio" (2014).
- Anytime-valid test (betting e-process, aGRAPA bet): Waudby-Smith &
  Ramdas, "Estimating means of bounded random variables by betting"
  (JRSS-B 2023). Ville's inequality makes P(sup_t K_t >= 1/alpha) <= alpha
  under H0, so the wealth may be inspected every day without inflating
  the false-positive rate.
- Drawdown of drifted Brownian motion: P(ever fall D below the running
  peak... from a fixed start) = exp(-2 mu D / sigma^2) for mu > 0.
"""
from __future__ import annotations

import math
import random
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

_N = statistics.NormalDist()
EULER_GAMMA = 0.5772156649015329


@dataclass(frozen=True)
class Moments:
    n: int
    mean: float
    sd: float
    skew: float
    kurt: float  # raw (non-excess) kurtosis; normal = 3

    @property
    def sharpe(self) -> float:
        return self.mean / self.sd if self.sd else 0.0


def moments(xs: Sequence[float]) -> Moments:
    n = len(xs)
    if n < 2:
        raise ValueError("need at least 2 observations")
    mu = statistics.fmean(xs)
    sd = statistics.pstdev(xs)
    if sd == 0:
        return Moments(n, mu, 0.0, 0.0, 3.0)
    skew = sum((x - mu) ** 3 for x in xs) / n / sd ** 3
    kurt = sum((x - mu) ** 4 for x in xs) / n / sd ** 4
    return Moments(n, mu, sd, skew, kurt)


def annualize_sharpe(sr: float, periods_per_year: float = 365.0) -> float:
    return sr * math.sqrt(periods_per_year)


def _sr_se(sr: float, n: int, skew: float, kurt: float) -> float:
    """Std error of a per-period Sharpe estimate under non-normal returns."""
    var = (1 - skew * sr + (kurt - 1) / 4 * sr * sr) / (n - 1)
    return math.sqrt(max(var, 1e-18))


def probabilistic_sharpe(m: Moments, sr_benchmark: float = 0.0) -> float:
    """P(true per-period Sharpe > sr_benchmark | sample). PSR."""
    return _N.cdf((m.sharpe - sr_benchmark) / _sr_se(m.sharpe, m.n, m.skew, m.kurt))


def expected_max_sharpe(n_trials: int, sr_variance: float) -> float:
    """E[max per-period Sharpe] across n_trials skill-less strategies."""
    if n_trials < 2:
        return 0.0
    a = _N.inv_cdf(1 - 1 / n_trials)
    b = _N.inv_cdf(1 - 1 / (n_trials * math.e))
    return math.sqrt(sr_variance) * ((1 - EULER_GAMMA) * a + EULER_GAMMA * b)


def deflated_sharpe(m: Moments, n_trials: int, sr_variance: float | None = None) -> float:
    """PSR against the best Sharpe luck alone produces over n_trials.

    sr_variance defaults to the sampling variance of a zero Sharpe at
    this sample size (1/n) — appropriate when the other trials' Sharpes
    were not all recorded.
    """
    var = sr_variance if sr_variance is not None else 1.0 / m.n
    return probabilistic_sharpe(m, expected_max_sharpe(n_trials, var))


def min_track_record(m: Moments, sr_benchmark: float = 0.0, alpha: float = 0.05) -> float:
    """Observations needed for PSR >= 1 - alpha at the observed moments."""
    if m.sharpe <= sr_benchmark:
        return math.inf
    z = _N.inv_cdf(1 - alpha)
    return 1 + (1 - m.skew * m.sharpe + (m.kurt - 1) / 4 * m.sharpe ** 2) * (
        z / (m.sharpe - sr_benchmark)) ** 2


def required_periods(sr_annual: float, *, alpha: float = 0.05, power: float = 0.8,
                     periods_per_year: float = 365.0) -> float:
    """Periods a one-sided fixed-sample test needs to detect sr_annual."""
    sr = sr_annual / math.sqrt(periods_per_year)
    if sr <= 0:
        return math.inf
    return ((_N.inv_cdf(1 - alpha) + _N.inv_cdf(power)) / sr) ** 2


def power_at(sr_annual: float, n: int, *, alpha: float = 0.05,
               periods_per_year: float = 365.0) -> float:
    """Power of a one-sided fixed-sample mean test after n periods."""
    sr = sr_annual / math.sqrt(periods_per_year)
    return _N.cdf(sr * math.sqrt(n) - _N.inv_cdf(1 - alpha))


def stouffer(p_values: Iterable[float], weights: Iterable[float] | None = None) -> float:
    """Combined one-sided p of independent tests (weighted Stouffer Z)."""
    ps = list(p_values)
    ws = list(weights) if weights is not None else [1.0] * len(ps)
    z = sum(w * _N.inv_cdf(1 - p) for w, p in zip(ws, ps, strict=True))
    return 1 - _N.cdf(z / math.sqrt(sum(w * w for w in ws)))


# -- group-sequential design --------------------------------------------------

def _crossing_prob(bounds: Sequence[float], fracs: Sequence[float],
                   drift: float = 0.0, sims: int = 100_000, seed: int = 0) -> float:
    """P(Z_k >= bounds[k] at some look) for the score process at info fracs.

    Z_k = B(f_k)/sqrt(f_k) + drift*sqrt(f_k), B standard Brownian motion;
    drift is the z the final look would have in expectation. Common
    random numbers (fixed seed) make it smooth in the bounds.
    """
    rng = random.Random(seed)
    hits = 0
    for _ in range(sims):
        b, prev = 0.0, 0.0
        for c, f in zip(bounds, fracs, strict=True):
            b += rng.gauss(0.0, math.sqrt(f - prev))
            prev = f
            if b / math.sqrt(f) + drift * math.sqrt(f) >= c:
                hits += 1
                break
    return hits / sims


def obf_bounds(n_looks: int, alpha: float = 0.05, sims: int = 100_000) -> list[float]:
    """One-sided O'Brien-Fleming z bounds for equally spaced looks.

    c_k = C * sqrt(K / k), C solved so the overall false-positive rate is
    alpha. Very strict early, close to the fixed-sample bound at the end.
    """
    fracs = [k / n_looks for k in range(1, n_looks + 1)]
    lo, hi = _N.inv_cdf(1 - alpha), 6.0
    for _ in range(40):
        mid = (lo + hi) / 2
        bounds = [mid * math.sqrt(n_looks / k) for k in range(1, n_looks + 1)]
        if _crossing_prob(bounds, fracs, sims=sims) > alpha:
            lo = mid
        else:
            hi = mid
    return [hi * math.sqrt(n_looks / k) for k in range(1, n_looks + 1)]


def sequential_power(sr_annual: float, look_periods: Sequence[int], bounds: Sequence[float],
                     periods_per_year: float = 365.0, sims: int = 100_000) -> float:
    """Power of a group-sequential one-sided test with these looks/bounds."""
    n_max = look_periods[-1]
    drift = sr_annual / math.sqrt(periods_per_year) * math.sqrt(n_max)
    fracs = [n / n_max for n in look_periods]
    return _crossing_prob(bounds, fracs, drift=drift, sims=sims, seed=1)


# -- sizing -----------------------------------------------------------------

def kelly_leverage(mean: float, sd: float, n: int | None = None, z: float = 0.0) -> float:
    """Growth-optimal leverage mu/sigma^2, using the mean's lower bound.

    With n and z > 0 the mean is replaced by mean - z*sd/sqrt(n): betting
    the edge you can defend, not the edge you measured. Never negative.
    Units: mean and sd as fractions of capital per period.
    """
    mu = mean - (z * sd / math.sqrt(n) if n and z else 0.0)
    return max(0.0, mu / (sd * sd)) if sd else 0.0


def log_growth(leverage: float, mean: float, sd: float) -> float:
    """Per-period expected log growth at a leverage (continuous approx)."""
    return leverage * mean - (leverage * sd) ** 2 / 2


def vol_target_leverage(recent: Sequence[float], target_sd: float,
                        cap: float = 1.0, halflife: float = 20.0) -> float:
    """EWMA-vol scaling: leverage that targets target_sd per period."""
    if not recent:
        return 0.0
    k = 1 - 0.5 ** (1 / halflife)
    var = recent[0] ** 2
    for x in recent[1:]:
        var = (1 - k) * var + k * x * x
    return min(cap, target_sd / math.sqrt(var)) if var > 0 else cap


def prob_drawdown(mean: float, sd: float, depth: float) -> float:
    """P(equity ever falls `depth` below a given peak), Brownian approx.

    Same units for all three (e.g. fraction of capital per period and a
    fractional depth). 1.0 when the drift is not positive.
    """
    if mean <= 0:
        return 1.0
    return math.exp(-2 * mean * depth / (sd * sd))


def drawdown_capped_leverage(mean: float, sd: float, depth: float, prob: float) -> float:
    """Largest leverage L with prob_drawdown(L*mean, L*sd, depth) <= prob.

    exp(-2 L mu D / (L sigma)^2) <= p  <=>  L <= 2 mu D / (sigma^2 ln(1/p)).
    Feed it a conservative (lower-bound) mean. 0 when the drift is not positive.
    """
    if mean <= 0 or sd <= 0:
        return 0.0
    return 2 * mean * depth / (sd * sd * math.log(1 / prob))


def breakeven_cost(mean_gross: float, mean_turnover: float) -> float:
    """Cost per unit notional traded at which the net mean is zero."""
    return mean_gross / mean_turnover if mean_turnover > 0 else math.inf


# -- anytime-valid test ------------------------------------------------------

@dataclass
class EProcess:
    """One-sided betting e-process for H0: E[x] <= 0.

    Each observation is mapped to y = max(-1, min(x, bound) / bound) in
    [-1, 1]; wealth K *= 1 + lam * y with lam predictable in [0, lam_cap].
    lam_cap < 1 keeps K > 0. Because lam >= 0 and E[y] <= 0 under H0,
    K is a nonnegative supermartingale, so P(ever K >= 1/alpha) <= alpha.
    Clipping gains at +bound is conservative; losses beyond -bound are
    floored and must be handled by the study's operational stop.
    """

    bound: float
    lam_cap: float = 0.5
    wealth: float = 1.0
    n: int = 0
    _sum: float = 0.0
    _sumsq: float = 0.0
    peak: float = 1.0

    def bet(self) -> float:
        """aGRAPA plug-in bet from data seen so far (prior: mean 0, var 1/4)."""
        n = self.n
        mu = self._sum / (n + 1)
        var = (0.25 + self._sumsq - self._sum ** 2 / max(n, 1)) / (n + 1)
        return min(self.lam_cap, max(0.0, mu / (var + mu * mu)))

    def update(self, x: float) -> float:
        y = max(-1.0, min(x, self.bound) / self.bound)
        self.wealth *= 1 + self.bet() * y
        self.n += 1
        self._sum += y
        self._sumsq += y * y
        self.peak = max(self.peak, self.wealth)
        return self.wealth

    def rejected(self, alpha: float = 0.05) -> bool:
        """True once the running max wealth has reached 1/alpha."""
        return self.peak >= 1 / alpha


def e_process(xs: Iterable[float], bound: float, lam_cap: float = 0.5) -> EProcess:
    ep = EProcess(bound=bound, lam_cap=lam_cap)
    for x in xs:
        ep.update(x)
    return ep
