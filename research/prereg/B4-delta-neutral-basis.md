# B4 — Delta-neutral basis capture (spot long + perp short)

Status: FROZEN-BEFORE-EVALUATION (committed pre-evaluation, Family B 7/8).
Data: DEV lake (spot 1d BTC/ETH + UM fundingRate + UM klines 1d).
FLAG: needs a spot leg in the engine; backtest-only in this run. A
SCREEN_PASS would require E7 spot-leg support before any paper/live
use; without it the hypothesis cannot advance past the screen.

## Economic mechanism

When perp funding is richly positive, short-perp + long-spot earns the
funding stream with near-zero delta. The trade warehouses the gap
between leveraged-long demand (perp) and spot holders. Unwind at
funding normalization or max hold; the P&L is carry minus 4-leg
turnover costs.

## Counterparty test

Who loses: leveraged perp longs paying funding (same pool as B3) plus
impatient basis traders unwinding early. Why it persists: spot/perp
segmentation (margin, custody, venue access) plus structural leverage
demand keep funding positive on average; the basis cannot be arbed to
zero by capital that cannot hold both legs. Failure: spot/perp flow
decoupling (F1), negative-flip whipsaw (F2), 4-leg costs (F3).

## Exact rules

- Universe: BTCUSDT + ETHUSDT ONLY (spot data pulled for these two;
  documented scope limit, not cherry-picking: the two deepest basis
  markets by construction).
- Predicted funding: median 8h rate over trailing 7 days, per symbol,
  settlements strictly before the daily check (00:00 UTC).
- All-in round-trip both legs: 2×(15 spot + 1 spread + 1 slip) +
  2×(7.5 perp + 1 spread + 1 slip) = 34 + 19 = 53bps (spot taker
  15bps = 10bps VIP0 + 50%). CORRECTED pre-evaluation (D-035): the
  committed text said 49bps, undercounting spread+slip on one leg.
- Entry: if median_8h × 3 × max_hold_days > k × 53bps → open
  delta-neutral (long spot notional = short perp notional);
  k in {1.5, 2, 3}; max_hold_days in {7, 14, 30}.
- Exit: funding negative for 3 consecutive settlements, or max hold
  reached, or symbol data ends (delist guard, n/a for BTC/ETH but coded).
- No-trade band: no re-entry within 3 days of an exit (same symbol).
- Execution: both legs taker at next daily open; funding accrues on the
  short perp at observed settlements; spot earns no funding.
- Sizing: each pair position ≤ 50% equity notional per leg; gross
  (spot+perp notionals) ≤ 2× equity.

## Parameter grid (9 cells, ALL trials counted)

| threshold k | max hold (days) |
|---|---|
| 1.5, 2, 3 | 7, 14, 30 |

## Cost model

As above with spot taker 15bps/side; perp legs as B1; 2× adverse
doubles fee/spread/slip (funding observed). Taker-only.

## Rebalance / turnover

- Daily 00:00 UTC check; positions held to exit trigger.
- Turnover budget ≤ 12× one-way annualized (4 legs per round trip).

## Dev promotion (numeric)

Walk-forward as B1 (pooled OOS 2021–2023): Sharpe ≥ 0.7; > 0.3 at 2×;
DSR ≥ 0.8 (trials = 9); PBO ≤ 0.3; ≥2 of 3 OOS years (same 2020
justification); plateau ≥70%; DD ≤ 35%; turnover ≤ 12×. Any miss KILLS B4.
Note: with 2 symbols, year-positivity and plateau carry extra weight;
a single-pair fluke cannot pass plateau honestly.

## Confirmation (holdout screen, exactly once, via verdict)

Point > 0.3 and ≥50% dev OOS; 80% LB > −0.3; positive at 2×;
DD in budget; turnover reported; screen-not-proof caveat stated.
A SCREEN_PASS advances to SLOW_ENGINE_DESIGN spot-leg work, NOT to
paper (no spot execution path exists).

## Failure modes

F1: basis regime where funding stays rich but spot lags perp on
spikes (tracking error). F2: negative-flip whipsaw around the exit
rule. F3: 49bps round-trip needs genuinely rich funding; thin
periods correctly sit in cash (reported).

## Knowledge-contamination note

Same background knowledge as B1 (incl. recalled rich 2021 funding,
flat 2023 funding). Avoidance: k multiples of measured COST (49bps),
not recalled funding levels; holds are 1/2/4-week conventions;
BTC+ETH scope is a liquidity prior (deepest markets), fixed before
seeing any basis series; no date-conditioned rules; written
pre-computation.
