# STATE — live/hardening (principal-engineer takeover)

Branch: `live/hardening` from `deep/integration` @ `e766383`.
Mission: research harness (2/10 for live capital) → hardened, validated,
gated, ready for a *supervised small-capital live trial*; find out honestly
whether any strategy has a real fee-inclusive edge. A rigorous negative
result plus a hardened system is success. Priority: money-handling
correctness > validation integrity > features.

## Task list

| ID | Task | Status |
|---|---|---|
| T0.1 | Baseline targeted tests + this file | DONE |
| T0.2 | Consolidate F2 health recovery + F-SIZING-01 (+ client-ID if present); restore F2 tests; prove `_release_exit_only` callers | DONE |
| T0.3 | ruff + mypy configs (strict on risk/execution/adapters/app) + CI | DONE |
| T0.4 | Truth-in-docs (doctor, run_live docstring, README E-007, prod.toml) | DONE |
| T1.1 | Venue-seeded accounting + account-mode verification (fail closed) | DONE |
| T1.2 | Hot path: cached account snapshot, debounced risk writer, weight governor, benchmark | PARTIAL |
| T1.3 | Table-driven exception policy + safe mode; one order-lifecycle path | PARTIAL |
| T1.4 | Protection window + shadow stop + gap budget | PARTIAL |
| T1.5 | SIGTERM/SIGINT flattens by default; `--leave-protected` opt-out | DONE |
| T1.6 | Client IDs: UUID run prefix + persisted monotonic seq, ≤36 chars | DONE |
| T1.7 | Settled funding booked in ledger, reconciled vs venue | DONE |
| T1.8 | Tiered maintenance margin / liquidation gate + min-viable-equity calc | PARTIAL |
| T1.9 | Pessimistic paper fills (book-walk + latency penalty); 1x/2x cost P&L | PARTIAL |
| T2.1 | Ingestion/strategy decoupling, drop accounting + breaker | PARTIAL |
| T2.2 | Honor `max_hf_subscriptions` (BTCUSDT, ETHUSDT default) | PARTIAL |
| T2.3 | `cryptobot latency-probe` (gate: p99 feed age <250ms, drops <0.1%) | PARTIAL |
| T2.4 | 5x-burst soak test (bounded memory, drop budget) | PARTIAL |
| T3.1 | systemd unit + Dockerfile, crash-loop breaker, resume-on-restart | PARTIAL |
| T3.2 | External watchdog (flatten on stale heartbeat + exposure) | PARTIAL |
| T3.3 | Pluggable alerts (rate-limited, fake-sink tested) | PARTIAL |
| T3.4 | JSON logging + rotation, metrics export, FULL-sync cost report | PARTIAL |
| T3.5 | `cryptobot data verify`; gz replay docs | PARTIAL |
| T4.1 | Fixture recorder (redacted) + recorded-fixture contract tests | PARTIAL |
| T4.2 | `cryptobot demo-drill` (hashed JSON report) | PARTIAL |
| T4.3 | OWNER_ACTIONS.md (exact commands + expected outputs) | TODO |
| T5.1 | Cost model v2 + break-even / required-win-rate tables | PARTIAL |
| T5.2 | Maker-capable replay/paper execution (conservative queue model) | PARTIAL |
| T5.3 | Hypothesis registry ≤6, preregistered + committed pre-evaluation | DONE |
| T5.4 | Evaluation protocol (walk-forward, purge/embargo, bootstrap, Holm) | PARTIAL |
| T5.5 | `cryptobot verdict` PASS/FAIL/UNDERPOWERED JSON (hash-bound) | PARTIAL |
| T5.6 | ≥14d pessimistic paper if any PASS | TODO |
| T6.1 | `cryptobot gate` + `cryptobot arm` two-step prod enablement (built OFF) | DONE |
| T6.2 | Capital ladder + automatic demotion/halt | PARTIAL |
| T6.3 | Live canary: first N trades at minimum size | PARTIAL |

Status values: TODO / IN_PROGRESS / DONE / BLOCKED / PARTIAL.

## T0.1 baseline (verified 2026-10-17, this session)

Command:
`nice .venv/bin/python -m pytest tests/unit/test_binance_live_contract.py
tests/unit/test_binance_live_v008.py tests/unit/test_execution_orders.py
tests/unit/test_execution_e2e.py tests/acceptance/test_ledger.py
tests/acceptance/test_risk_sizing.py tests/acceptance/test_risk_v008.py -q`
→ **81 passed in 2.91s**. `tests/unit/test_session_health_recovery.py` does
NOT exist on `deep/integration` (confirmed: `file or directory not found`) —
it is the missing F2 test to restore in T0.2.

## Audit-claim verification (code-checked before fixing)

