# B7 — Low-volatility cross-sectional tilt (dollar-neutral)

Status: FROZEN-BEFORE-EVALUATION (committed pre-evaluation, Family B 7/8).
Data: DEV lake (klines 1d). No holdout touch. No lake statistic seen.

## Economic mechanism

The low-volatility anomaly: high-volatility assets earn lower
risk-adjusted returns (lottery demand overpays for upside; leverage
constraints push investors into high-beta instead of levered low-beta).
A dollar-neutral long-low-vol / short-high-vol portfolio harvests the
spread with low turnover at monthly cadence.

## Counterparty test

Who loses: (a) retail lottery-ticket buyers overpaying for high-vol
alts; (b) leverage-constrained funds bidding up high-beta names they
can hold unlevered; (c) momentum chasers concentrated in the most
volatile names. Why it persists: preferences (skew-loving) and
constraints (no/expensive leverage) are stable features, documented
across decades and asset classes. Failure: short high-vol leg explodes
in melt-ups (F1); anomaly arbitraged in/top-30 mega-caps (F3).

## Exact rules

- Universe: top_n=30, min_listing_age_days=90,
  min_quote_volume_30d=$10M, at each monthly rebalance (first day of
  month, 00:00 UTC; signals from prior month-end close).
- Volatility: trailing window V in {60, 120} days std of daily log
  returns (data ≤ month-end close).
- Rank eligible symbols by σ; long bottom selection, short top
  selection (tercile → 10/10; quintile → 6/6).
- Weighting: equal-weight OR inverse-vol within each leg (gridded);
  legs dollar-equal at entry. Portfolio ≈20% annualized trailing
  vol target via uniform leg scaling; gross ≤ 2×; per-symbol ≤ 25%.
- Execution: taker at the month-open bar. Rebalance band: between
  month-ends, trade only if a leg's weight drifts > 5pp from target
  (else hold; turnover control).
- Delisting: exit at last close, no replacement until next month-end.

## Parameter grid (8 cells, ALL trials counted)

| vol window V (days) | selection | weighting |
|---|---|---|
| 60, 120 | tercile, quintile | equal, inverse-vol |

Monthly rebalance fixed (not gridded).

## Cost model (realistic all-in)

B1-identical (7.5bps taker/side, 1bp spread/side, sqrt-impact slip
floor 1bp, observed funding, taker-only, 2× adverse on
fee/spread/slip).

## Rebalance / turnover

- Monthly. Turnover budget ≤ 4× one-way annualized.

## Dev promotion (numeric)

Walk-forward as B1 (pooled OOS 2021–2023): Sharpe ≥ 0.7; > 0.3 at 2×;
DSR ≥ 0.8 (trials = 8); PBO ≤ 0.3; ≥2 of 3 OOS years (same 2020
justification); plateau ≥70%; DD ≤ 35%; turnover ≤ 4×. Any miss KILLS B7.

## Confirmation (holdout screen, exactly once, via verdict)

Point > 0.3 and ≥50% dev OOS; 80% LB > −0.3; positive at 2×;
DD in budget; turnover reported; screen-not-proof caveat stated.

## Failure modes

F1: short high-vol leg gaps up (melt-up months dominate). F2: the
top-30 universe is too mega-cap for the anomaly (small-alt effect
excluded by construction — honest scope limit). F3: vol ranking lags
regime flips (V=120 slow to adapt; the grid spans it).

## Knowledge-contamination note

Same background knowledge as B1 (incl. recalled alt manias and the
academic low-vol literature). Avoidance: windows/selections are
canonical anomaly-study conventions (2/4-mo vol, tercile/quintile,
monthly rebalance); no recalled "low-vol worked in 2022" tuning —
the DIRECTION is the literature prior, the test is the evidence;
universe/costs mechanical; written pre-computation.
