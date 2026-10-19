# B6 — OI–price divergence regime signal

Status: FROZEN-BEFORE-EVALUATION (committed pre-evaluation, Family B 7/8).
Data: DEV lake (klines 1d + metrics OI daily). No holdout touch.

## Economic mechanism

Open interest measures leveraged participation. Price rising without
OI (weak rally, no sponsorship) and price falling while OI builds
(crowded shorts = squeeze fuel) are divergences between price and
positioning. Fading the divergence bets that positioning, not price,
mean-reverts first.

## Counterparty test

Who loses: late leveraged entrants who build OI at extremes and are
liquidated/squeezed out (longs piling into a stalling rally; shorts
pressing washed-out selloffs). Why it persists: leverage constraints
force exits at the worst time; retail herding rebuilds the pattern
every cycle; OI data is public but underused in systematic rules.
Failure: divergences that resolve by price continuing (F1).

## Exact rules

- Universe: top_n=30, min_listing_age_days=90,
  min_quote_volume_30d=$10M, weekly (Monday 00:00 UTC). Symbols
  without metrics coverage at signal time are ineligible.
- Over window W in {7, 30} days ending Sunday close: r = total log
  return; g = Δlog(sum_open_interest) (daily 00:00 UTC OI series).
  z_r = r / σ_r, z_g = g / σ_g with σ = trailing-90d std of
  non-overlapping W-period changes (min 4 observations for W=7, min 3
  for W=30 — 90 days admit exactly 3 non-overlapping 30d windows, so
  min-4 would structurally silence the W=30 cells; corrected
  pre-evaluation, D-035). Raw (non-demeaned) z-scores per the formula.
  OI "now" is the last 00:00 UTC print strictly before the signal date.
- Divergence D = z_g − z_r. Signal: if |D| > threshold T in {1, 2} →
  direction = −sign(D) (fade the gap: crowded-long build without
  price → SHORT; OI drain on selloff → LONG). Hold exactly 1 week.
- Mode variant: "plain" takes all signals; "+trendfilter" takes only
  signals whose direction agrees with the B1-60d sign for that symbol
  (interaction cell owned by B6; B1 untouched).
- Size: equal-risk sleeves to 20% annualized; gross ≤ 2×; per-symbol
  ≤ 25%. Execution: taker at Monday open.

## Parameter grid (8 cells, ALL trials counted)

| OI window W (days) | threshold T (σ) | mode |
|---|---|---|
| 7, 30 | 1, 2 | plain, +trendfilter |

## Cost model (realistic all-in)

B1-identical (7.5bps taker/side, 1bp spread/side, sqrt-impact slip
floor 1bp, observed funding, taker-only, 2× adverse on
fee/spread/slip).

## Rebalance / turnover

- Weekly signals, 1-week holds, no intraweek trading.
- Turnover budget ≤ 6× one-way annualized.

## Dev promotion (numeric)

Walk-forward as B1 (pooled OOS 2021–2023): Sharpe ≥ 0.7; > 0.3 at 2×;
DSR ≥ 0.8 (trials = 8); PBO ≤ 0.3; ≥2 of 3 OOS years (same 2020
justification); plateau ≥70%; DD ≤ 35%; turnover ≤ 6×. Any miss KILLS B6.

## Confirmation (holdout screen, exactly once, via verdict)

Point > 0.3 and ≥50% dev OOS; 80% LB > −0.3; positive at 2×;
DD in budget; turnover reported; screen-not-proof caveat stated.

## Failure modes

F1: divergence resolves by continuation (crowd right). F2: OI series
breaks (contract migrations, venue methodology changes — mitigated by
per-symbol z-scoring and eligibility; a dead OI series starves that
symbol honestly). F3: +trendfilter inherits B1's whipsaw (reported
separately; plain cells judge the core idea).

## Knowledge-contamination note

Same background knowledge as B1. Avoidance: windows/thresholds are
round statistical conventions (1wk/1mo, 1σ/2σ); the divergence
formula is symmetric (no recalled "OI up + flat price = short"
calibration — the SIGN is the hypothesis, the threshold is round);
no event conditioning; written pre-computation (no OI series seen).