1. Ledger seeded from config even live — **CONFIRMED**:
   `src/cryptobot/app/session.py:188` `Ledger(config.paper_capital_usdt)`;
   `configs/prod.toml:16` `paper_capital_usdt = 120.0` ("NOT live equity").
   Venue seeding: only via periodic `_snapshot_account()` (session.py:2757);
   no startup wallet/position/order seeding found.
2. Signed REST on hot path — **CONFIRMED**: `binance_live.py:625,1307,1315,
   1388,1416` call `_signed("GET","/fapi/v2/account")`; account view at
   :1307 explicitly "no cache". Fsync-per-tick claim: risk-state writer to
   verify in T1.2.
3. Venue exceptions kill process — **PLAUSIBLE, to pin in T1.3**: Session has
   `_exchange_errors` counter (session.py:215) but no safe-mode flatten path
   found on the live driver; classification table absent.
4. No atomic bracket / protection window — **TO VERIFY in T1.4** (entry →
   `attach_protection` sequencing in `app/engine.py`, `app/reference.py`).
5. SIGTERM does not flatten — **CONFIRMED**: `cli.py:121-126` handler only
   sets `session._stop_flag = "graceful"`; no flatten/confirm path.
6. No maintenance-margin/liquidation model — **CONFIRMED** (no
   `leverageBracket`/liquidation-price code in risk/; verify in T1.8).
7. Feed drops / `max_hf_subscriptions` unused — **TO MEASURE in T2.1/T2.2**
   (config declares `max_hf_subscriptions = 2` in paper/prod/demo tomls;
   subscription path to trace).
8. Client-ID collision — **CONFIRMED for live engine**:
   `binance_live.py:249` default `run_tag="bl"`, `:650-653`
   `f"{run_tag}-{seq:06d}-{rand16}"` with per-process `seq` and only 16 bits
   of randomness → collisions across restarts are likely. (`OrderManager`
   at `execution/order_manager.py:132-135` uses 8 hex chars — better, still
   per-process seq.) No run-unique UUID prefix, no persisted seq.
9. F2 + F-SIZING-01 unmerged — **CONFIRMED**: `fix/f2-health-recovery`
   (`eb0cfe1`) and `integration/owner-exec` (`21e21a4` merge, `a576e73`
   sizing clamp) are not ancestors of HEAD. On HEAD,
   `session.py:2757-2759` still latches health once (`_halt_entries` with no
   release); `risk/sizing.py:93` still `stressed = sum(legs)/10000*...`
   unclamped (negative funding credit enlarges size).
   `_release_exit_only` (session.py:1494) has **zero production callers** on
   HEAD — only `tests/unit/test_rev2_stream_ownership.py:644`.
10. Live funding never booked — **PARTIAL**: `ledger.py:169-180`
    `record_funding`/`note_funding` exist and `binance_live.py:1399-1404`
    sums `FUNDING_FEE` income, but no live-path caller books settled funding
    into the ledger (to pin in T1.7).
11. Zero-slippage paper fills — **CONFIRMED**: `paper_engine.py:223`
    `FillModel(prob_fill_on_limit=1.0, prob_slippage=0.0, ...)`.
    `OrderManager.submit_with_retry` (`order_manager.py:159`) is the tested
    retry path; live path uses `BinanceLiveEngine.submit` directly — retry
    logic not wired into live (T1.3).

Also: no `.github/` CI on HEAD; no ruff/mypy config in `pyproject.toml`
(dev extra is pytest only). Working tree carries uncommitted pivot work
(`tools/pivot_*`, `tests/unit/test_pivot_*`, `data/pilot/`, `reports/pivot/`)
that predates this branch — left untouched, never committed as own work.

## Decisions

- D-H1: Branch `live/hardening` created from `deep/integration` @ e766383;
  commit per task with task ID (explicitly directed by the takeover
  protocol). No push without explicit ask. `deep/sc-scalp` never merged
  (negative evidence).
- D-H2: `data/captures/campaign-1day-20261017` is never read/touched
  (untouched confirmation data, live campaign running). Dev data:
  `data/pilot`, `datasets/benchmark_30d`; log every use in
  `research/DATA_LEDGER.md`.
- D-H3: Prod submission stays OFF by default; P6 builds the arming path
  only. Gate thresholds are never lowered to pass; any change needs a
  written justification in DECISIONS.md.

## T0.2 consolidation (DONE)

Reproduced on HEAD before fixing (branch tests run against e766383):
F2 file → 6 failed/1 passed (stale latch never releases; entries never flow
after mark recovery); sizing file → 2 failed/2 passed (−25bps funding credit
sized qty×stop = 33.6 USDT vs 12.5 budget). Cherry-picked `eb0cfe1`
(F2, → b686d0b) and `a576e73` (F-SIZING-01, → b87ee9a); after: both files
11 passed; targeted regression (session×4 + sizing×3 + execution) 84 passed.
`_release_exit_only` production callers now: `_apply_health_gate`
(session.py:1569) ← `_health_tick` (:1585) ← event path (:2832). No
client-ID work exists on `integration/owner-exec` (diff of
binance_live.py/order_manager.py vs e766383 is empty) → client IDs are
T1.6. `docs/f2-health-recovery.md` came with the F2 cherry-pick.

