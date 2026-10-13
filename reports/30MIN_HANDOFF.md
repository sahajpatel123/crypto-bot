# 30-Minute Execution Plan — final handoff (manager)

## Code delivery (main @ TBD)

| Batch | Content | SHA |
|---|---|---|
| Baseline + deadline wrapper | Frozen baseline d733a61, run_budget.py + self-tests | d5800e3, 6ec1d68 |
| W5 probes + demo drill | 18 probes (8 green, 10 red→fixed), drill runner + procedure, drill fix, probe updates | 61d4c04, 91d74ad, 154102b, 890de6b, 66e8877, 1f63a77 |
| W4 research | Signal-to-fill funnel, frozen ROUND-01 (registry 0.4.0) | 25c6cb7 |
| W1 execution | IOC arrival-cancel + no-rest, relabel superseded; manager query-API repairs | f11e899, fdad744 |
| W3 runtime | Bounded producer, 250ms tick, control seam, fail-closed ts, 1s gates, preflight | 523b20d, 3abc5e5 |
| W2 data/cost | cost-contract-v1, selector 31→26, bench runner, parity proof | 0df168b, a96899c |

Suite: 1022 passed, 1 skipped, 0 xfailed. Zero failures.

## Gate evidence (each reported separately)

- Runtime budget: run_budget.py (budget, inheritance, INCOMPLETE, no-relaunch) + 5/5 self-tests; every worker job wrapped, zero overruns.
- Execution/accounting: 11/11 IOC probes green (arrival-cancel, no-rest, bands, races, exactly-once, protection, reduce-only, labeled exits).
- State continuity: 811,788-event split-resume == reference (cursor/heartbeats/booked identical).
- Data/cost integrity: one cost contract (26bps, signed funding, explicit spread); causal manifest resolution verified.
- Economic candidate: SEE SCORING SECTION (TBD).
- Exchange operation: demo drill safe paths verified (no-creds BLOCKED, non-demo refused); credentialed drill BLOCKED on owner credentials (declared blocker); prod preflight completes without submitting orders (default-off).

## Scoring (corrected stack)

TBD — run in progress.

## Three readiness verdicts

TBD.

## Elapsed times

TBD (from outbox filings + budget reports).

## Remaining blockers & finite next jobs

TBD.
