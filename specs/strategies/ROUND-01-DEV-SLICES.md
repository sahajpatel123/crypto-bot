# ROUND-01 development comparison — PREP ONLY (Worker 4, CORR phase A)

Prepared, NOT run. Phase B executes after Workers 1–3 pass and the
manager says go. Do not widen bands, reduce costs, raise leverage, or
add variants to force profit.

## Compatibility gates (all must hold per slice)

1. Second-resolution trade+quote events (minute marks are incompatible
   with the 1s freshness gate until W3's alignment lands).
2. Depth present for depth-gated families (S5 excluded regardless).
3. Fee/funding/slippage stack = frozen cost contract (W2).
4. Corrected IOC execution (W1 fix in tree).
5. Warm-up/policy identical across cells in a comparison.

## Slice inventory

- synth_quotes / synth_noquotes dev (XRPUSDT, 9,000 usable
  symbol-seconds per 18k prefix): compatible for MECHANISM checks only
  (funnel shape, gate behavior). Economics meaningless. Usable now.
- observed-archive minute marks: INCOMPATIBLE until W3 eligibility
  export + freshness-gate alignment land. Do not score S-strategies on
  60s marks against a 1s gate.
- live-like second-resolution captures with books: compatible IFF W3's
  eligibility export covers them (first event, first usable bar,
  input-class coverage, eligible duration, gap inventory). Pending.

## Phase-B-first batch (4 singles + CASH, per config)

Run from the repo root, each job under `tools/run_budget.py`
(≤25 min working budget, INCOMPLETE not PASS on overrun):

```
backtest --dataset <DATASET> --splits development --armsets S1 \
  --config configs/round01/R01-S1.toml \
  --require-round trials/round-01.json --require-config R01-S1 \
  --out runs/phase-b/R01-S1
# ... R01-S2 (armsets S2), R01-S3 (S3), R01-S4 (S4) analogously ...
backtest --dataset <DATASET> --splits development --armsets CASH \
  --config configs/round01/R01-CASH.toml \
  --require-round trials/round-01.json --require-config R01-CASH \
  --out runs/phase-b/R01-CASH
```

Variant + COMBINED batch: same pattern with
`configs/round01/R01-<V>.toml` + `--require-config R01-<V>` and the
matching family armset (S1 for S1-V/S1-F, S3 for S3-R/S3-C, S4 for
S4-S; COMBINED for R01-COMBINED).

## Trial logging

Every cell logs a TrialRecord (`trial_id=R01-<CFG>-<split>-<seed>`,
`split=development|holdout`, metrics per brief) into the round trial
log. Failed cells keep `status=failed` + error; preregistered-but-
unrunnable cells keep `status=discarded` + reason. Nothing is deleted
or rescored to chase fills.

## Phase-B deliverables per config (brief)

Closed-trade count, eligible hours/days, fill rate, net expectancy ±
uncertainty, gross/net P&L, fees/funding/slippage split, drawdown,
worst trade/day, exposure, holding times, net daily returns incl.
zero-trade days. Estimates separated from booked costs; spread never
deducted twice. Negative results ship with a mechanism-based next
hypothesis, not a widened band.
