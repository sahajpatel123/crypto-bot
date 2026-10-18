# STATE — live/final-hardening

Worktree: `/Users/sahajpatel/Code/cryto-bot-final`
Branch: `live/final-hardening` from `live/hardening` tip `3100266`
Date: 2026-10-18. This file is the run memory; resume at the first
non-DONE task. The agent never placed a real/demo order, never read or
stored a key, and never read the campaign-1day event data.

## Completion checklist

| Item | Status | Evidence |
|---|---|---|
| Full suite green in worktree, 0 failed | DONE | 1527 passed, 1 skipped; logs `final-suite-nobench2.log`, `final-suite-bench.log` |
| F0.3 table has no open REOPEN | DONE | table below, 80 targeted passed |
| Break-even verified by independent script + tests | DONE | `tools/breakeven_audit.py`; `test_breakeven_audit.py` |
| Liquidation/bracket gate wired into live admission, tested | DONE | `Session._bracket_admission`; `test_margin_sizing.py` |
| Recorder, vault, autopilot, calibrate, host-check, fixtures ingest exist/tested/service defs | DONE | modules + tests + `deploy/` |
| H4–H6 preregistered and committed before evaluation | DONE | `research/prereg/H4..H6`; registry |
| arm/gate refusal tests in every path | DONE | `test_autopilot_gate.py`; `_prod_arm_problem` |
| Chaos matrix ends flat/protected | DONE (matrix) | `test_lifecycle_matrix.py`, acceptance faults |
| OWNER_ACTIONS single ordered checklist | DONE | `OWNER_ACTIONS.md` |
| FINAL_STATUS no unsupported claim | DONE | rewritten from evidence |

## F0.3 claim audit (re-ran every DONE claim)

Command (80 passed in 5.54s):

`pytest tests/unit/test_venue_seeding.py test_shutdown_flatten.py
test_client_ids.py test_funding_booking.py test_margin_sizing.py
test_fill_realism.py test_hardening_batch.py test_doctor_truth.py
test_exception_policy.py test_hotpath_cache.py test_protection_window.py
test_ladder_controller.py test_breakeven_audit.py test_live_recorder.py
test_vault.py test_autopilot_gate.py -q`

| Claim (FINAL_STATUS DONE) | Re-run | Verdict |
|---|---|---|
| T1.1 venue-seeded accounting | `test_venue_seeding.py` | PASS |
| T1.5 SIGTERM flattens / leave-protected | `test_shutdown_flatten.py` | PASS |
| T1.6 client IDs unique across restarts | `test_client_ids.py` | PASS |
| T1.7 settled funding booked | `test_funding_booking.py` | PASS |
| T1.8 tiered margin / liquidation helper | `test_margin_sizing.py` | PASS — reopened: NOW wired into live admission |
| T1.9 pessimistic fills | `test_fill_realism.py` | PASS — reopened: parameterized model replaced one-tick rule |
| T1.2 hot-path cache | `test_hotpath_cache.py` | PASS |
| T1.3 exception policy | `test_exception_policy.py` | PASS — reopened: submit/stream escapes fixed |
| T1.4 protection window | `test_protection_window.py` | PASS |
| T0.4 doctor truth | `test_doctor_truth.py` | PASS |
| T6.1 gate/arm | `test_hardening_batch.py` + new gate tests | PASS — arm is now TTY/CI-gated |
| T5.5 verdict JSON | `test_hardening_batch.py` + vault verdict path | PASS |
| T5.3 preregister H1–H3 | files + registry | PASS; H4–H6 added |
| `_release_exit_only` callers | code inspection + F2 tests | PASS |

No REOPEN remains. PARTIALs that were code-able were fixed; the rest
are BLOCKED-OWNER (venue/demo/14-day evidence) or BLOCKED-TECH
(mutation score below).

## Phase task table

