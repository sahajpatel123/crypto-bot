# W4 READY-RESEARCH Phase A — Candidate Export (FINAL)

Branch `worker4/ready-research`, worktree `/tmp/cryto-bot-w4-ready`,
base tag `review-0d40ad3-baseline` (=`0d40ad3`). Read-only on current
tree: no src changes; new files are the frozen registry
(`trials/ready-01.json`), diagnostics tooling
(`tools/export_candidates.py`), and outputs. The exporter imports ONLY
market_data + strategies + coordination — never app.session,
research.scoring, or research.funnel — so no clearance-gated module
is touched.

Plan correction honored: projected margin distance is NOT
probability-weighted expectancy. Cost-gap figures below are
threshold-calibration diagnostics only, never edge claims.

## Export + exact reproduction

`tools/export_candidates.py` mirrors the Session feed loop (per-symbol
1s bars, replay clock, 130-bar warmup) and evaluates the pure
`get_adapter('S1'/'S3')` per ready bar-close over each run's own
assembled capture. One budgeted job (1500s cap, 93.6s elapsed,
CHILD_EXIT rc=0), four serialized streams:

| stream | evals | candidates | intents | rejects |
|--------|-------|------------|---------|---------|
| S1 cap-30min | 3337 | 12 | exact | exact (3325) |
| S3 cap-30min | 3337 | 45 | exact | exact (3292) |
| S1 cap-2h | 14138 | 4 | exact | exact (14134) |
| S3 cap-2h | 14138 | 0 | exact | exact (14138) |

Validation: emitted evidence_ref set EQUALS recorded store.db intent
ids, and per-evaluation strategy rejects EQUAL rejections.jsonl
strategy-stage rows (multiset-exact incl. timestamps), all four runs.

## Candidate fields (61 records, `outputs/ready-phasea/candidates.json`)

Per candidate: side, symbol, evidence timestamp, entry band, stop +
target (decoded exit rule), time exit, holding limit, data quality,
projected reward bps (selector formula), itemized estimated costs per
cost-contract-v1 (fees 10.0, spread full 5.0 with half per leg,
slippage 10.0, signed funding +1.0; round-trip 26.0 bps everywhere),
cost gap (reward minus floor), plus observed arrival-bar context
(close, spread, trades, volume — observed, never booked).

Provenance: fee = schedule taker (simulation-labeled); spread,
slippage (incl. modeled 50+50ms latency), funding = conservative
presets; actual funding unknown (conservative unknown). Spread never
double-booked (full 5.0, half per leg).

## H-R1 result (pre-registered BEFORE export numbers seen)

H-R1: fewer than 25% of cost-rejected S1/S3 candidates fall within
5 bps of the floor. OBSERVED: 0/61 within 5 bps (gaps −22.94 to
−12.25, median −21.13; projected rewards 3–13.75 bps vs 26 bps
floor). Rejections are deep, not marginal — H-R1 holds
descriptively. Closest candidate still 12.25 bps short. This is a
calibration fact, not an edge claim.

Context (not booked): observed arrival-bar spreads (~0.04 bps
typical) sit two orders of magnitude below the 5 bps spread preset;
the binding preset terms are fees + slippage (10 bps each). Actual
executable costs await W2 measurements in Phase B.

## Registered for Phase B (frozen `trials/ready-01.json`, 2 hypotheses)

- H-R2 (null): the floor correctly rejects — counterfactual mean net
  markout over intended 30–300s holds ≤ 0; reject only on significant
  positive with full §81 metrics + adverse sensitivity.
- Variant set (fixed): floor multiples {1.00× V0 baseline, 0.75× V1,
  0.50× V2} × {S1, S3} + CASH control. Phase B selects ONE on
  dev/validation, compares vs CASH + unchanged baseline.
- cap-30min/cap-2h + all inspected periods are DEVELOPMENT KNOWLEDGE;
  locked evaluation reserved on genuinely untouched data.

Phase B gated on manager integrating W1 lifecycle + W2 measurements
and saying go. No economics run in Phase A.
