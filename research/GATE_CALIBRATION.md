# G1 — Synthetic Gate Calibration and Statistical Audit

**Status: synthetic evidence only. The gate verdict remains NO-GO.** No strategy result is claimed; no market-return data was read, and the sealed holdout was not opened. No frozen threshold or preregistration was edited.

## Owner takeaway

For the prereg-relevant null (zero net edge after ordinary 1× fixed fees), the 1×/2× B4b production path returned **0 GO out of 200 paths in each of 20 null cells**. The per-cell 95% Wilson upper bound is **1.9%**, so these samples do **not** establish a false-GO rate below 1% (and are not familywise-adjusted). Sensitivity cells at N=50/100 have only five paths each and cannot establish a rate.

No path passed at the requested 2, 5, 10, 20 or 40 bps planted net edges. The raw 80%-pass crossing on the finer N=10 grid was about **50–52 bps net after 1× fixed fees**, near the additional 49-bps fixed-fee stress. These are coarse Monte Carlo estimates, not a validated MDE: power used 25 paths per cell and the 2× stress omits market impact and funding.

A separately labeled diagnostic with zero edge even after the 2× fixed-fee stress produced **23.5–55%** false passes across N=10 null cells. B4b’s adverse-cost leg is Sharpe >0.30; it does not require positive adverse-cost expectancy. That sensitivity is a warning about the gate’s 2× leg, not the prereg-relevant 1×-net-zero null. Neither result changes the current NO-GO verdict.

## Frozen B4b gate and conventions reviewed

The current B4b path in `tools/forward_b4b.py` uses program-level **N=10** (nine trial Sharpes plus the selected candidate), 90 forward days and 20 round trips minimum, Sharpe >=0.70 at 1×, Sharpe >0.30 at 2×, DSR >=0.80, Newey–West t >=2, a stationary-bootstrap lower 20th percentile >0, drawdown <=0.35, and at least two positive eligible years (each with >=60 forward days). The production bootstrap uses 1,000 rounds. Its DSR effective sample size follows the repository convention: the smaller of Bartlett/Newey–West autocorrelation-adjusted n and n/holding-days, bounded by 2 and n; the expected-maximum adjustment uses the finite trial-Sharpe vector (N=10 in B4b).

B4b treats PBO and plateau as structural nulls for a single preregistered cell; it relies on DSR for the selection penalty. It has **no positive-month-share gate**, no frozen month-share threshold, no >=300-trade gate, and no adverse-cost expectancy gate. It has a >=20-round-trip/90-day stopping rule and a 2× Sharpe gate instead. The >=300-trade and positive adverse-expectancy guards are present in the separate generic `verdict.evaluate_trades` path, not B4b. These layers must not be conflated.

B4b’s configured fixed fee increment for its 2× stress is 49 bps per round trip: 2×(15+1) bps spot plus 2×(7.5+1) bps perp. The 53-bps `RT_BPS` value is a hurdle identity, not the fee increment. Synthetic `edge_bps` denotes net return after ordinary 1× fixed fees; the adverse stream subtracts another 49 bps. Market-impact and funding variability are not modeled.

## Independent recomputation

`tools/gate_calibration.py --audit` independently recomputes 200 seeded inputs per statistic using naive loops / `statistics.NormalDist` / literal CSCV enumeration. Inputs include normal, Student-t(3), skewed, autocorrelated, tied, tiny, empty, constant and NaN cases. The DSR audit includes the B4b N=10 convention and the repository’s effective-n rule. Both the B4b stationary bootstrap and the generic gate’s whole-day block bootstrap were checked with 64 seeded resamples.

| Statistic | Inputs | Result after fixes |
|---|---:|---|
| DSR | 200 | 0 disagreements |
| PBO (CSCV) | 200 | 0 disagreements; 60 non-finite inputs rejected by both paths |
| Stationary-bootstrap CI | 200 | 0 disagreements |
| Whole-day block-bootstrap CI | 200 | 0 disagreements |
| Sharpe at 1× and 2× costs | 200 pairs | 0 disagreements |
| Expectancy at 1× and 2× costs | 200 pairs | 0 disagreements |
| Positive DEV-year count | 200 | 0 disagreements |
| Positive-month share | 200 diagnostic calculations | No production counterpart or frozen threshold found |

The initial audit exposed one PBO case where NaN returns had been silently ranked, and two exact-tie year totals where `numpy.nansum` produced a tiny positive residual. The smallest fixes now reject non-finite PBO inputs and use `math.fsum` for calendar-year net before strict-positive classification. Regression tests cover both. No other discrepancy remained after fixes.

## Synthetic size and power study

Command: `PYTHONPATH=src .venv/bin/python tools/gate_calibration.py --study --seed 20261025 --null-basis one_x --out /tmp/g1-primary-final.json`. The full 191-cell default grid completed in **407 seconds**. It injects generated daily returns into B4b’s production `evaluate_frames` path while replacing the market simulator and trial loader with deterministic synthetic streams. The four-year 2020–23 event counts are clustered by synthetic month; trade-noise SD is 20 bps. Null families are iid Gaussian, Student-t(3), GARCH-like, AR(1) with phi=0.45, and zero-mean regime switching. The study is synthetic only.

The study uses 64 bootstrap resamples per path rather than B4b’s production 1,000 to stay within the runtime bound; this makes the Monte Carlo estimates noisier. N=10 null cells use 200 paths; N=10 power cells use 25; N=50/100 sensitivity cells use five. Wilson intervals below are per-cell 95% intervals and are not simultaneous intervals.

### False GO at N=10 (zero net edge after 1× fixed fees)

