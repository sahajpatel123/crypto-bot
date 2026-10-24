# Family C — daily/weekly perp portfolio hypotheses (preregistered)

Committed BEFORE any C-family code is run on data. Rationale: every
intraday family (S, X1, H1-H5, B1-B7) died on costs; H2-HIST shows 1h
trend has ~0 gross edge over 2022-2026. Family C moves to horizons where
~18bps round-trip cost is small vs the move, using effects with
published priors in crypto (time-series/cross-sectional momentum,
funding carry, short-term reversal).

## Data
- Prices: Binance USD-M monthly `markPriceKlines` 1h (datasets/history_1h,
  already downloaded for H2-HIST), aggregated to UTC daily closes.
- Funding: Binance USD-M monthly `fundingRate` archive, summed per UTC day.
- Universe: H2-HIST universe B (28 USDT perps). Survivorship caveat: the
  list was chosen in 2026, so it contains survivors; any survivor is a
  live candidate only after forward confirmation.
- A symbol is eligible on day d once it has 35 prior daily closes.

## Split (fixed now)
- DEV: 2022-01-01 .. 2024-12-31. All iteration happens here.
- HOLDOUT: 2025-01-01 .. 2026-08-31. Scored EXACTLY ONCE per hypothesis
  that passes DEV, rules frozen at the DEV commit. Disclosure: H2-HIST
  reported per-year H2 numbers on these years (H2 only); nothing else of
  the holdout has been looked at.

## Execution / cost model (all hypotheses)
- Signals use closes up to day d; positions are held over day d+1
  (close-to-close). No look-ahead.
- Cost per unit of notional traded = taker 5 + half-spread 1 + slippage 3
  = 9 bps per side; 2x adverse = 18 bps. Funding P&L is booked from the
  funding archive (longs pay positive funding).
- Portfolios are normalised to 1.0x gross notional; daily return in bps
  of gross notional is the scoring unit.

## Hypotheses (family of 4 → Holm alpha 0.05/4 = 0.0125)
- C1 TSMOM: each symbol weight ∝ sign(28d return); equal gross per
  symbol. Rebalanced daily.
- C2 XSMOM: long top quintile / short bottom quintile by 28d return,
  equal weight, dollar-neutral. Rebalanced weekly (Mondays).
- C3 CARRY: long bottom quintile / short top quintile by trailing 7d
  summed funding, equal weight, dollar-neutral. Rebalanced weekly.
- C4 REVERSAL: long bottom quintile / short top quintile by prior 1d
  return, dollar-neutral, rebalanced daily.

## DEV pass (all required)
1. Week-block bootstrap CI95 lower bound of mean daily return > 0 at 1x.
2. Mean daily return > 0 at 2x adverse cost.
3. One-sided bootstrap p <= 0.0125 (Holm step 1 for family of 4).
4. Positive mean in each of 2022, 2023, 2024.
5. >= 300 scored days.

## HOLDOUT confirmation (once)
Mean daily return at 1x > 0 with one-sided week-block p <= 0.05, and
mean at 2x adverse > 0. Pass → forward paper on live data (>=30 days,
scored once) before any runtime/arming work. Fail → hypothesis KILLED.
