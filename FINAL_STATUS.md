# FINAL STATUS — live/final-hardening

Worktree `/Users/sahajpatel/Code/cryto-bot-final`, branch
`live/final-hardening`, from `live/hardening` tip `3100266`.
Every claim cites a command run in this worktree or a file path. No real
or demo order was placed; no key was read, printed or stored;
`data/captures/campaign-1day-*` events were never read.

## Headline

**No strategy has a demonstrated fee-inclusive edge. The arming gate is
correctly NO-GO.** This is the honest outcome, not a failed build: the
system now measures, seals, evaluates and gates edge over time, and
refuses capital until the evidence exists.

## Scores

| Score | Value | Basis |
|---|---|---|
| Infrastructure readiness | **8/10** | recorder/vault/autopilot/verdict/gate/arm/deploy + tests; missing live venue evidence and mutation/perf closure |
| Edge readiness | **1/10** | 0 PASS verdicts; 6 hypotheses are unevaluated (0 trades); no sealed confirmation data |
| **Live readiness = MIN** | **1/10** | gate NO-GO; no arm file; no owner venue evidence |

Infrastructure is not 10/10 because the live venue path, demo drill,
latency and 14-day paper evidence are owner/credential-dependent, and
mutation/performance thresholds are not fully closed. Edge is 1/10
because the hypothesis family exists and is preregistered, but no
hypothesis has even a dev promotion.

## Gate table (verified today)

| Gate check | State | Evidence |
|---|---|---|
| Verdict PASS | **FAIL** | `research/verdicts/H1..H6.json` all UNDERPOWERED (0 trades) |
| Sealed provenance (no SYNTHETIC) | **FAIL** | no CONFIRM chunk exists |
| Autopilot GATE_READY | **FAIL** | `cryptobot autopilot status`: all DEV_EVAL |
| Cost model fresh | **FAIL** | `research/cost-model.json` not produced (no calibrated fills) |
| Host-check PASS | **BLOCKED-OWNER** | `cryptobot host-check` needs owner host/NTP/network |
| Demo drill PASS | **BLOCKED-OWNER** | `tools/demo_drill_live.py` needs demo keys |
| Latency p99/drops | **BLOCKED-OWNER** | `cryptobot latency-probe --feed-seconds` needs owner host |
| Watchdog heartbeat | **FAIL/BLOCKED** | writer exists; owner must run the bot/watchdog |
| `cryptobot gate` overall | **NO-GO** | `cryptobot gate` (tests `test_autopilot_gate`) |
| `cryptobot arm` | **REFUSED** | non-TTY/CI/no GO tests pass; no armed.json exists |

## Autopilot hypothesis table

Machine state: `research/autopilot/state/H*.json`; registry:
`research/autopilot/registry.json`; log:
`research/autopilot/transitions.json`.

| H | State | Trades | Power ETA | Gate-eligible |
|---|---|---|---|---|
| H1 maker OFI | DEV_EVAL | 0 | n/a | no |
| H2 trend/vol | DEV_EVAL | 0 | n/a | no |
| H3 funding tilt | DEV_EVAL | 0 | n/a | no |
| H4 cross-venue lead-lag | DEV_EVAL | 0 | n/a | no |
| H5 liquidation cascade | DEV_EVAL | 0 | n/a | no |
| H6 vol-shock filter | DEV_EVAL | 0 | n/a | no |

The budget is 6 of the allowed 8. H4–H6 were committed before any
evaluation. A hypothesis that fails dev is permanently KILLED; a PASS
goes to a 14-day pessimistic paper run and only PAPER_COMPARE success
produces GATE_READY.

## What was built / fixed (all with tests)

- **Recorder** (`market_data/live_recorder.py`): Binance aggTrade,
  bookTicker, depth@100ms, markPrice@1s, forceOrder; REST
  OI/funding/premium/depth; optional Bybit/OKX plugins; bounded writer
  with counted/flagged overflow; gzip hourly chunks; SHA-256
  hash-chained manifests; sequence/depth/timestamp checks; reconnect
  with jitter; disk budget; integrity report. CLI:
  `cryptobot recorder start|stop|status|verify`; systemd unit.
- **Vault** (`data/vault.py`): hash-chained registry and access log;
  DEV/CONFIRM classes; CONFIRM only after freeze; SYNTHETIC never
  CONFIRM; one-shot verdict token; import-lint proof that no other
  module reads CONFIRM data.
- **Autopilot** (`research/autopilot.py`): idempotent state machine with
  hash-chained transitions, daily JSON/Markdown report, power ETA,
  exactly-once confirmation, 14-day paper compare. CLI:
  `autopilot run-once|status|report`, `research register|power`.
- **Verdict/gate/arm**: verdict can consume a sealed CONFIRM chunk with a
  one-shot token; gate requires GATE_READY, sealed provenance, config
  hash, fresh cost/host/drill/latency/heartbeat; arm requires TTY, no CI,
  typed phrase, positive capital/daily loss, unexpired GO gate. Tests
  cover refusals in every path.