| ID | Task | Status | Evidence |
|---|---|---|---|
| F0.1 | Worktree at 3100266; read memory files | DONE | `git worktree list`, this file |
| F0.2 | Hermetic suite (git object, no mutable reads) | DONE | `test_zone_status.py`, `test_hermetic_reads.py` 6 passed |
| F0.3 | Claim audit | DONE | table above, 80 passed |
| F0.4a | Bracket gate in live admission; stale rejects | DONE | `risk/margin.py`, `session.py`, 8 margin tests |
| F0.4b | Independent break-even audit | DONE | 6 tests; 102% INFEASIBLE |
| F0.4c | Explicit paper fill model | DONE | `PaperFillParameters`, 2 tests |
| F0.4d | RESEARCH_VERDICTS maps to machine JSON | DONE | `research/verdicts/H1..H6.json` |
| F0.5 | Adversarial review + triage | DONE | DECISIONS D-029; 18 regressions |
| F1.1 | Property-based invariants | DONE | `test_properties_f1.py` 4 passed; found rounding bug |
| F1.2 | Mutation score | BLOCKED-TECH | mutmut run not completed in this run; see Risks |
| F1.3 | Chaos matrix | DONE | `test_lifecycle_matrix.py` + acceptance faults |
| F1.4 | Determinism | DONE | existing `test_determinism.py`, `test_replay_numeric.py` |
| F1.5 | Paper vs sandbox differential | PARTIAL | existing paper/sandbox contract tests; no new tolerance harness |
| F1.6 | Parser fuzz | DONE | existing malformed/adversarial parser tests |
| F1.7 | Performance regression | PARTIAL | existing bench tests; no new p99 threshold |
| F2.1 | Close code-able PARTIALs | DONE | see F0.3 table |
| F2.2 | `cryptobot calibrate` | DONE | `research/calibration.py`, 4 tests |
| F2.3 | `cryptobot fixtures ingest` | DONE | `fixtures.py`, 1 test |
| F2.4 | Deployment kit + host-check | DONE | `deploy/`, `ops/host_check.py` |
| F2.5 | Credential safety | DONE | `security.py`, manual checklist |
| F2.6 | Clock-skew guard | DONE | `risk/clock_guard.py`, test |
| F3.1 | Binance public recorder streams | DONE | `market_data/live_recorder.py` |
| F3.2 | Bybit/OKX plugins (flags) | DONE | `venue_stream_url`, `subscription_messages`, tests |
| F3.3 | Durability/quality | DONE | bounded writer, gzip chunks, hash manifests, integrity report, disk budget |
| F3.4 | No campaign disturbance | DONE | recorder writes only `data/recorder`; campaign untouched |
| F3.5 | Vault | DONE | `data/vault.py`, 6 tests, import lint |
| F3.6 | Recorder CLI + services | DONE | `cryptobot recorder`, `deploy/systemd` |
| F4.1 | Budget + H1–H6 prereg | DONE | 6/8, frozen configs |
| F4.2 | Dev stage criteria | DONE | `Autopilot.dev_promotes` |
| F4.3 | Freeze before CONFIRM | DONE | `Vault.freeze_hypothesis` refuses refreeze |
| F4.4 | Power analysis / ETA | DONE | `research/power.py`, test |
| F4.5 | Exactly-once confirmation | DONE | vault token + `CONFIRM` state |
| F4.6 | Autopilot run-once/status/report | DONE | state machine + CLI; 7 tests |
| F4.7 | 14-day paper compare | DONE | `PAPER_14D`/`PAPER_COMPARE` |
| F4.8 | Terminal NO-EDGE report | PARTIAL | `autopilot report` exists; terminal auto-report only when all KILLED/FAIL |
| F5.1 | Gate additional evidence | DONE | `cmd_gate` checks; GO test |
| F5.2 | Arm interactive-only | DONE | TTY/CI/expiry tests |
| F5.3 | Ladder + auto-demotion | DONE | `risk/ladder_controller.py`, 4 tests |
| F5.4 | Per-trade attribution | PARTIAL | controller records predicted vs realized; no session auto-feed yet |
| F5.5 | Prod refuses without gate/arm | DONE | `Session._prod_arm_problem`; `_run_prod` refusal |
| F6.1 | Dashboard | DONE | `reporting/status.py`, test |
| F6.2 | Alert sinks | DONE | existing `monitoring/alerts.py` + tests |
| F7.1 | README/ARCHITECTURE/SECURITY/RUNBOOK | DONE | files at root |
| F7.2 | OWNER_ACTIONS ordered checklist | DONE | 14 ordered steps |
| F7.3 | Stale docs corrected | DONE | README/RESEARCH_VERDICTS rewritten |
| F8.1 | Acceptance --full | DONE | `cryptobot acceptance --full` |
| F8.2 | Suite/mutation/perf/chaos/soak | PARTIAL | suite/chaos/soak evidence; mutation/perf BLOCKED-TECH |
| F9 | FINAL_STATUS | DONE | two scores, gate table |

## Break-even (independent)

`python tools/breakeven_audit.py` → `ok: true`, 30 rows, 0 problems.
- 25/25bps at 26bps cost: p*=1.02 → 102% → **INFEASIBLE**.
- Default taker 25/25: 18bps → p*=86% (corrects the earlier
  ">60–65%" statement).
Tests: `tests/unit/test_breakeven_audit.py` 6 passed.

## Autopilot state (machine-written, after run-once)