Each entry is GO/paths; all cells had zero GO (per-cell Wilson upper bound 1.9%).

| Null process | 100 events | 300 events | 1,000 events | 3,000 events |
|---|---:|---:|---:|---:|
| iid Gaussian | 0/200 | 0/200 | 0/200 | 0/200 |
| Student-t(3) | 0/200 | 0/200 | 0/200 | 0/200 |
| GARCH-like | 0/200 | 0/200 | 0/200 | 0/200 |
| Positive AR(1) | 0/200 | 0/200 | 0/200 | 0/200 |
| Zero-mean regime switching | 0/200 | 0/200 | 0/200 | 0/200 |

At N=50 and N=100, each of the 20 null cells per N had 0/5 GO. The corresponding upper bound is about 43%; these are exploratory checks, not evidence of a low false-GO rate. Best-of-K rows were 0/200 for K=10, 0/25 for K=50, and 0/25 for K=200 (upper bounds 1.9%, 13.3%, and 13.3%, respectively).

**Interpretation sensitivity:** when the null is instead defined as zero edge *after the 2× fee stress* (the 1× stream is therefore seeded with +49 bps), N=10 false-GO rates ranged from 47/200 to 110/200 (23.5–55%) over the five null families and four event counts. This demonstrates that the B4b adverse-Sharpe criterion alone does not provide a <1% test at a 2×-neutral boundary. It is separate from the primary null above.

### Power at requested planted net edges

The table summarizes all four event counts (100, 300, 1,000 and 3,000); every cell had zero GO at the requested 2–40 bps edges. N=10 uses 25 paths per cell; N=50 and N=100 use five.

| Net edge after 1× fees | N=10 | N=50 | N=100 |
|---:|---:|---:|---:|
| 2 bps | 0/25 | 0/5 | 0/5 |
| 5 bps | 0/25 | 0/5 | 0/5 |
| 10 bps | 0/25 | 0/5 | 0/5 |
| 20 bps | 0/25 | 0/5 | 0/5 |
| 40 bps | 0/25 | 0/5 | 0/5 |

The extra 49-bps fixed-fee stress makes these edges negative at 2× fees, so the zero power is primarily a consequence of the cost hurdle, not evidence that the statistical legs alone lack power.

### Raw N=10 80%-pass crossing and translations

A finer synthetic edge grid around the 49-bps stress found these raw pass-rate crossings. They use only 25 paths per edge/event cell and should be treated as coarse, non-monotonic Monte Carlo estimates, not an independently calibrated MDE.

| Events over four years | Raw 80% crossing (bps/trade, after 1× fees) | IID Sharpe reference | Mean daily return at 1× | At 3× leverage |
|---:|---:|---:|---:|---:|
| 100 | 52.0 | 13.0 | 0.0356% | 0.1068% |
| 300 | 51.0 | 22.1 | 0.1047% | 0.3142% |
| 1,000 | 50.0 | 39.5 | 0.3422% | 1.0267% |
| 3,000 | 49.8 | 68.1 | 1.0219% | 3.0656% |

Translations assume 20-bps independent per-trade SD, events spread across 1,461 days, no compounding, and linear leverage scaling. They omit impact, funding, leverage constraints, liquidation and path-dependent execution. A daily *average* at 3× near 3% in the 3,000-event row is not evidence of 2–3% “good days”; the two quantities differ, and no market data or strategy was evaluated.

## Guard mutation checks

The fast boundary mutations were killed by these tests. Where B4b has no production leg, the absence is stated rather than filled in with a new threshold.

| Removed/weakened leg | Test that fails under the mutation | Scope / limitation |
|---|---|---|
| DSR threshold | `test_mutation_dsr_guard_rejects_below_frozen_threshold` | Generic promotion guard; B4b’s frozen DSR threshold unchanged |
| PBO threshold | `test_mutation_pbo_guard_rejects_above_frozen_threshold` | Generic promotion guard; B4b PBO is structural-null |
| Bootstrap lower bound | `test_mutation_bootstrap_guard_rejects_lower_bound_even_when_p_passes` | Generic day-block verdict path |
| Positive-year count | `test_mutation_positive_year_guard_rejects_one_of_three` | Generic promotion guard; B4b has a separate positive-year gate |
| n >= 300 | `test_mutation_n300_guard_keeps_299_events_underpowered` | Generic Family C verdict; B4b instead uses 90 days / 20 round trips |
| Positive 2× expectancy | `test_mutation_2x_expectancy_guard_rejects_negative_adverse_mean` | Generic verdict path; B4b has no such expectancy leg, only 2× Sharpe >0.30 |
| Positive-month share | No mutation possible | No production month-share function or frozen threshold found |

These tests demonstrate that each existing generic guard rejects a targeted boundary case; they do **not** estimate a separate counterfactual false-GO rate after deleting each guard. B4b’s missing PBO/month-share/2×-expectancy legs cannot be mutation-tested as production gates. This remains a limitation of the requested “rate increases under each deletion” analysis.

## Checks and boundaries

- `.venv/bin/pytest -q tests/unit/test_gate_calibration.py --basetemp=/tmp/b5043fc7-bt` — **12 passed**.
- `.venv/bin/ruff check src tests` — **0 findings**.
- `git diff --check` — passed.
- Full 191-cell study — passed in 407 seconds; RSS was not measured.
- No full test suite was run locally; CI is the required full-suite authority.
- Synthetic-only use is recorded in `research/DATA_LEDGER.md` (2026-10-25). No real returns, holdout data, API keys or orders were involved.
- Gate thresholds and verdict were not changed: **NO-GO remains NO-GO**.
