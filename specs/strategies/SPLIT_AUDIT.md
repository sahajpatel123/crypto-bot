# Split-procedure audit — EXP-001/EXP-002 (Worker 1, Q-003 Phase 2)

Scope: `split_indices` (70/5/25 + embargo), seed split, and the runner's
scoring windows. Verdict per directive Sec 3 question, with one blocking
finding for FUTURE return-based evaluation (not for current diagnostics).

## 1. Causal warmup: PASS

Both baselines evaluate only at `t >= 120` with windows ending at `t`
(proven by the `causal_future_mutation_invariant` unit tests). Validation
bars legitimately read train/embargo bars as history — past data is causal.
Scored ranges: train `[120, train_end)`, validation `[val_start, n)`.

## 2. No training outcome crosses into validation: PASS (vacuous)

All strategy parameters are frozen in the preregistered specs; nothing is
fitted. Train/validation differ only in which bars are scored, so there is
no training outcome that could leak.

## 3. Embargo vs label/holding horizons: INSUFFICIENT for future returns

Current EXP metrics (signal counts, reject mix, per-signal cost exposure)
use NO forward labels, so no leakage is possible today. But the 5% embargo
(12 bars at n=240) is far shorter than the actual outcome horizon of a
signal: `holding_limit_s` (120) + `entry_expiry_s` (15) = 135 bars. Any
future trade-return evaluation scored on these splits would leak outcomes
across the boundary.

Required before return-based scoring: purge at least 135 bars after the
train end (not a percentage), or design event-aware splits. The runner
records split boundaries per trial so a purge rule can be audited later.

## 4. Event placement asymmetry (noted, not a defect)

Scenario events sit at fixed bar indices: S1 impulses (150–159) fall in the
train split, S2 resumptions (208–212) in validation. Both splits execute
correctly (EXP-001: 36 signals/arm all-train; EXP-002: 8 signals/arm
all-validation); future work that needs events in both splits must place
them deliberately.

## 5. Seed separation: PASS

Train seeds {11,12,13} / validation {21,22} (EXP-001) and {31,32,33} /
{41,42} (EXP-002) are disjoint; every trial persists its seed plus the
fixture sha256, so inputs are pinned and re-runnable.
