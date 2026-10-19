# B2 — Cross-sectional momentum, dollar-neutral quantiles

Status: FROZEN-BEFORE-EVALUATION (committed pre-evaluation, Family B 7/8).
Data: DEV lake only. No holdout touch. No lake statistic seen at prereg.

## Economic mechanism

Cross-sectional return continuation: winners keep winning (slow
information diffusion, analyst/attention Gradients across 100s of
small alts) and losers keep losing (overhang, staking unlocks,
neglect). A weekly-rebalanced long-winners/short-losers portfolio
harvests the spread while dollar-neutrality removes beta.

## Counterparty test

Who loses: (a) disposition-effect sellers of winners and holders of
losers (realized vs paper loss asymmetry); (b) passive/index flows
buying whatever is large; (c) sentiment chasers rotating late.
Why it persists: underreaction is behavioral and stable; the alt
universe is too broad for arbitrage capital to close every gap;
short-sale/liquidity frictions protect the short leg. Crowding in the
most obvious names is the failure mode (F2).

## Exact rules

- Universe: top_n=30, min_listing_age_days=90,
  min_quote_volume_30d=$10M, at each weekly rebalance date.
- Signal date: Monday 00:00 UTC. Formation return over F days ending
  Sunday close, skipping the most recent 1 day (Jegadeesh-Titman
  skip-1 adapted to daily): `ret = close[d-1]/close[d-1-F] - 1`.
- Rank eligible symbols by ret; long top quantile, short bottom
  quantile (terciles → 10/10; quintiles → 6/6 of 30).
- CLARIFIED pre-evaluation (D-035): "skip-1" means the formation uses
  closes strictly before the rebalance date (most recent: Sunday close
  for Monday 00:00 UTC execution, formula
  close[d−1]/close[d−1−F]−1). No additional day is skipped: at daily
  frequency with next-open execution the most recent close is already
  one day stale at fill time.
- Equal-weight within each leg; legs dollar-equal (net zero at entry);
  each leg vol-scaled to 10% annualized trailing-60d (portfolio ≈20%).
  Gross ≤ 2×; per-symbol ≤ 25% gross.
- Execution: taker at Monday open. Quantile hysteresis band: a long
  exits only if its rank falls below the 60th (tercile) / 70th
  (quintile) percentile; symmetric for shorts (±10pp band).
- Delisting: exit at last close, no same-week replacement.

## Parameter grid (6 cells, ALL trials counted)

| formation F (days) | quantiles |
|---|---|
| 5, 20, 60 | tercile, quintile |

Weekly rebalance fixed (not gridded).

## Cost model (realistic all-in)

Same as B1: perp taker 7.5bps/side, spread 1bp/side,
slippage max(1bp, 0.5·σ_1d·√(notional/ADV_30d)), funding at observed
settlements, taker-only, 2× adverse doubles fee/spread/slip legs.

## Rebalance / turnover

- Weekly, Monday 00:00 UTC. Turnover budget ≤ 12× one-way annualized.

## Dev promotion (numeric)

Same walk-forward (train→2021/2022/2023, pooled OOS 2021–2023):
Sharpe ≥ 0.7 realistic; > 0.3 at 2×; DSR ≥ 0.8 (trials = 6);
PBO ≤ 0.3; positive ≥2 of 3 OOS years (same 2020-train-only
justification as B1); plateau ≥70% neighbors; DD ≤ 35%;
turnover ≤ 12×. Any miss KILLS B2.

## Confirmation (holdout screen, exactly once, via verdict)

Point > 0.3 and ≥50% dev OOS; 80% LB > −0.3; positive at 2×;
DD in budget; turnover reported; screen-not-proof caveat stated.

## Failure modes

F1: momentum crashes (sharp reversals after crowded runs). F2: short
leg illiquidity (hard-to-borrow/delisting — mitigated by $10M floor).
F3: formation too short (5d ≈ reversal, not momentum — the grid
settles it; a 5d win with 20/60d losses fails plateau honestly).

## Knowledge-contamination note

Same background knowledge as B1. Avoidance: formation windows are
canonical momentum conventions (1wk/1mo/3mo); tercile/quintile sorts
and skip-1 are textbook; no conditioning on recalled alt-seasons or
crashes; weekly cadence chosen for cost control before seeing any
turnover data; written pre-computation (inventory metadata only).
