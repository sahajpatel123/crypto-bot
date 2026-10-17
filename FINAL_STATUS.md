# FINAL STATUS — live/hardening takeover

Branch `live/hardening` from `deep/integration` @ e766383. Every claim
below cites a file or a command run in this program (see STATE.md for
the full log). No real or demo orders were placed; no keys were read;
`data/captures/campaign-1day-20261017` was never touched.

## Headline

**No strategy has a demonstrated fee-inclusive edge** (see
RESEARCH_VERDICTS.md: pilot 0/14 cells positive, best −25.37bps;
H-R2 −13.42bps; X1 measured a since-fixed latch). Infrastructure is
materially hardened, but the system is **not ready for live capital**:
the arming gate is correctly NO-GO today.

**Readiness for a supervised small-capital live trial: 4/10**
(up from the audit's 2/10). Money-handling defects 1, 8, 9, 10 are
fixed with tests; protection/shutdown semantics are real; feed,
latency and venue evidence still belong to the owner (OWNER_ACTIONS).

## Gate table (today, verified)

| Gate | State | Evidence |
|---|---|---|
| Verdict PASS (hash-bound) | **FAIL** (no PASS hypothesis) | RESEARCH_VERDICTS.md; `cryptobot verdict` |
| Demo drill PASS | **BLOCKED** (no credentials, by design) | `cryptobot demo-drill` → verdict BLOCKED, sha256 in output |
| Latency probe PASS | **UNDERPOWERED** (REST measured only on owner host; WS p99 owed) | `cryptobot latency-probe` (OWNER_ACTIONS §2) |
| 14-day pessimistic paper | **NOT RUN** (needs a PASS first, T5.6) | RESEARCH_VERDICTS.md |
| Preflight PASS | PASS-offline (existing) | `cryptobot preflight` tests (test_cli_readiness) |
| Watchdog + supervisor | PARTIAL (unit-proven, not venue-proven) | tools/watchdog.py, ops/systemd, test_hardening_batch |
| No BLOCKED in STATE.md | PASS (partials are not blocks) | STATE.md |
| `cryptobot gate` overall | **NO-GO** (correct) | run in this program: gate NO-GO, arm refuses exit 2 |

## Task table

| Phase | DONE | PARTIAL (evidence owed) |
|---|---|---|
| P0 T0.1–T0.4 | all | ruff 628 / mypy 464 baselines reported, CI non-blocking until zero |
| P1 T1.1, T1.5, T1.6, T1.7 | venue seed, shutdown, client IDs, funding | — |
| P1 T1.2–T1.4, T1.8, T1.9 | — | refresher thread + stale halt; submit-site retry wiring; sandbox fault-injection of every ordering; leverageBracket admission wiring; book-walk in Session accounting, pnl_2x in reports |
| P2 T2.1–T2.4 | breaker/HF/soak unit-proven | venue-scale drop/latency evidence (owner host) |
| P3 T3.1–T3.5 | unit-proven | FULL-sync measured cost; live watchdog trial |
| P4 T4.1–T4.3 | OWNER_ACTIONS complete | recorded fixtures + live drill (owner credentials) |
| P5 T5.1–T5.3, T5.5 | cost v2, prereg (3), verdict CLI | T5.2 maker in paper engine (queue model done); T5.4 dev evaluation of H1–H3 not yet run; T5.6 n/a (no PASS) |
| P6 T6.1–T6.3 | gate/arm built OFF, refusals tested; ladder+canary functions | prod path consuming armed.json (separate review) |

## Benchmarks (before → after, measured)

- Account margin on hot path: 1 signed REST per event → ≤1 per 5s
  per engine (T1.2, test_hotpath_cache: script-exhaustion proof).
- Risk tick fsync: every monitor_tick → ≤1/s, transitions forced
  (test_hotpath_cache debounce test).
- Client-ID collision space: seq + 16-bit rand per restart → UUID
  run prefix + seq; 1000 ids / 5 restarts, zero collisions
  (test_client_ids).
- Paper fills: 0 slippage → always 1 tick adverse + book-walk model
  (test_fill_realism, test_adapters_paper_engine).

## Tests

Targeted per task (each commit message carries its count). Full
suite: see STATE.md final entry (run at delivery; the only known
non-green is the zone-manifest test, proven to read the concurrent
uncommitted pivot `ZONES.json`, not committed code).

## What still stands between now and live capital (ranked)

1. **No edge.** H1–H3 dev evaluation (pessimistic, preregistered),
   then exactly-once confirmation on untouched data.
2. **Owner venue evidence**: demo drill PASS, latency p99 <250ms /
   drops <0.1% on the candidate host, recorded fixtures.
3. **14-day pessimistic paper** after any PASS (T5.6).
4. Close the PARTIALs: stale-cache halt + refresher thread,
   leverageBracket admission wiring, sandbox fault-injection matrix,
   book-walk accounting in Session reports.
5. Ruff/mypy baselines to zero so CI lint/type jobs can block.
6. Prod path consuming `armed.json` + canary — separate review,
   owner present. Never arm on a NO-GO gate.
