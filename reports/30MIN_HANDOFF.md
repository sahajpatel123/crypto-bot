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

Config: `combined.toml` S1–S4 arms=all (18 arms), BTCUSDT, development slice
2026-09-12/09-13 (benchmark_30d) + live-like capture proof (cap-2h).

| Run | Events | Status / wall | Result |
|---|---|---|---|
| #1 archive 2-day | 811,788 | COMPLETE 512.5s | 0 intents, equity flat 120.00 |
| #2 archive 2-day (clock fix) | 811,788 | COMPLETE 517.6s | 0 intents, equity flat 120.00 |
| Capture proof (150k) | 150,000 | TRUNCATED 38.2s | 0 intents (warmup-limited, non-economic) |
| Capture full (1.5M, 79 min) | 1,500,000 | TRUNCATED 366.9s | 0 intents, equity 120.00→120.00, 0 fills |

Root causes (both verified, neither a strategy verdict):
1. Archive slice: `markPrice` cadence is 60s (2,880 marks, median/max gap 60s) while the
   fail-closed freshness gate requires ≤1s. Gate blocks 100% → 0 intents. The gate is
   CORRECT (stale marks must not price risk); the archive feed cannot satisfy it.
   Manager clock fix (`0b0c1fc` + regression test) verified clock tracks event time.
2. Capture full run: gate passes in steady state (minute-1 startup transient excepted:
   35,010/38,466 stale rejects in minute 1 from out-of-order stream-start backlog —
   correct fail-closed on temporally incoherent input; remaining 78 min median 36/min).
   Strategies exit 65-min warmup, evaluate (range/breakout/gap gates observed), and fire
   ZERO setups in 79 min. Consistent with the ROUND-01 pre-gate base rate (~1/day ⇒
   ~0.05 expected in 79 min): no evidence of over-tightening, no tuning performed.

No TrialRecord with fills exists on the corrected stack. The 100-position / 10-day
economic floor is unreachable: pre-gate base rate ~1/day, gate further restricts, and
no defensible ≥10-day FRESH holdout exists (post-10-11 ≤ 2 days; pre-09-12 violates
chronology). Holdout absence is reported as a limitation, never manufactured.

## Three readiness verdicts

1. **Software delivery — READY (bounded scope).** 1022 passed + 1 skipped + 0 xfailed;
   11/11 IOC probes; split-resume parity on 811,788 events; unified 26bp cost contract;
   stop recognition 0.5s; safe demo-drill paths verified. Caveats: credentialed demo
   drill BLOCKED on owner credentials; prod venue-equity reconcile is a live-CLI
   follow-up; `_ioc_done` FIFO eviction past 4096 terminals (journal retains truth).
2. **Strategy expectancy — INCONCLUSIVE. NOT READY for real capital.** Zero fills on the
   corrected stack; no qualifying sample for any expectancy claim. The blockers are
   data-cadence (archive) and base-rate economics (capture), not disproven edge — but
   inconclusive is inconclusive: no strategy is certified.
3. **Daily 2–3% objective — NOT ACHIEVED.** Zero supporting evidence; all corrected-stack
   observations are flat (120.00). No tuning was performed to manufacture the target.

## Elapsed times

Every job wrapped in `tools/run_budget.py`; zero overruns, zero INCOMPLETE (one disclosed 0.1s W5 smoke check ran unwrapped).

| Owner | Job | Elapsed / budget | Outcome |
|---|---|---|---|
| W1 | setup+baseline | 66.5s / 1500s | CHILD_EXIT |
| W1 | IOC probe | 2.1s / 300s | CHILD_EXIT |
| W1 | regress-before | 1.8s / 30s | FAIL (expected red, since fixed) |
| W2 | m1 slice | 0.2s | CHILD_EXIT 0 |
| W2 | parity chunk1 (200k) | 63.1s | TRUNCATED (bounded proof) |
| W2 | parity chunk2 (613,788) | 179.0s | COMPLETE |
| W2 | parity reference (811,788) | 267.5s | COMPLETE |
| W2 | branch suite (762+1) | 131.7s / 201.9s | green |
| W3 | 30-min drill (all, 2k events) | 3.652s / 600s | PASS rc=0 |
| W3 | branch suite | 65.956s / 1500s | CHILD_EXIT rc=0 |
| W3 | stop recognition | 0.525s | 8 ticks during 2s block |
| W4 | funnel slice (18k events) | 15.874s / 1500s | CHILD_EXIT |
| W4 | ROUND-01 registry check | 0.442s / 600s | CHILD_EXIT |
| W4 | returns/registration pass | 63.11s / 1500s | CHILD_EXIT |
| W5 | all probe/drill jobs | within budget | 0 overruns (1 disclosed 0.1s unwrapped) |
| Mgr | full suite on main (1022+1+0x) | within 1500s | green |
| Mgr | bench regression (6/6) | within budget | green |
| Mgr | demo drill (safe paths) | within budget | 0 submitted, 4 BLOCKED |
| Mgr | prod preflight | within budget | 9/9 checks, no orders |
| Mgr | scoring run #1 BTC 2-day (811,788) | 512.5s / 1500s | COMPLETE, 0 intents |
| Mgr | scoring run #2 BTC 2-day (811,788) | 517.6s / 1500s | COMPLETE, 0 intents |
| Mgr | capture proof BTC (150k) | 38.2s / 1500s | TRUNCATED_MAX_EVENTS, 0 intents |
| Mgr | capture full BTC (1.5M, 79 min) | 366.9s / 1500s | TRUNCATED_MAX_EVENTS, 0 intents |

Sources: `coord/outbox/W{1..5}-30MIN.json`, `/tmp/score30/budget-*.json`.

## Remaining blockers & finite next jobs

1. **Owner credentials** (BLOCKED, declared): credentialed demo drill + live-feed paper
   session require owner-supplied demo keys. Safe paths verified without them.
2. **Fresh 10-day holdout** (data limitation): no defensible ≥10-day post-10-11 slice
   exists yet; collect via E-006 capture, then score once — no backfill fabrication.
3. **W5 W2/W3 reviews** (pending in W5 inbox): independent review filings outstanding;
   integration already on main, reviews are attestation-only.
4. **Prod venue-equity reconcile** (live-CLI follow-up, out of scope): wire reconcile
   into the live CLI path when credentials exist.
5. **Minute-1 startup transient** (minor, documented): out-of-order stream-start backlog
   trips the freshness gate fail-closed for ~1 min; steady-state verified. Consider a
   bounded disorder buffer if startup economics ever matter.
