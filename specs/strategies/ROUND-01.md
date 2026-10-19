# ROUND-01 freeze record — preregistered research round (Worker 4, 30MIN)

Status: PREREGISTERED. Frozen before any score is observed. Machine
registry: `trials/round-01.json` (generated from
`research/experiments.py::ROUND_01`; the JSON is authoritative on
timestamps). Code registry version 0.4.0 adds `discarded` trial status
and `development`/`holdout` splits.

Plan: 30-minute execution plan, section 7. 11 configurations total
(4 baselines + 5 variants + COMBINED + CASH), strategy v0.1.0,
card/spec parameters frozen (no band/hold/confirmation changes in
this round).

## Configs

| ID | Family | Arm | Role | Mechanism |
|---|---|---|---|---|
| R01-S1 | S1 | S1 | baseline | breakout expansion continues after an executable entry |
| R01-S2 | S2 | S2 | baseline | trend resumption offers sufficient net continuation |
| R01-S3 | S3 | S3 | baseline | range reversion exceeds total costs |
| R01-S4 | S4 | S4 | baseline | measured reclaim supports reversal to the prior range |
| R01-S1-V | S1 | S1-V | variant | vol_z>=1.0 filters false breaks/chasing |
| R01-S1-F | S1 | S1-F | variant | 10-bar buy_frac>=0.58 (real-trade input) filters adverse drift during latency |
| R01-S3-R | S3 | S3-R | variant | width<=120bps + >=2 touches avoids trend-transition fades |
| R01-S3-C | S3 | S3-C | variant | entry-to-mid>=26bps avoids sub-cost ranges |
| R01-S4-S | S4 | S4-S | variant | ablation: does the pierce requirement cost genuine reversals |
| R01-COMBINED | COMBINED | COMBINED | portfolio | single-account bot; must beat the strongest single family |
| R01-CASH | CASH | CASH | benchmark | flat benchmark |

## Excluded (explicit)

- **S5 (whole family): ineligible.** No synchronized depth in scoring
  data: 0 of 8869 eligible seconds on the diagnosis slice, 1.2–1.4M
  `book:never-synced` rows in both banked cells, 0 snapshots installed.
  Reinstate only on depth-enabled captures with sync gating; never on
  invented depth (plan section 5).
- **S2-V, S2-F: deferred**, not rejected. Outside the 12-config cap;
  weaker mechanism priority than S1-V/S1-F for round 1.

## Splits (frozen)

- Development: observed-archive 2026-09-12..2026-10-03. Already viewed:
  diagnostic knowledge only; selection here does not create new evidence.
- Holdout: FRESH uninspected archive coverage, at least 10 complete
  calendar days, defensible chronology + selection history (manager/W2
  to identify post-10-11 or pre-09-12 coverage). If unavailable, report
  the limitation; never manufacture a holdout by renaming a split.
- Purge: 300 s at every boundary (covers 120-bar features + 15 s entry
  delay + 120 s max hold + margin).

## Stopping rule (frozen)

Score each config exactly once per split. Select ONE final candidate on
development BEFORE any holdout inspection. Score the holdout once. No
re-tuning after the holdout look. A negative round (no survivor) is a
valid result — do not add configs until one curve is positive.

Engine gate: no scoring until the corrected IOC execution (W1) and the
frozen cost contract land. Scoring follows corrected execution.

## Trial registry format (v0.4.0)

`TrialRecord{trial_id, exp_id=ROUND-01, arm=config_id, seed, split,
status, reason, utc, metrics}`. Status: `ok` (scored) | `failed`
(errored, error text in reason, stays recorded) | `discarded`
(preregistered but dropped pre-score, e.g. config invalid on the
dataset — reason required, stays recorded). `TrialLog` is append-only;
`failed()`/`discarded()` list non-ok trials. Duplicate trial_ids
rejected.