## Commands run

- `git switch -c live/hardening` (from deep/integration @ e766383)
- targeted baseline above → 81 passed
- T0.2: `pytest /tmp/test_session_health_recovery.py` → 6F/1P on HEAD;
  `pytest tests/acceptance/test_sizing_funding_clamp.py` → 2F/2P on HEAD;
  after cherry-picks → 11 passed; regression set → 84 passed
- T0.3 (ff1b184): ruff 0.17.1 baseline 628 errors, mypy 2.4.0 baseline 464
  errors/58 files — configs committed, CI lint/type jobs report
  non-blocking until baselines reach zero (never weakened to pass).
- T0.4 (31b6c4d): doctor live-label fix + test_doctor_truth 28 passed
  with test_cli_readiness.
- P2-P6 batch (test_hardening_batch 9 passed): DropBreaker+hysteresis
  wired in _control_step, per-type producer drops, HF cap in bridge +
  CLI BTC/ETH default; latency-probe/data-verify/verdict/gate/arm/
  demo-drill CLI (arm refuses without GO+env ack+typed phrase);
  alerts (Memory/Log/Webhook + rate limit), metrics counters;
  systemd+Dockerfile (crash-loop via StartLimitBurst), watchdog tool
  (no countdownCancelAll); cost_model_v2 tables, maker queue model,
  verdict engine (bootstrap/Holm/UNDERPOWERED), ladder+canary.
  PARTIAL = owner-run live evidence still owed (latency p99, drill,
  soak at venue scale, FULL-sync measurement) — see FINAL_STATUS.
- T1.4 (PARTIAL): existing attach (stop-first, verified, 3-attempt
  emergency flatten) + new shadow_stop_breached + protection time
  budget (30s -> flatten + protection-gap alert) wired in
  _ensure_protection_inner. Fault-injection on sandbox venue owed
  (covered partially by T1.3 safe-mode + existing protection tests);
  parallel stop/target is sequential stop-first by design (safer).
- T1.5: Session.shutdown_flatten (bounded retries, flat confirmed
  via ledger+venue snapshot), graceful stop in _supervise now
  flattens, --leave-protected CLI flag wired (paper run). 34 passed
  with cli/session regressions.
- T1.9 (PARTIAL): execution/fill_realism.py book-walk + latency +
  stressed_pnl 1x/2x; paper FillModel prob_slippage 0.0->1.0 (always
  1 tick adverse). One existing paper test updated to allow the
  slipped tick (behaviour change, assertion widened by exactly the
  slip). Owed: wire book-walk into Session replay accounting and
  report pnl_2x in run reports.
- T1.7: engine.funding_income + Session.book_settled_funding
  (tranId-idempotent) + funding_reconcile; 6 tests with T1.8 passed.
  Live-loop periodic booking call owed (startup + hourly) — noted.
- T1.8 (PARTIAL): risk/margin.py tiered maintenance margin, isolated
  liquidation price, liquidation_ok (3x + beyond stop+slippage),
  minimum_viable_equity. Admission wiring into policy.evaluate owed
  (needs leverageBracket fetch at readiness) — gate function tested.
- T1.6: _new_client_id = tag(sanitised<=16)-uuid10-seq6 (<=36, legal
  charset); 1000 ids across 5 simulated restarts unique. Regression
  fix: v008 unreachable test scripted 3 errors for T1.3 bounded retry.
- T1.3 (PARTIAL): classify_exception table (retry_backoff/lookup_first/
  reject_intent/safe_mode), bounded retry on account_snapshot read,
  Session.enter_safe_mode (halt+flatten retries+alert, never raises),
  run_live converts safe_mode/lookup_first to graceful end. Evidence:
  test_exception_policy + regressions 28 passed. Live path order
  lifecycle is BinanceLiveEngine (OrderManager retry unchanged for
  reference path — ONE live path; OrderManager remains replay-only,
  documented not deleted to keep suite contract). Owed: wiring
  retry_backoff at submit call sites (engine refuse-fast already
  covers rate-limit window) — tracked in FINAL_STATUS.
- T1.2 (PARTIAL): engine account cache TTL 5s (REST + ACCOUNT_UPDATE),
  account_snapshot_cached, weight governor from X-MBX-USED-WEIGHT-1M,
  RiskPolicy._persist_tick debounce (transitions force; flush_state).
  Evidence: test_hotpath_cache 4 tests + regressions = 77 passed.
  Before: account_margin = 1 signed REST/call; after: <=1 per 5s/engine.
  Owed: background REST refresher thread + stale-cache entry halt and
  replay p99 benchmark — stale REST failure currently propagates
  (handled as safe-mode in T1.3); do not claim DONE until then.
