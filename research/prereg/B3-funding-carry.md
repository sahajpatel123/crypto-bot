# B3 — Funding-rate carry tilt (perp-only, + market-neutral variant)

Status: FROZEN-BEFORE-EVALUATION (committed pre-evaluation, Family B 7/8).
Data: DEV lake only (fundingRate + klines 1d). No holdout touch.

## Economic mechanism

Perpetual funding transfers payment from the crowded side to the
contrarian side every 8h. When the predicted funding rate exceeds
round-trip costs by a margin, holding against the crowd earns carry
while price mean-reverts toward spot. The tilt is structural income,
not price prediction.

## Counterparty test

Who loses: leveraged directional traders paying funding for leverage
they cannot otherwise obtain (or obtain more expensively). A
persistently long-biased crowd pays shorts week after week.
Why it persists: demand for crypto leverage is structural and
price-insensitive at the margin; exchanges set funding to clear the
perp/spot gap, guaranteeing the transfer exists whenever positioning
is one-sided. Failure: sustained one-way markets where the adverse
price drift exceeds carry (F1), and crowded carry itself (F3).

## Exact rules

- Universe: top_n=30, min_listing_age_days=90,
  min_quote_volume_30d=$10M, weekly (Monday 00:00 UTC).
- Predicted funding: median of observed 8h funding rates over the
  lookback (7 or 30 days), per symbol, using settlements strictly
  before Monday 00:00 UTC.
- All-in one-way cost C1w = 9.5bps (7.5 fee + 1 spread + 1 slip
  floor); round-trip RT ≈ 19bps. Expected hold ≈ 7 days = 21
  settlements. Breakeven per-settlement ≈ RT/21 ≈ 0.9bp → 1bp unit.
- Entry: if median > +k×1bp → SHORT perp; if < −k×1bp → LONG perp;
  k in {1, 2}. Size: equal-risk sleeves vol-scaled (trailing-60d) to
  20% annualized; gross ≤ 2×; per-symbol ≤ 25%.
- Market-neutral variant (gridded): legs resized to net-zero dollars
  at entry (long notional = short notional); directional variant
  takes all signals as-is.
- Exit (hysteresis band): close when |median| < 0.5×k×1bp at a weekly
  check. Max hold 28 days (forced exit, taker).
- Execution: taker at Monday open; intra-week funding accrues on
  actual positions at observed settlements.

## Parameter grid (8 cells, ALL trials counted)

| funding median lookback | threshold k | market-neutral |
|---|---|---|
| 7d, 30d | 1, 2 | yes, no |

## Cost model (realistic all-in)

B1-identical legs (7.5bps taker/side, 1bp spread/side, sqrt-impact
slip floor 1bp, observed funding, taker-only, 2× adverse on
fee/spread/slip only).

## Rebalance / turnover

- Weekly signal check; positions held between (carry needs time).
- Turnover budget ≤ 6× one-way annualized.

## Dev promotion (numeric)

Walk-forward as B1 (pooled OOS 2021–2023): Sharpe ≥ 0.7; > 0.3 at 2×;
DSR ≥ 0.8 (trials = 8); PBO ≤ 0.3; ≥2 of 3 OOS years (same 2020
justification); plateau ≥70%; DD ≤ 35%; turnover ≤ 6×. Any miss KILLS B3.

## Confirmation (holdout screen, exactly once, via verdict)

Point > 0.3 and ≥50% dev OOS; 80% LB > −0.3; positive at 2×;
DD in budget; turnover reported; screen-not-proof caveat stated.

## Failure modes

F1: trend-vs-carry — one-way market drift dwarfs funding income.
F2: funding regime flip right after entry (median lags). F3: crowded
carry compresses rates to costs (threshold filters this; if nothing
passes, the strategy correctly holds cash — reported, not tuned).

## Knowledge-contamination note

Same background knowledge as B1 (incl. recalled long-biased funding
in 2021 bull, negative funding in 2022 fear). Avoidance: thresholds
are derived from COST arithmetic (RT/21 ≈ 1bp unit), not from
recalled rate levels; lookbacks are 1wk/1mo conventions; the neutral
variant exists for mechanism isolation, not because any backtest
suggested it; written pre-computation.