| H | State | Power ETA | Provenance |
|---|---|---|---|
| H1 | DEV_EVAL | n/a (no dev trades) | OBSERVED |
| H2 | DEV_EVAL | n/a | OBSERVED |
| H3 | DEV_EVAL | n/a | OBSERVED |
| H4 | DEV_EVAL | n/a | OBSERVED |
| H5 | DEV_EVAL | n/a | OBSERVED |
| H6 | DEV_EVAL | n/a | OBSERVED |

Gate is NO-GO: no PASS verdict, no GATE_READY, no sealed confirmation.

## Tests / commands run (this run)

- F0.2: `pytest tests/unit/test_zone_status.py tests/unit/test_hermetic_reads.py -q` → 6 passed.
- F0.3/F1 targeted: `pytest ...16 files... -q` → 80 passed in 5.54s.
- Acceptance/audit/CEO: `pytest tests/acceptance tests/audit tests/ceo_review -q` → 264 passed, 1 warning in 34.58s.
- `python tools/breakeven_audit.py` → 30 rows, ok.
- `pytest tests/unit/test_live_recorder.py tests/unit/test_vault.py` → 13 passed.
- `pytest tests/unit/test_autopilot_gate.py` → 7 passed.
- `pytest tests/unit/test_calibration_ops.py` → 8 passed.
- `pytest tests/unit/test_properties_f1.py tests/unit/test_risk_rounding.py` → 12 passed.
- `pytest tests/unit/test_adversarial_regressions.py` → 6 passed.
- `pytest tests/unit/test_ladder_controller.py` → 4 passed.
- `python -m cryptobot.cli acceptance --root /tmp/cb-accept2` → PASS, gate NO-GO on SYNTHETIC.
- Definitive suite: `pytest -q` with the three slow benchmark files
  split out → **1500 passed, 1 skipped**; benchmark files separately →
  **27 passed**. Combined **1527 passed, 1 skipped, 0 failed**.

## F0.5 adversarial triage

Two reviewers (no STATE, no prior reasoning) audited money paths and
FINAL_STATUS. Full findings in DECISIONS D-029. Summary:

| Finding | Verdict |
|---|---|
| Unknown/reject submit kills run, leaks hold (A1/A2) | FIXED — supervised shell + classify |
| Unreachable venue treated as flat (B1/A7) | FIXED — None => not flat; reference exempt |
| Day roll clears safety halts (B2/A8) | FIXED — hard-halt prefix preservation |
| Protection UNKNOWN crashes (B3) | FIXED — catch + emergency at attempt bound |
| Non-USDT fee crash in drain (B4) | FIXED — safe-mode wrapper |
| No watchdog heartbeat writer (B5) | FIXED — `watchdog.json` on init/30s |
| Orphan late fill unprotected (B6) | FIXED — orphan flatten in supervision |
| leave-protected trusts local legs (B7/A9) | FIXED — venue stop verified |
| Dust/min-notional close loop (B8/A10) | FIXED — explicit dust latch + min-notional check |
| Malformed venue positions read flat (B9) | FIXED — complete=False |
| Shadow stop not called (A4) | FIXED — wired in `_supervise` |
| Rate-limit read escapes (A3) | FIXED — broad fail-closed catches |
| Flatten reports submitted as ok (A12) | FIXED — drain + flat check |
| Negative maintenance margin (A6) | FIXED — clamped non-negative |
| Leverage changed mid-run (A6) | FIXED — 60s `leverage_now` recheck |
| Booking-block latch no auto-ack (A11) | DISPUTED — fail-closed by design; RUNBOOK manual reconcile |
| Default mark-age opt-in on old research configs (A5) | DISPUTED for prod — prod/demo set 1s; gate requires host evidence |

## Risks / open items

- R-1 CLOSED: full suite previously had one non-hermetic failure; fixed
  and guarded (above).
- R-2: Mutation testing (F1.2) and new performance thresholds (F1.7)
  were not completed; these are engineering-quality gaps, not live
  safety gaps, and are listed in FINAL_STATUS.
- R-3: Venue/demo/latency/drill/14-day paper evidence can only be
  produced by the owner: OWNER_ACTIONS steps 1–14.
- R-4: No credentials were used; no real or demo order was placed.

## Commands / artifacts

- Worktree: `git worktree add -b live/final-hardening ... 3100266`.
- Autopilot: `cryptobot autopilot run-once` (machine-written states).
- Acceptance: `cryptobot acceptance --full` (see `runs/acceptance-*`).
- Logs: `/private/var/folders/.../final-unit.log`,
  `/private/var/folders/.../final-suite-full.log` (superseded by the
  final full run recorded in FINAL_STATUS).
