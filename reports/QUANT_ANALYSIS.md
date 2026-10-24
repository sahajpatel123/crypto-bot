# Quant analysis — what it takes to make this bot profitable

Toolkit: `src/cryptobot/research/quant.py` (tests: `tests/unit/test_quant.py`).
Numbers: `tools/quant_report.py` → `reports/quant/C2-quant.json`, on C2's
already-scored daily series (DEV 2022–24, holdout 2025–26, replication
2020–21; 2,396 days). Descriptive: no verdict changes.

## The four equations that decide profitability

1. **Edge after costs** — net = gross − turnover × cost. C2's break-even
   cost is ~100 bps per side against 9 modeled, so costs are not what
   holds C2 back; the signal's size relative to its noise is.
   (Intraday scalps were the opposite: costs ate a gross edge of a few bps.)
2. **Evidence needed** — days ≈ ((z_α + z_power) / SR_daily)². For an annual
   Sharpe of 1, 80% power needs ~2,260 days. Sharpe is the
   time-to-proof dial: Sharpe 2 needs a quarter of that, Sharpe 3 a ninth.
3. **Luck across trials** — the deflated Sharpe ratio compares the best
   Sharpe to what 56 skill-less trials would produce. C2 pooled: PSR 0.994
   but DSR **0.58** (needs ≥ 0.95). After 56 tries, C2 is not
   distinguishable from the best of 56 coin flips.
4. **Sizing** — growth-optimal leverage μ/σ² on the defensible (lower-bound)
   edge, then capped so P(any 20% drawdown) ≤ 5%:
   L ≤ 2μD / (σ² ln(1/p)). C2 pooled: **~0.21x** gross → ~4%/yr expected.

## C2 by period

| | DEV | Holdout | 2020–21 | Pooled |
|---|---|---|---|---|
| mean bps/day | 8.9 | 5.9 | 14.7 | 9.9 |
| Sharpe (annual) | 1.02 | 0.83 | 1.08 | 0.98 |
| kurtosis | 10.9 | 6.9 | 12.1 | 15.0 |
| worst day bps | −1,324 | −741 | −1,619 | −1,619 |
| deflated Sharpe (N=56) | 0.29 | 0.11 | 0.20 | 0.58 |
| min track record (days) | 961 | 1,464 | 809 | 1,013 |
| P(25% drawdown) at 1x | 20% | 20% | 34% | 26% |
| leverage for P(DD20) ≤ 5% | 0.19 | 0.03 | 0.10 | 0.21 |

Stouffer-combined p of the three published period p-values: 0.005.
EXPLORATORY: it ignores the 56-trial search, which the DSR does not.

## Forward test design (fixed before any forward data)

| design | power at measured Sharpe |
|---|---|
| original: 180 days fixed, p ≤ 0.05 | 17% |
| 3-year fixed | 52% |
| betting e-process, daily checks, 3 years | ~19% |
| **group-sequential, looks at 1/2/3 years (adopted)** | **51%** |

Amendment: `research/prereg/C2-forward-amendment-1.md`. The old
"drawdown < 2,500 bps" pass rule was dropped: it fails every historical
period, so it would reject the edge as measured.

Vol-targeting (EWMA, target 150 bps/day): Sharpe 1.02/0.83/1.08 →
1.05/1.05/1.25. Found on read data, so it is only a gated secondary
forward hypothesis. If real, power rises to ~69%.

## What would actually move profitability

- **Higher Sharpe per unit of time, not more backtests.** Information
  ratio ≈ skill × √(independent bets). C2 makes a handful of correlated
  bets a week. A real path needs many independent bets: maker-side
  execution with queue data, or market-neutral carry (long spot / short
  perp), whose risk is mostly funding flips and venue risk, not
  direction. Both need new data or infrastructure (spot leg, full depth
  plus trade prints) and their own preregistration.
- **Stop spending trials.** Each new historical test raises the DSR bar
  for everything; the trial count (56) is now the binding constraint.
- **Size by drawdown, not by conviction.** Even a passing C2 justifies
  ~0.2x gross.
