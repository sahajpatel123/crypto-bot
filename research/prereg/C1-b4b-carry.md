# C1 — B4b delta-neutral carry (pre-authorized)

Status: FROZEN-BEFORE-ANY-FORWARD-READ. Family C, one hypothesis.
This is the only new hypothesis authorized after closeout. Holdout is
BURNED for B4 and any B4 variant, including C1. Holdout bytes are
never decoded for C1. Confirmation is FORWARD data only, dated after
2026-10-17.

## Economic mechanism

When trailing perp funding stays above the round-trip cost of a
hedged book, a spot-long plus perp-short position collects that
funding with near-zero delta. Turnover is limited by construction:
the book is opened only when funding clears a cost hurdle, it is
closed only after that carry falls through a hysteresis band, and
the hedge is resized only when the two legs drift apart.

## Knowledge-contamination note

B4 was killed on a frozen turnover budget after a 50% leg size.
C1 does not loosen that budget and does not reuse the void screen.
The hurdle is the B4 round-trip cost (53 bps), not a number fit on
returns. The confirmation cell below is named in this file before
any forward read and before any DEV sanity run. DEV may be used
after this file is committed, only to check that the rules run and
that the capital table is finite. A DEV result cannot confirm C1.

## Exact rules

- Universe: BTCUSDT and ETHUSDT. Both may be open. Each leg is 50%
  of equity notional. Gross of the four legs is 2.0, the existing
  gross cap.
- Decision clock: 00:00 UTC daily. A rate is eligible only if its
  settlement time is strictly before the decision.
- Trailing funding: median of the 8h funding rate over the previous
  7 days. Annualized carry APR = median_8h × 3 × 365.
- Round trip RT = 53 bps = 0.0053, the B4 identity:
  2×(15 spot + 1 spread + 1 slip) + 2×(7.5 perp + 1 spread + 1 slip).
- Entry hurdle APR = k × RT × 365 / 7. Enter a flat symbol when
  trailing APR > entry hurdle and the median 8h rate is positive.
- Exit hysteresis: after at least 7 decision days in the position,
  exit when trailing APR < 0.5 × entry hurdle for 3 consecutive
  decision days, or when the median 8h rate is negative.
- Rebalance band: while open, submit a hedge adjustment only when
  |spot notional − perp notional| / equity > drift_band. Otherwise
  hold the quantities.
- Execution: taker at the next bar open. No maker. No holdout.

## Confirmation cell (the only cell allowed on FORWARD)

k = 1.5, drift_band = 0.05. This cell is not chosen from a ranking.

## DEV-sanity grid (not a confirmation)

| k | drift_band |
|---|---|
| 1.0, 1.5 | 0.05, 0.10 |

4 cells. All are counted if a DEV sanity run is performed. None of
them can be promoted onto FORWARD. DEV sanity does not read files
dated after 2026-10-17.

## Cost model

Same as B4. Perp taker 7.5 bps/side (5 bps plus a 50% history
buffer). Spot taker 15 bps/side. Spread 1 bp/side. Slippage floor
1 bp, coefficient 0.5. The 2× stress doubles fee, spread, and
slippage. Funding is the observed rate on the short perp and is
not doubled.

## Confirmation (FORWARD only)

Eligible dates are after 2026-10-17. The run waits until it has at
least 90 forward days. Capital base for APR is gross margin
notional (sum of absolute leg notionals).

All three are required:

- 80% block-bootstrap lower bound of net APR > 0
  (`lower_q = 0.20`, the same one-sided bound as Family B).
- Net APR at 2× cost > 0.
- Max drawdown ≤ 2%.

Reported separately, and not substitutes for each other:

- beats_zero: the lower bound above is > 0.
- beats_benchmark_apr: point net APR > benchmark_apr.

benchmark_apr defaults to 0.05. It may be edited only in
`research/configs/C1.toml`, and only before the first forward
evaluation artifact exists.

## Capital feasibility

At 120, 1,000, and 10,000 USDT the machine reports, per symbol,
target notional = 0.5 × equity, quantity rounded to the 0.001 step,
and whether that quantity clears a 6 USDT minimum notional. The
table uses the prices in the evaluation sample. It is not a reason
to change the 50% leg.

## Failure

A miss on any of the three confirmation requirements is FAIL.
Holdout use is a void, not a result. Fewer than 90 forward days
stays unconfirmed; it is not a pass.