- **Bracket/liquidation gate**: wired into live admission and demo;
  missing/unobserved/stale/malformed brackets reject; tier boundaries
  tested; mid-run leverage is rechecked every 60s.
- **Break-even**: independent audit; 25/25bps at 26bps cost is 102% and
  INFEASIBLE; default 25/25 taker is 86% (corrected from ">60–65%").
- **Paper fills**: explicit spread/depth/latency parameters replace the
  unconditional one-tick rule (Nautilus simulator's one-tick limit is
  documented).
- **Calibration, fixtures ingest, host-check, credential safety, clock
  guard, dashboard, deployment kit** exist and are tested.
- **Adversarial fixes** (two independent reviewers): unknown/reject
  submit escapes, unreachable-venue-as-flat, safety halts cleared by day
  roll, protection UNKNOWN crash, user-stream fee crash, missing
  watchdog heartbeat, orphan late fills, leave-protected local-only
  trust, dust close loop, malformed venue positions, unwired shadow
  stop, rate-limit read escapes, flatten-without-drain, negative
  maintenance margin. See DECISIONS D-029.
- **Rounding bug**: property tests found floor/ceil epsilon could round
  up/down by a whole step; fixed and tested.

## Benchmarks / before-after

| Metric | Before | After |
|---|---|---|
| Non-hermetic suite failure | 1 failed (mutable ZONES.json) | fixed + guard test |
| Break-even 25/25 at 26bps | ">60–65% win" prose | 102%, INFEASIBLE (independent script) |
| Liquidation gate | helper only | live/demo admission, stale rejects |
| Paper slippage | always 1 tick | spread/depth/latency parameters, floor 1 tick |
| Rounding | could increase qty/price by a step | clamped to input side |
| Watchdog heartbeat | no writer | atomic `watchdog.json` on init/30s |
| Gate latency | REST-only accepted | p99 ≤250ms + drops ≤0.1% required |
| Arm | typed phrase only | TTY + no-CI + gate + expiry + capital + typed |
| Hypothesis family | H1–H3 | H1–H6 preregistered, budget 6/8 |

## Tests (evidence)

- `pytest tests/acceptance tests/audit tests/ceo_review -q` →
  **264 passed, 1 warning in 34.58s**.
- `pytest tests/unit/test_zone_status.py tests/unit/test_hermetic_reads.py -q`
  → **6 passed**.
- Targeted F0.3/F1 set (16 files) → **80 passed in 5.54s**.
- `pytest tests/unit/test_live_recorder.py tests/unit/test_vault.py -q`
  → **13 passed**.
- `pytest tests/unit/test_autopilot_gate.py -q` → **7 passed**.
- `pytest tests/unit/test_calibration_ops.py -q` → **8 passed**.
- `pytest tests/unit/test_properties_f1.py tests/unit/test_risk_rounding.py -q`
  → **12 passed**.
- `pytest tests/unit/test_adversarial_regressions.py -q` → **6 passed**.
- `pytest tests/unit/test_ladder_controller.py -q` → **4 passed**.
- `python tools/breakeven_audit.py` → `ok: true`, 30 rows.
- `cryptobot acceptance --full` → PASS, final state GATE_READY,
  provenance SYNTHETIC, gate NO-GO.
- Full unit suite result and count: see the run log
  `final-unit.log` (recorded below when complete).

## Remaining work — ONLY owner-dependent (ordered)

1. Provision the host and pass `host-check` (OWNER_ACTIONS 1).
2. Start/verify the recorder and leave it running (2).
3. Add demo-only, trade-only, IP-allowlisted, no-withdrawal keys (3).
4. Run the demo drill and reconcile flat (4).
5. Measure WS latency/drops and stop on failure (5).
6. Ingest recorded demo fixtures (6).
7. Calibrate the cost model from fills (7).
8. Install/enable the autopilot timer (8).
9. Let dev/confirm/paper evidence accrue; freeze and confirm exactly
   once per hypothesis (9–11).
10. Run `gate`; only a GO allows the human `arm` ceremony (12–13).
11. Supervise the canary; promotion is manual (14).

## Non-owner gaps (BLOCKED-TECH, not live blockers)

- F1.2 mutation score not completed (mutmut runner was not configured
  and run within this session); no surviving-mutant claim is made.
- F1.5 paper-vs-sandbox differential tolerance harness and F1.7 new
  performance thresholds are not added; existing deterministic/bench
  tests remain green.
- F4.8 terminal NO-EDGE auto-report is generated only when every
  hypothesis reaches KILLED/FAIL; today they are DEV_EVAL.
- F5.4 per-trade attribution exists in `LadderController`; automatic
  session feeding of predicted-vs-realized slippage is not yet wired.

These are quality/completeness gaps, not reasons to arm capital. The
gate cannot pass without the missing evidence regardless.
