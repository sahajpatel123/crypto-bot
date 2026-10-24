# H2-HIST — multi-year falsification of H2 (preregistered)

Written and committed BEFORE any download or scoring of this data.

Why: H2's dev result (+56 bps/trade, n=290) comes from 36 inspected days
in one regime, concentrated in 3 of 8 symbols. A real trend/vol-regime
edge should survive years of history it has never seen. This test can
KILL H2; it cannot confirm it (it is still historical, not forward).

Data (never inspected by this project): Binance USD-M public archive,
monthly `markPriceKlines` 1h (same price series family as the dev eval),
2022-01 through 2026-08 (ends before the benchmark_30d window starts
2026-09-12, so there is no overlap with inspected data).

Universes (fixed now):
- A (primary): the dev 8 — BTC ETH SOL ZEC NEAR STRK XRP W (USDT perps),
  each from its first archived month.
- B (secondary, selection-bias check): A plus BNB DOGE ADA AVAX LINK
  LTC DOT BCH TRX ATOM FIL ETC OP ARB APT INJ SUI TIA SEI UNI.

Rules: `research.h_eval.h2_trades` byte-for-byte as committed (EMA20/50,
ATR(14) expanding percentile > 70, entry next open, stop 1.5xATR /
target 3xATR, stop wins ties, 7-day time exit, CostModel defaults:
taker 5+5, spread 2, slippage 6 bps; 2x adverse). No parameter changes.

Scoring: `verdict.evaluate_trades` (day-block bootstrap, family_size=4
for H1-H4), DD reported but not a kill criterion over 4.7 years.

H2 is KILLED (no further work, no tuning) if ANY of, on universe A:
1. day-block bootstrap CI95 lower bound <= 0 bps/trade at 1x cost;
2. mean expectancy <= 0 at 2x adverse cost;
3. mean net expectancy <= 0 in 3 or more of the 5 calendar years
   2022, 2023, 2024, 2025, 2026(Jan-Aug).
Universe B is reported; if B's mean net expectancy <= 0 the result is
flagged "selection-dependent" (H2 not killed, but no live path without
a forward test on B).

If H2 survives: it earns (1) a runtime H2 strategy in Session,
(2) a forward confirmation on data collected after this commit, scored
once, (3) the 14-day pessimistic paper run. Nothing here arms live.