- T1.1: test_venue_seeding 5F on HEAD → after Ledger.reseed_opening,
  Session.seed_from_venue, BinanceLiveEngine.verify_account_modes +
  journal_client_ids, CLI _seed_live_session (demo + prod): 84 passed
  (venue_seeding + cli_readiness + binance_live x2). Recent-income
  fetching at startup deferred to T1.7 (funding booking); seed uses
  wallet/positions/orders now. Full P0 suite still owed (R-1).

## Open risks

- R-1 CLOSED: definitive full suite on 8b7f254: 1479 passed,
  1 failed, 1 skipped (1434s). The one failure
  (test_zone_status::test_real_zones_manifest_shape) reads the
  concurrent UNCOMMITTED coord/pivot/ZONES.json (Z6 cites a drill
  PASS in the working copy); committed HEAD has Z6 evidence=[] as
  the test expects. Not a hardening regression; pivot files untouched.
- R-2: Pivot working-tree changes may interact with suite runs (pivot
  tests present); keep them out of hardening commits.
- R-3: No credentials available (by design) — all venue-behaviour claims
  must be proven on the sandbox venue / recorded fixtures; live claims
  become OWNER_ACTIONS.md entries.

---
# RUN2 — self-advancing system (F0-F9), worktree detached @ 3100266
Started: 2026-10-18. Worktree:
`/private/var/folders/3w/wgv95vkx69lf97wwlsh02d700000gn/T/opencode/cryto-hard-work`
(detached HEAD 3100266). Main checkout untouched; uncommitted files there
never read. Campaign `data/captures/campaign-1day-*` events never read
(manifest/heartbeat/status metadata only).

## RUN2 task list (phase order F0,F3,F1,F2,F4,F5,F6,F7,F8,F9)

| ID | Task | Status |
|---|---|---|
| F0.1 | Re-entry: worktree + read committed docs | DONE |
| F0.2 | Hermetic suite: zone test via git object + guard test, full suite 0 failed | IN_PROGRESS (fix 1e96e80; full suite sh_14bf34aa running) |
| F0.3 | Claim audit PASS/REOPEN table | DONE (21 items, 0 REOPEN; item 21 full-suite shared w/F0.2) |
| F0.4a | Leverage-bracket gate into LIVE admission + stale reject | DONE |
| F0.4b | Break-even re-derivation + tests + fix >60% statement | DONE |
| F0.4c | Paper fill model parameterized + calibration path | DONE |
| F0.4d | RESEARCH_VERDICTS sentences -> verdict JSON mapping | DONE |
| F0.5 | Adversarial review (2 subagents or 30-item pre-mortem) | DONE (33 findings: 32 FIXED, 1 DISPUTED w/evidence; batches 1-8) |
| F3.1 | Standalone recorder Binance USD-M + USDC check | DONE (integrated) |
| F3.2 | Venue plugins Bybit/OKX behind flags | DONE (stubs behind flags) |
| F3.3 | Durability: buffer, fsync, rotation, hash-chain, reports | DONE (integrated) |
| F3.4 | Campaign manifest metadata gap note | DONE |
| F3.5 | Vault DEV/CONFIRM + token gate + import-lint | DONE (integrated) |
| F3.6 | recorder CLI + systemd + compose | DONE |
| F1.1 | Property tests (Hypothesis) | DONE |
| F1.2 | Mutation testing risk/execution/adapters | IN_PROGRESS (scoped loop sh_14c4e13c in mut worktree: sizing/margin/rounding/fillrealism/policy/ordermanager) |
| F1.3 | Chaos matrix sandbox venue | TODO |
| F1.4 | Determinism replay byte-identical | DONE |
| F1.5 | Differential paper vs sandbox | TODO |
| F1.6 | Fuzz REST/WS parsers | TODO |
| F1.7 | Perf regression thresholds | TODO |
| F2.1 | Close PARTIAL/BLOCKED non-credentialed | TODO |
| F2.2 | calibrate CLI + conservative-only auto-update | TODO |
| F2.3 | fixtures ingest CLI | TODO |
| F2.4 | deploy kit + host-check | TODO |
| F2.5 | Credential safety checks | TODO |
| F2.6 | Clock-skew guard halts entries | TODO |
| F4.1 | Prereg H4-H6 committed pre-eval (budget ≤8) | TODO |
| F4.2-F4.7 | Autopilot state machine + dev/confirm/paper stages | TODO |
| F4.8 | NO-EDGE terminal report | TODO |
| F5.1-F5.5 | Gate/arm hardening + ladder + canary + refusal verify | TODO |
| F6.1-F6.2 | Dashboard + alerts | TODO |
| F7.1-F7.3 | Docs + OWNER_ACTIONS ordered checklist | TODO |
| F8.1-F8.2 | Acceptance + soak + scores | TODO |
| F9 | FINAL_STATUS rewrite from evidence | TODO |

