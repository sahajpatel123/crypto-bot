# W4 CORR-STRAT Phase B — Economic Scoring (FINAL)

Branch `worker4/corr-scoring`, worktree `/tmp/cryto-bot-w4-phaseb`,
base origin/main @ `3b83d7c`. Every cell gated with
`--require-round trials/round-01.json --require-config R01-*`
(sha `f08fa9c507a5ef17`, verified in each job log).
Slices `cap-30min` + `cap-2h`: W3-audited SCORABLE subsets of
`captured.toml` (`datasets/cap_30min.toml`, `datasets/cap_2h.toml`).
No param tuning; no band/cost/leverage/variant changes; no live orders.
Every job under `tools/run_budget.py` (cap-30min: 1500s; cap-2h: 1800s).

Money rules: booked figures come ONLY from ledger fills/fees and
funding settlements. Cost-contract-v1 (26 bps round-trip) estimates are
reported separately and never booked; spread charged once. With zero
fills in all 10 cells, booked gross/fees/funding/net are all exactly 0
and expectancy/fill-rate/hold-times are reported as n/a (n=0), not zero.

## Economic panel — cap-30min (mechanism × BTCUSDT,ETHUSDT), 5/5

| cell | elapsed | closed | net | setups | cost-pass | mechanism |
|------|---------|--------|-----|--------|-----------|-----------|
| S1 | 744.7s | 0 | 0 | 12 | 0 | 12/12 reward-below-cost |
| S2 | 1457.3s | 0 | 0 | 0 | 0 | trend/sequence fail, no setups |
| S3 | 1481.5s | 0 | 0 | 45 | 0 | 45/45 reward-below-cost |
| S4 | 494.8s | 0 | 0 | 0 | 0 | pierce/reclaim fail, no setups |
| CASH | 452.3s | 0 | 0 | — | — | control (arms=0), no rejections |

Symbol-time: 3600 usable symbol-s (1800 BTCUSDT + 1800 ETHUSDT);
623 strategy-eligible s per strategy (coverage 17.3%).

## Economic panel — cap-2h (mechanism × BTCUSDT,ETHUSDT), 5/5

| cell | elapsed | closed | net | setups | cost-pass | mechanism |
|------|---------|--------|-----|--------|-----------|-----------|
| S1 | 819.4s | 0 | 0 | 4 | 0 | 4/4 reward-below-cost |
| S2 | 857.7s | 0 | 0 | 0 | 0 | trend/sequence fail, no setups |
| S3 | 829.3s | 0 | 0 | 0 | 0 | range fail only, no setups |
| S4 | 959.9s | 0 | 0 | 1 | 0 | 1/1 reward-below-cost |
| CASH | 1005.9s | 0 | 0 | — | — | control (arms=0), no rejections |

Symbol-time: 14400 usable symbol-s (7200×2);
1129 strategy-eligible s per strategy (coverage 7.8%).

Booked (all cells): gross 0, fees 0, funding 0 (0 entries), net 0.
Drawdown 0 (flat equity). Worst trade/day n/a. Exposure 0. Holds n/a.
Daily nets: all window days 0.0 (zero-trade days included per brief).

## Funnel evidence (per-cell stages)

cap-30min: usable 1571 s. S1: 12 setups, 0 cost-pass. S2: 0 setups
(380 trend-fail + sequence rows). S3: 45 setups, 0 cost-pass
(432 range-fail + 176 regime-na behind the setups). S4: 0 setups
(521 pierce-fail + reclaim rows). Gap-fail (unavailable data): 2684
rows every strategy cell; startup 931 s; stale_input 0;
missing_depth 0; ioc_cancelled 0; nonmarketable 0.

cap-2h: usable 6462 s. S1: 4 setups, 0 cost-pass. S2/S3: 0 setups.
S4: 1 setup, 0 cost-pass. Gap-fail: 12896 rows every strategy cell;
startup 1 s; stale_input 0; missing_depth 0; ioc_cancelled 0.

## Sensitivity (read-only; no params touched)

Setup rate per 1000 eligible-s (exact Garwood 95% CI) and cost-kill
fraction (exact Clopper-Pearson 95% CI); `tools/phaseb_sensitivity.py`,
`panels/sensitivity.json`:

| cell | setups | rate/1000s [95% CI] | cost-kill [95% CI] |
|------|--------|---------------------|--------------------|
| S1-30min | 12 | 19.3 [9.9, 33.6] | 1.00 [0.74, 1.00] |
| S2-30min | 0 | 0.0 [0.0, 5.9] | n/a |
| S3-30min | 45 | 72.2 [52.7, 96.7] | 1.00 [0.92, 1.00] |
| S4-30min | 0 | 0.0 [0.0, 5.9] | n/a |
| S1-2h | 4 | 3.5 [0.95, 9.1] | 1.00 [0.40, 1.00] |
| S2-2h | 0 | 0.0 [0.0, 3.3] | n/a |
| S3-2h | 0 | 0.0 [0.0, 3.3] | n/a |
| S4-2h | 1 | 0.89 [0.01, 4.9] | 1.00 [0.03, 1.00] |

Findings: (1) every setup admitted on either slice was killed by the
cost floor (62/62 combined); (2) S3 setup generation is regime-sharp —
72.2/1000s on cap-30min vs 0 on cap-2h (CIs disjoint); S1 also drops
19.3 → 3.5 (CIs barely touch); (3) S2/S4 generated zero setups on
either slice (upper bounds 5.9 and 3.3/1000s). No numeric cost margins
are recorded (intents table carries decision/reason strings only), so
margin-distance sensitivity is not computable — stated, not imputed.

## Watch items

All 10 cells: no unresolved mentions, no qty-short wipe mentions, no
orphan exit reservations. Listed phenomena NOT observed anywhere:
`policy.note_fill` unresolved expiries, protection-leg orphans,
gap-gate eligibility edges, IOC cancels, nonmarketable bands.

## Jobs

10/10 scoring cells CHILD_EXIT rc=0. First attempts of S4/CASH on
cap-30min under 4-way contention hit INCOMPLETE_BUDGET at 1500.5s
(verified enforcement) and were rerun solo to CHILD_EXIT rc=0; no
partial output was scored. Full suite: see filing.

## Evidence

Panels: `/tmp/w4-phaseb/panels/R01-*.json` + `sensitivity.json`.
Run dirs: `/tmp/w4-phaseb/R01-*/runs/mechanism/<ARM>/`
(ledger, fills, journal, equity, store, rejections).
Budget reports: `/tmp/w4-phaseb/cell-*.json`.
Code: `src/cryptobot/research/scoring.py`,
`tests/unit/test_research_scoring.py`, `tools/score_phaseb.py`,
`tools/phaseb_sensitivity.py`, `datasets/cap_30min.toml`,
`datasets/cap_2h.toml`.

## Next research hypothesis (REQUIRED for negative results)

Grounded in observed mechanisms only: 62/62 admitted setups killed by
reward-below-cost (S3 45/45, CI [0.92,1.00]); S3 setup generation
regime-sharp (72.2/1000 eligible-s on cap-30min vs 0 on cap-2h, CIs
disjoint); S2/S4 zero setups on both slices; no numeric cost margins
recorded (decision/reason strings only).

H-NEXT (cost-floor family, S1/S3/S4): the current fixed selection-stage
reward-vs-cost threshold is miscalibrated relative to realized setup
edge on these slices — i.e., a non-empty margin band exists in which
setups that are currently killed would pass cost and book non-negative
expectancy. Falsify/confirm WITHOUT changing economics first: add
read-only logging of (projected reward, cost estimate, margin) per
selection-stage intent, then measure the margin distribution of killed
setups on the same W3-audited cap-30min + cap-2h (mechanism x
BTCUSDT,ETHUSDT). If killed margins cluster near the floor, the band
exists and a calibrated floor multiple is the next change to test; if
margins are deeply negative even against exact measured costs,
REJECT H-NEXT — the edge family itself is insufficient and the next
hypothesis moves to setup quality (range/regime gates), not the floor.

H-NEXT-2 (setup-filter family, S2/S4): zero setups means the floor was
never reached — the binding constraint is the trend/sequence
(S2) and pierce/reclaim (S4) gates. Next hypothesis: S2/S4 gates
over-reject on these regimes. Falsify by logging gate-level feature
values at rejection and testing whether near-miss populations show
positive forward returns net of the 26 bps contract on held-out data.

CAVEAT (development knowledge): cap-30min/cap-2h outcomes are now
development knowledge. Any threshold, floor-multiple, or gate change
informed by them MUST be confirmed on held-out data (fresh captures,
or archive only after W3 clears it) — re-scoring the same slices is
diagnostic, never confirmation. No new economics were run for this
addendum.
