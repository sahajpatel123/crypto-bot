# PILOT-RESULTS-2026-10-17 — single preregistered scoring pass

Prereg: reports/pivot/PILOT-SCORING-PREREG.md (filed BEFORE any pilot
scoring). Data: 29 rank-ordered volatile days, 33.9M events, 0.60GB
(see PILOT-STORAGE-2026-10-17.md). Costs: 26bps realistic + 52bps
adverse. Regime caveat: volatile-regime behavior ONLY; nothing here can
qualify a strategy for capital.

## Verdicts (pooled across 29 days)

| Family | Cell | n | net@26 | hit@26 | net@52 | Verdict |
|---|---|---|---|---|---|---|
| SCALP | 15bps LONG | 939 | -25.37 | 0.026 | -51.37 | PILOT-NONE |
| SCALP | 15bps SHORT | 900 | -26.16 | 0.024 | -52.16 | PILOT-NONE |
| SCALP | 30bps LONG | 104 | -25.92 | 0.058 | -51.92 | PILOT-NONE |
| SCALP | 30bps SHORT | 95 | -26.11 | 0.042 | -52.11 | PILOT-NONE |
| P3-SWING | ALL | 63 | -36.53 | 0.286 | -62.53 | PILOT-NONE |
| P3-SWING | LONG | 37 | -39.22 | 0.243 | -65.22 | PILOT-NONE |
| P3-SWING | SHORT | 26 | -32.71 | 0.346 | -58.71 | PILOT-NONE |
| P2-CARRY | funding-only | 29d | +0.97bps/d vs 40bps target | — | — | P2-PARTIAL |
| P1-MAKER | — | 0 | unevaluable (no quote channel) | — | — | PILOT-BLOCKED |

## Reading (descriptive, not expectancy)
- SCALP gross ≈ 0 (net ≈ -cost to 1bps): 60s trailing momentum has NO
  gross edge on volatile days; 2,038 trades all bleed cost. Hit rate
  2-6% — continuation beyond cost is a tail event, not a tendency.
  Decisive rejection of this config, not a near-miss.
- P3-SWING gross ≈ -10bps: 4h breakouts on volatile days mean-revert
  within the 4h exit window more often than they continue (hit 29%).
  The P3 hypothesis (continuation + low turnover) is not confirmed by
  THIS config; a different entry/exit is a NEW hypothesis needing fresh
  data, not a tweak on this set.
- P2 funding realizes ~1bps/day long-1x vs the 40bps target (2.4%).
  Carry at 1x cannot approach the target; leverage multiplies risk, not
  edge. Full delta-neutral carry still unscored (no hedge leg).
- P1 unscored: needs bookTicker archive (fits in the 9.4GB headroom).

## Integrity notes
- ONE scoring pass per prereg; no thresholds touched after seeing data.
- Execution was optimistic by construction (bar-close fills, zero
  latency): real fills would be worse, so these Nones are robust.
- study-01 per-day files were re-emitted once after a filename collision
  in the scoring harness (deterministic re-execution, same params);
  repooled totals verified IDENTICAL to the first pass (8/8 cells).
- No day dropped, none added post-hoc. Rank #30 (today) skipped as
  unpublished before scoring began.

## What this means for the capital goal
No preregistered config earns a live test. That is the pilot WORKING:
cheap, honest rejection before capital. Paths that remain open (each
needs a FRESH prereg + FRESH data — the 10-day campaign or next month's
volatile days, never re-tuning on this set):
1. P1 maker with bookTicker archive (new channel, new prereg).
2. New P3-style hypotheses (mean-reversion exits? different horizons?)
   preregistered BEFORE touching fresh data.
3. Campaign 10-day set → PIVOT-01 qualification path (unchanged).

Per-day files: reports/pivot/pilot_results/<day>.{s1,s2}.{26,52}.json,
*.s3.json, pooled.json.