## RUN2 log
- F0.1 DONE: worktree detached @ 3100266 confirmed (`git rev-parse HEAD`
  = 3100266aa52a4181df250c7b1ecf916796d74483); read STATE/FINAL/
  OWNER/VERDICTS/DECISIONS + research/prereg/H1-H3 from worktree only.
- F0.2 FIX (targeted green, full suite pending): guard
  tests/unit/test_hermetic_suite.py failed first (2 failed on HEAD
  code), then tests/unit/test_zone_status.py switched to
  `git show HEAD:coord/pivot/ZONES.json` via _read_committed.
  Targeted: `pytest tests/unit/test_zone_status.py
  tests/unit/test_hermetic_suite.py` → 6 passed. D-RUN2-01 justifies
  the scoped hermetic ban. NOTE: worktree .venv via `uv sync --locked`
  refused (lockfile needs update, uv picked 3.12 vs main 3.14); full
  suite runs with main-venv interpreter + PYTHONPATH=worktree/src so
  the tested code is the worktree's (verified
  cryptobot.__file__=worktree/src/...).
- F0.3 CLAIM AUDIT (all DONE items in FINAL_STATUS.md re-run in
  worktree @1e96e80; interpreter main-venv + PYTHONPATH=worktree/src):

  | # | DONE claim (FINAL_STATUS) | Evidence cmd (re-run) | Result |
  |---|---|---|---|
  | 1 | T0.1 baseline 81 passed | `pytest test_binance_live_contract test_binance_live_v008 test_execution_orders test_execution_e2e acceptance/test_ledger acceptance/test_risk_sizing acceptance/test_risk_v008` | PASS (81 passed) |
  | 2 | T0.2 F2+sizing 11 passed | `pytest test_session_health_recovery acceptance/test_sizing_funding_clamp` | PASS (11 passed) |
  | 3 | T0.3 ruff/mypy configs + CI non-blocking | `ls .github/workflows/ci.yml; grep continue-on-error` (2 hits); `ruff check src tests` | PASS (CI non-blocking verified; ruff now 657 vs 628 baseline — count drift, see note A) |
  | 4 | T0.4 doctor truth 28 passed | `pytest test_doctor_truth test_cli_readiness` | PASS (28 passed) |
  | 5 | T1.1 venue seeding 84 passed | `pytest test_venue_seeding test_cli_readiness test_binance_live_contract test_binance_live_v008` | PASS (84 passed) |
  | 6 | T1.5 shutdown flatten 34 w/regressions | `pytest test_shutdown_flatten` (2) + `test_cli_readiness` (25) | PASS-core (core green; exact 34-file set under-specified in STATE, covered by full suite; note B) |
  | 7 | T1.6 client IDs unique 1000/5 restarts | `pytest test_client_ids` | PASS (2 passed, UUID+seq, zero collisions) |
  | 8 | T1.7 funding booking 6 w/T1.8 | `pytest test_funding_booking test_margin_sizing` | PASS (6 passed) |
  | 9 | P2-P6 batch 9 passed | `pytest test_hardening_batch` | PASS-functional (10 passed; was 9 @767650d, soak added later — count drift, note C) |
  | 10 | P5 cost v2 table taker>60% | `breakeven_table()` 25/25 taker 1x → 86% req, 18bps RT | PASS (86%>60%; imprecision + missing INFEASIBLE flag → F0.4b TODO) |
  | 11 | P5 prereg H1-H3 committed pre-eval | `ls research/prereg/` (3 files); `git log -- research/prereg/` (767650d, no eval after) | PASS |
  | 12 | P5 verdict CLI PASS/FAIL/UNDER | `cryptobot verdict --help`; `test_verdict_underpowered_and_fail` in batch | PASS |
  | 13 | P6 gate NO-GO + arm refuses exit 2 | `cryptobot gate --out` → NO-GO RC=2; `cryptobot arm` → REFUSED RC=2, no armed.json | PASS |
  | 14 | P6 ladder+canary functions | `test_ladder_demotion_and_canary` in batch | PASS |
  | 15 | Bench: hotpath ≤1/5s, debounce ≤1/s | `pytest test_hotpath_cache` | PASS (4 passed) |
  | 16 | Bench: paper 1-tick adverse | `pytest test_fill_realism test_adapters_paper_engine` | PASS (55 passed) |
  | 17 | Gate table: drill BLOCKED, latency UNDERPOWERED, paper NOT RUN | `cryptobot demo-drill --help`, `latency-probe --help` exist; no drill/latency JSONs in tree | PASS (correctly unmet) |
  | 18 | No BLOCKED in STATE.md | grep BLOCKED in STATE task table (0) | PASS |
  | 19 | Prod OFF default | `grep allow_live_submission configs/prod.toml` → false | PASS |
  | 20 | Research: pilot 0/14 best −25.37bps; H-R2 −13.42bps | research/DATA_LEDGER.md cites as pre-takeover audit inputs | PASS-cited (raw data/pilot + datasets/benchmark_30d absent in committed worktree — uncommitted in main, never touched per rule; note D) |
  | 21 | Full suite 1479/1/1 on 8b7f254 | Background full suite @1e96e80 running (sh_14bf34aa) | PENDING (required 0 failed; closes F0.2) |

  Notes: (A) ruff 628→657 drift predates RUN2 (own files clean:
  `ruff check` on both changed test files → All checks passed).
  (B) T1.5/T1.3/T1.2 "with regressions" counts (34/28/77) lack exact
  file lists in STATE; core files green, full suite is the closer.
  (C) batch 9→10: `git show 767650d:...batch` has 9 defs, HEAD has 10
  (soak added in 400a741); STATE/FINAL counts stale, function green.
  (D) pilot/benchmark raw data not in committed tree — numbers are
  ledger-cited audit inputs, not recomputed; F0.4d maps verdict
  sentences to machine JSON.
  REOPENs opened: NONE (0). F0.3 → DONE pending full-suite close of
  item 21 (shared with F0.2).
