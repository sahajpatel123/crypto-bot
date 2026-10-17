# RESEARCH VERDICTS — does anything have a real fee-inclusive edge?

**Answer today: no strategy has demonstrated a positive net
expectancy.** A rigorous negative result plus a hardened system is a
successful outcome here; nothing below is dressed up as a pass.

## Evidence (development data only — see research/DATA_LEDGER.md)

| Family | Evidence | Numbers | Trials | Verdict |
|---|---|---|---|---|
| Taker scalps (prior pilot, S-family) | `data/pilot` (DEVELOPMENT, inspected) — audit input, reproduced in STATE.md T0.1 | 0/14 cells positive; best −25.37bps at 26bps round-trip cost | 14 cells | **FAIL** |
| H-R2 (prior benchmark) | `datasets/benchmark_30d` (DEVELOPMENT) | −13.42bps expectancy | — | **FAIL** |
| X1 (prior benchmark) | `datasets/benchmark_30d` (DEVELOPMENT) | 0 fills in 24 cells (F2 latch, since fixed) | 24 cells | **UNDERPOWERED** (measured the latch, not the strategy) |
| H1 maker OFI scalp | `research/prereg/H1-maker-ofi-scalp.md` — preregistered this program, not yet evaluated | — | 0 | **UNDERPOWERED** (unevaluated) |
| H2 trend/vol-regime | `research/prereg/H2-trend-vol-regime.md` — preregistered, not yet evaluated | — | 0 | **UNDERPOWERED** (unevaluated) |
| H3 funding-skew tilt | `research/prereg/H3-funding-skew-tilt.md` — preregistered, not yet evaluated | — | 0 | **UNDERPOWERED** (unevaluated) |

## Why taker scalps fail structurally (T5.1, cost_model_v2)

`cryptobot research cost_model_v2.breakeven_table()`: at 25/25bps
stop/target with a taker entry (~13–18bps round-trip at 1x, more at
1.5x/2x stress), the required win rate exceeds 60–65% before any
alpha — the pilot's best cell (−25.37bps) is what that arithmetic
predicts without a real signal. Maker entry cuts the fee leg
(~2bps/side) but adds queue/adverse-selection risk, which the
conservative queue model in `execution/fill_realism.maker_fill`
(no credit for touches) prices honestly.

## Protocol for any future claim (T5.4/T5.5)

`cryptobot verdict` emits PASS/FAIL/UNDERPOWERED JSON bound to
config/data/code hashes, no manual override. PASS needs bootstrap
CI95 lower bound > 0 at realistic cost, expectancy > 0 at 2x adverse
cost, ≥300 trades, ≥60% non-negative days, drawdown in budget, Holm
correction across the family. Confirmation happens exactly once per
hypothesis on untouched data (the campaign capture, owner-released).

## Recommendation — what to test next (ranked)

1. **H1 maker OFI** on dev data with the pessimistic queue model;
   if dev expectancy ≤ 0 at 1x maker cost, stop — do not tune.
2. **H2 trend/vol-regime**: 26bps is small versus multi-hour moves;
   this family has the best structural prior.
3. **H3 funding tilts** as a filter on H2 rather than standalone.
4. Only a dev PASS earns the single untouched-data confirmation,
   then ≥14 days pessimistic paper (T5.6) before any arm discussion.
