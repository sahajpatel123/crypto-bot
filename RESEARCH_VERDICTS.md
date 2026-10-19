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
| H1 maker OFI scalp | `reports/hypotheses/H1-accrual-01.json` — first live book capture (BTC/ETH, 5,962 snapshots) | 1 fill, −14.07bps (n=1); only 7 snapshots breach frozen 0.6 threshold | 1 | **UNDERPOWERED** (signal-starved on majors; alts are the future universe) |
| H2 trend/vol-regime | `reports/hypotheses/H2.json` — bar-level dev evaluation, 8 symbols, benchmark_30d + 2026-10-12..19 extension | net **+55.94bps/trade** on 290 trades; split-half +81.1 / +30.8bps; sized DD 329bps; +8.8bps equity/day. WARNING: edge concentrated in STRK/W/NEAR; BTC/ETH/SOL/ZEC/XRP negative — no post-hoc symbol dropping permitted | 290 | **UNDERPOWERED** (n<300 by 10 trades; concentration risk open) |
| H3 funding-skew tilt | `reports/hypotheses/H3.json` — bar-level dev evaluation, 8 symbols, benchmark_30d | net −6.62bps/trade (gross +11.38bps), −28.6bps/active day, 28 days | 121 | **UNDERPOWERED** (n<300; net expectancy negative) |

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