- F0.4a DONE: bracket/liq gate wired into RiskPolicy.evaluate (was 0
  production callers). RiskConfig gains leverage_brackets /
  brackets_asof_utc / brackets_max_age_s (validated); run_mode
  requires fresh brackets; stale always rejects; sized notional
  prices the ACTIVE tier, liq estimated at max leverage
  (conservative), liquidation_ok 3x enforced. Session.arm_brackets
  injection + parse_brackets_payload (signed-endpoint fetch stays
  credentialed/owner). Tests: test_bracket_admission 8 (failed 5
  first, incl. boundary + stale + tier-flip + parser + arm).
  Behaviour-change updates (not weakening, cf. T1.9): 3
  test_risk_v006 run_mode Approve tests now supply fresh brackets via
  _run_policy. Regression: risk v004/v006/v007/v008/gates + bracket +
  margin + replay + app_filters + hardening_batch → 158 passed.
- F0.4b DONE: break-even re-derived (EV=p*T−(1−p)*S−c, p*=(S+c)/(T+S)).
  Formula was already correct; table lacked INFEASIBLE flag. Added
  `feasible` per row (p*≤1). Tests: test_breakeven_derivation 4
  (failed 4 first on missing flag; plain-arithmetic cross-check of all
  30 rows, EV=0 at p*, 25/25@26bps→102% infeasible). Script
  tools/verify_breakeven.py → 30 rows OK, 3 infeasible (25/25 taker
  1.5x/2x, maker 2x), RC=0. Fixed RESEARCH_VERDICTS ">60–65%" to exact:
  25/25 taker 18bps/86% @1x, 104%/122% infeasible @1.5x/2x; maker
  15bps/80% @1x. hardening_batch (>0.6) untouched, still passes.
- F0.4c DONE: 1-tick rule retired. PaperFillParams (versioned,
  provenance-stamped ASSUMED-pessimistic: 2 spread + 6 slip + 2
  latency + 25 empty-book bps, 50ms p95) in fill_realism;
  NautilusPaperEngine accepts fill_params (dict or object),
  fill_delay_ms defaults from params, slippage_audit prices every
  fill against the book-walk pessimistic leg (drift_bps≥0, never
  better). Calibration path documented in module/class docstrings:
  F2.2 `cryptobot calibrate` fits MEASURED params from
  demo-drill/paper/live fills; auto-updates only more conservative.
  Tests: test_paper_fill_params 5 (failed ImportError first; incl.
  200-seed never-improves property). Regression: fill_params +
  fill_realism + paper_engine → 60 passed. FINAL_STATUS benchmark
  line "always 1 tick adverse" now stale (rewritten in F9).
- F0.4d DONE: every RESEARCH_VERDICTS sentence maps to machine JSON.
  Generated via CLI only (never hand-edited): 6 verdict JSONs in
  research/verdicts/ (all UNDERPOWERED n=0 — raw pilot/benchmark
  vectors absent from committed tree, honestly encoded as empty
  trades inputs; ledger citations preserved as audit input) +
  cost-model.json via verify_breakeven --out (30 rows, 3 infeasible).
  Pilot/H-R2 corrected FAIL→UNDERPOWERED (in-tree machine evidence;
  ledger FAIL citations retained as audit input, not machine
  verdicts). Recommendations section REMOVED (no machine mapping;
  next steps rebuild in F4 autopilot queue). Test:
  test_verdicts_mapping 4 (failed 4 first; enforces row→JSON,
  hash-binding, no uncited claims, no recommendations).
- F0.5 IN_PROGRESS: 2 read-only adversarial reviewers launched
  (ses_eb3ff36d lens A risk/exec, ses_eb3ff369 lens B adapters/live;
  briefed WITHOUT STATE/decisions; triage on return).
- FULL SUITE fresh @0f86687 (sh_14c02e4f): 1494 passed, 1 skipped,
  0 failed in 1107s. STILL mixed-collect (F1.1/recorder/vault/triage
  landed mid-run, uncollected) → final authoritative suite re-runs at
  F0 end.
- F0.5 DONE: both cold reviewers returned (A: 11 findings ses_eb3ff36d,
  B: 22 findings ses_eb3ff369; briefed without STATE/decisions).
  Triage: 32 FIXED across batches 1-8 (all CRITICAL/HIGH closed with
  failing-first tests), 1 DISPUTED (B#21 paper MARKET GTC: live
  closes are MARKET sweep not IOC-cancel; GTC documented
  paper_engine:603-615; timing residual drift-priced by B#9).
  Notable independent confirmations: A#11 == F1.1 rounding bug;
  reviewer-held areas (journaling, idempotency, sizing clamp,
  prod-off chain) match the F0.3 PASS column.

  | ID | Severity | Finding | Verdict |
  |---|---|---|---|
  | A#1 | CRITICAL | Duplicate close over unknown | FIXED (batch1: unknown=in-flight) |
  | A#2 | CRITICAL | Orphaned exposure unsupervised | FIXED (batch4: orphan watch+flatten+alert) |
  | A#3 | HIGH | shutdown_flatten exits naked | FIXED (batch4: keep-legs+drain+safe-mode) |
  | A#4 | HIGH | Venue exc crash/flatten (=B#5) | FIXED (batch2: degraded reads+gate) |
  | A#5 | HIGH | Paper funding restart mismatch | FIXED (batch5: journal+restore totals) |
  | A#6 | HIGH | Mark-missing fail-open (short) | FIXED (batch4: mark-missing blocks entries) |
  | A#7 | MEDIUM | Dust deadlock (exact-zero) | FIXED (batch6: ledger snaps ≤1e-9) |
  | A#8 | MEDIUM | Reconcile symbol-vs-global + silent skip | FIXED (batch5: per-symbol+skipped loud) |
  | A#9 | MEDIUM | Hot-path REST while holding (=B#16) | FIXED (batch7: cached agree on hot_cache) |
  | A#10 | LOW | OrderManager/paper ID recovery | FIXED (batch8: seq restore+collision loop+32-bit) |
  | A#11 | LOW | Rounding epsilon round-up | FIXED (F1.1 scale-aware eps) |
  | B#1 | CRITICAL | Submit exc escapes admit + latch | FIXED (batch2: reject/unknown/ratelimit paths) |
  | B#2 | CRITICAL | Sibling double-fill reversal | FIXED (batch3: reversal detector+flatten; venue reduce-only backstop verified) |
  | B#3 | HIGH | Shadow stop dead code | FIXED (batch4: wired+tested both branches) |
  | B#4 | HIGH | Supervision feed-dependent | FIXED (batch4: throttled idle health eval) |
  | B#5 | HIGH | 429 kills stop processing (=A#4) | FIXED (batch2: skip-tick+defer+duration safe-mode) |
  | B#6 | HIGH | Flatten-then-cancel race | FIXED (outcome-covered: reduce-only backstop + reversal detector+flatten) |
  | B#7 | HIGH | Safe-mode misreport | FIXED (batch1: verify+unknown_ids) |
  | B#8 | HIGH | Flat-confirm fail-open | FIXED (batch1: None→False) |
  | B#9 | HIGH | Paper fills raw (audit unwired) | FIXED (batch6: drift top-up+fills_drift.jsonl, B9 schema intact) |
  | B#10 | HIGH | Live funding unwired | FIXED (batch5: throttled booking+reconcile) |
  | B#11 | MEDIUM | Orphan leg on partial attach | FIXED (batch3: rollback+partial_leg_id both seams) |
  | B#12 | MEDIUM | Re-protection wrong-way (=B#2) | FIXED (batch3: reversed books flatten, never protect) |
  | B#13 | MEDIUM | Seed foreign-order gate vacuous | FIXED (batch8: strays surfaced+refused) |
  | B#14 | MEDIUM | run_mode brackets livelock (paper) | FIXED (batch8: paper flag+live arm at readiness) |
  | B#15 | MEDIUM | ACCOUNT_UPDATE freshness lie | FIXED (batch7: age REST-bound) |
  | B#16 | MEDIUM | Snapshot-per-event (=A#9) | FIXED (batch7: see A#9) |
  | B#17 | MEDIUM | Triggered-algo misattribute | FIXED (batch3: _triggered remap+journal) |
  | B#18 | MEDIUM | Watchdog/supervisor unwired | FIXED (batch8: heartbeat+unit+resume-safe+alerts.jsonl; sinks→F6) |
  | B#19 | MEDIUM | Resume flatten skips note_flat | FIXED (batch4: shell-less release) |
  | B#20 | LOW | Cancel lookup throttled in window | FIXED (batch7: window-bypass DELETE) |
  | B#21 | LOW | Paper MARKET GTC vs live IOC | DISPUTED (live closes are MARKET sweep, not IOC; GTC documented paper_engine:603-615; timing residual drift-priced by B#9) |
  | B#22 | LOW | Funding fallback-id collision | FIXED (batch5: row-index ids) |
- F3 BUILDERS launched: recorder (ses_eb3fdca9: writer/streams/
  plugins/integrity/service + tests + systemd) and vault
  (ses_eb3fdca8: registry/tokens/loader + 4 tests + import-lint).
  File ownership explicit; owner integrates + wires CLI.
- F3.4 DONE: campaign absent in worktree (gitignored, main-checkout
  only); rule 3 dominates F3.4 read permission → no read attempted.
  Gap note data/recorder/CAMPAIGN-GAP-F0.md records E-006 vs F3.1-3.3
  gaps (verified by grep: no forceOrder/OI/funding/premium/USDC/
  rotation/compression/hash-chain/parquet/plugins/disk-alerts) +
  owner reconciliation path.
- ENV: hypothesis 6.170.1 + mutmut installed into the shared test
  interpreter (main-venv site-packages; ignored, not source) for
  F1.1/F1.2. No source files touched outside the worktree.
- F1.1 DONE: test_properties_risk (7: sizing-in-budget incl. negative
  funding, rounding safe+idempotent, liq monotonic in leverage,
  client-ID legal/unique incl. random tags, protection covers fills)
  + test_properties_ledger (4: conservation, dup idempotency,
  booked-net reorder, same-side replay). REAL BUG FOUND + FIXED:
  floor_to_step/ceil/floor_to_tick multiplicative epsilon rounded UP
  at large qty/step ratios (10.0/1e-8→10.00000001); replaced with
  scale-aware 2ulp-capped epsilon (safe direction, idempotent to
  1e9). Independently confirmed by reviewer A#11. Regression test in
  test_risk_rounding. 20 passed (properties+rounding), 30 passed
  (rounding/sizing/protected-entry regression).
- F1.2 IN_PROGRESS: scoped mutmut loop in detached mut worktree
  (sizing/margin/rounding/fillrealism/policy/ordermanager with fast
  selections); harness fixed (mutants/ import shadowing); binance_live
  excluded w/ justification (DECISIONS D-RUN2-02, ~1500 mutants x 60s
  infeasible; chaos+contract+property cover instead).
- F1.4 DONE: wall_utc injectable in Session (5 wall_ts sites);
  replay-twice byte-identical fills/risk/drift + intents/commands
  dumps; report identical modulo declared perf noise + workdir.
  Failed 2 first on pristine (wall bytes), 46 passed with replay
  regression.
- F3.1-F3.3 DONE (builder ses_eb3fdca9, owner-verified): recorder
  package (writer/streams/plugins/integrity/service, 1399 lines),
  16 tests green (overflow loud-drop, tamper-evident chain,
  integrity counts), systemd unit, README. forceOrder via
  all-market !forceOrder@arr + client filter (no per-symbol stream
  exists); Bybit/OKX STUBS behind flags with UNVERIFIED endpoint
  refs. Ruff: only 7 UP017 (timezone.utc kept for codebase
  consistency, matching E-006 convention).
- F3.5 DONE (builder ses_eb3fdca8, owner-verified): vault package
  (registry/tokens/loader/_common), 30 tests green (chain tamper,
  one-shot tokens, CONFIRM token-gate, SYNTHETIC refuse,
  import-lint). Review point (vault README): cross-hypothesis
  DEV-for-H/CONFIRM-for-H2 nuance follows per-hypothesis classify;
  accepted (documented).
- F3.6 DONE: `cryptobot recorder start|stop|status|verify` wired
  (foreground+pid+status.json+STOP/SIGTERM; offline status/verify),
  4 CLI tests (failed 4 first), systemd unit (builder) + watchdog
  unit (triage), deploy/docker-compose.yml (recorder live, rest in
  F2.4). F3 CLOSED (F3.1-3.6 all DONE).
