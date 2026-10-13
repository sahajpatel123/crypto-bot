# READY handoff — readiness review + execution plan (final, manager)

Reviewed baseline: tag `review-0d40ad3-baseline` = `0d40ad3`.
Integrated HEAD: see SHA table below (final tip at push time).
Suite: **1162 passed, 1 skipped, 0 failed** (manager and W5 agree exactly).
Production order submission stayed disabled throughout. No live orders.
No credentials in repo. W5 final verdict: **PASS**.

## 1. Integrated commits (main, all pushed)

| SHA | Content |
|---|---|
| `a5a6fb9` | Review inputs preserved (directive + probes + results + 6.9s local repro) |
| `442501c` | Manager: truncated CORR_HANDOFF repaired; aggregate probe marked historical (TypeError verified) |
| `624dc0a` | W4 phase A: 61-candidate export + frozen H-R1/H-R2 (read-only) |
| `44387e4` | W2: scoring/funnel (episodes, funding+IST, symbol-seconds, watch) |
| `a70d8ed` + `e63af64` | W5 interim + W2/W4A review addendum (APPROVE both) |
| `9a4693c` | W3: deadline containment + gap taxonomy + eligible intervals (merge) |
| `30f9175` | W1: Session lifecycle §5 six invariants (merge, vertical slice) |
| `6954f8d` | Manager acceptance gate (5 probe assertions, permanent, 5/5 green) |
| `29f1971` | W5 W3 review addendum (APPROVE) |
| `1fda122` | Manager drill prep (§7 plan + kill-on-miss + 9 stubbed tests) |
| `e33c95d` | W5 W1 review addendum (APPROVE) |
| `7380905` | W5 closing: final challenge PASS + W5-READY.json |

## 2. Runnable bounded commands (all ≤1500s work, verified)

```
# Full suite (271s of 1500s)
python3 tools/run_budget.py --budget-s 1500 --checkpoint-dir <ck> --report-out <rep> \
  -- uv run --locked --extra dev pytest -q -p no:cacheprovider

# Independent probes (6.9s of 300s)
uv run --locked --extra dev python Crypto_Bot_CORR_Independent_Probes.py

# READY acceptance gate (6s of 300s)
uv run --locked --extra dev pytest tests/unit/test_ready_acceptance.py -q

# Deadline battery on macOS (85s of 900s, 24 incl. budget+eligibility)
uv run --locked --extra dev pytest tests/runtime/test_nested_deadline_adversarial.py \
  tests/unit/test_run_budget.py tests/unit/test_eligibility.py -q

# Deadline battery on Linux (colima w3batt images, 66-77s)
docker run --rm -v $PWD:/repo -w /repo w3batt \
  python -m pytest tests/runtime/test_nested_deadline_adversarial.py -q
docker run --rm -v $PWD:/repo -w /repo w3batt-ps \
  python -m pytest tests/runtime/test_nested_deadline_adversarial.py \
  tests/unit/test_run_budget.py -q

# Eligibility intervals (offline, no replay)
PYTHONPATH=src .venv/bin/python tools/eligible_intervals.py --help

# Confirmation scoring cell, S3 on cap-30min (481s of 1500s)
python3 tools/run_budget.py --budget-s 1500 --checkpoint-dir <ck> --report-out <rep> \
  -- uv run --locked --extra dev python -m cryptobot.research.backtest \
  --dataset cap-30min --splits mechanism --symbols BTCUSDT,ETHUSDT --armsets S3 \
  --config configs/round01/R01-S3.toml --require-round trials/round-01.json \
  --require-config R01-S3 --out <out>

# Demo drill (BLOCKED without owner creds; kill-on-miss armed)
uv run --locked --no-sync python tools/audit/demo_drill.py --dir <dir> full
```

## 3. Finding → cause → fix → independent proof

| # | Finding | Cause | Fix (→ SHA) | Independent proof |
|---|---|---|---|---|
| 1 | 0.332 fill vs 0.33293226 approval; 6 live legs forgotten; emergency loops | Venue flooring after risk approval; legs dropped unconfirmed; vacuous flatten spam | W1: venue-step snap pre-approval + post-rounding recheck; executable narrowing; never-drop tracking; replace-not-clear; act-only flatten → `30f9175` | Probe-after both tapes COMPLETE, forgotten 0, `{verified:1}`; manager lifecycle acceptance 2/2; W5 APPROVE + adversarial in-bracket sweep to full release |
| 2 | Filled reservation expires to unresolved; quiet tape INCOMPLETE | Paper path never called note_fill; unknowns unhandled | W1: first-fill reservation→exposure exactly once; IOC remainder retires; release on full agreement only → `30f9175` | expiry [] both tapes; quiet exit @100.23 via time-exit inside bracket; W5 exact |
| 3 | Partial exit counted as closed trade | No episode model | W2: open/partial/closed/orphan-exit episodes; closed-only trades → `44387e4` | Probe {closed:0,n:0}; manager acceptance; W5 exact + orphan-exit disclosure check |
| 4 | Funding omitted; UTC vs IST day | No funding attribution; naive dates | W2: signed funding in trade/daily/booked; Asia/Kolkata realized+marked days; reconciliation identity → `44387e4` | Probe 0.74 everywhere on 2026-10-12; missing-ledger-never-flat; W5 exact |
| 5 | Symbol-seconds collapsed (2→1) | Clock-second union | W2: (strategy,symbol,second) eligibility + attribution → `44387e4` | Probe total 2; W5 exact |
| 6 | One generic gap reason; 65-min unexplained | BarMissing→None; no taxonomy | W3: 7-class taxonomy; exact per-symbol intervals; zero agg-breaks; empties proven quiet; mark jitter excluded → `9a4693c` | 24/24 Mac; crafted-capture probe by W5; W5 APPROVE |
| 7 | 5 Linux deadline failures; daemon survival marker | Child-rooted walk missed subreaper orphans; ps/PATH dependency; zombie false-survivors | W3: dual discovery roots; /proc enumeration + fallback; reaping; fail-closed hook → `9a4693c` | Manager Linux re-run: 15+2skip (ps), 10+2skip (no ps); battery contracts preserved (2 justified Linux skipifs + 2 platform-neutral ports); W5 APPROVE |
| 8 | Handoff truncated; aggregate probe stale | Transit truncation; freshness API moved on | Manager: handoff reconstructed + re-verified; probe marked historical → `442501c` | Marker gone; TypeError verified live |
| 9 | Demo drill unverified legs | Stop never lookup-verified; no stale/unknown/cap kills | Manager §7 prep: declared plan + kill-on-miss + 9 stubbed tests → `1fda122` | 9/9 green; W5 verified drill kill logic in closing |

## 4. Elapsed times (run_budget everywhere; zero overruns; no 1800s budgets)

| Owner | Job | Elapsed / budget | Outcome |
|---|---|---|---|
| W1 | repro before/after | 14.0s / ~14s / 300s | exact before, fixed after |
| W1 | full suites (3×) | 382s / 240s / 256s / 1500s | 1130+1 green |
| W2 | probes before/after | 7.7s / 12.6s | 3/3 fixed |
| W2 | owned + neighbors + unit suite | 0.1s / 25.2s / 220.0s / 1500s | 885+1 green |
| W3 | Linux before (no-ps/ps) | 60.2s / 61.6s | 4 + 3 legs fail (reproduced) |
| W3 | Mac battery before/after | 74.5s / 84.7s | 24/24 green |
| W3 | eligibility exports | per /tmp reports | exact intervals |
| W3 | full suite | 246.7s / 1500s | 1116+1 green |
| W4A | export + validation (4 streams) | 93.6s / 1500s | 61 candidates, exact |
| W5 | gate suite / full / probes | 100.1s / 332.1s / ~7s | PASS, 1162+1 |
| Mgr | probes + acceptance + suites | 6.9s / 6.2s / 265–316s / 1500s | 5/5, 1162+1 |
| Mgr | Linux battery (ps / no-ps) | 77.5s / 65.8s / 1500s | 15+2 / 10+2 |
| Mgr | S3 confirmation cell | 481.3s / 1500s | 0 closed, 45 below-cost |

## 5. Economic evidence (corrected stack)

- Prior verified finding transfers: selection-stage cost kills are
  upstream of the lifecycle/scoring fixes.
- Manager confirmation cell (S3-cap30min on merged main): 0 closed
  trades, 45/45 setups `below_cost`, stale/depth 0 — panel-identical
  mechanism to W4's, scored with the corrected scorer (symbol-seconds,
  reservation splits, slippage note). Evidence:
  `reports/ready-evidence/economics/`.
- H-R1 holds descriptively (0/61 within 5bps, median gap −21.13):
  rejections are deep, not marginal — a calibration fact, never an
  edge claim.
- W4 phase-B counterfactual comparison: EXECUTION BLOCKED (worker
  unresponsive after GO + 2 pings; runtime stop-messaging guidance).
  Frozen H-R1/H-R2 + 6-variant set + locked-eval designation stand
  ready in `trials/ready-01.json` for a future run.

## 6. Remaining blockers

1. Owner demo credentials (credentialed drill; prep armed and tested).
2. W4 phase-B comparison (executor-absent; reassign or rerun to close).
3. Linux subreaper *mechanism* verified by manager on colima; a standing
   CI leg would make it permanent (W5's noted open item).
4. Fresh held-out data for H-R1/H-R2 confirmation (captures are dev
   knowledge; never relabel used data fresh).

## 7. Three verdicts

1. **Trading-lifecycle correctness — PASS.** Six §5 invariants hold on
   the integrated tree: snapped+rechecked sizing, exactly-once
   fill conversion, verified protection with resize, terminal-tracked
   children, idempotent flatten, full-agreement release. Both tapes
   COMPLETE with zero forgotten legs and in-bracket exits; crash-kill
   resume preserves parity; W5 adversarial challenge PASS.
2. **Economic evidence — NO QUALIFYING STRATEGY (evidence, not a veto
   on the software).** Zero closed trades after realistic costs on the
   corrected stack (45/45 S3 setups below-cost confirmed); expectancy
   n/a (n=0, honestly reported); H-R1 holds as deep-rejection
   calibration. The W4B counterfactual comparison is execution-blocked,
   not data-blocked — the frozen design awaits a runner.
3. **Exchange operation — CONDITIONAL (unchanged, prep advanced).**
   Credential-free paper, demo guards, read-only readiness verified;
   drill kill-on-miss armed and tested; signed/credentialed legs still
   blocked on owner credentials; prod submission disabled by design.

## 8. Identities

- Reviewed baseline tag: `review-0d40ad3-baseline` = `0d40ad3`.
- ROUND-01: sha `f08fa9c507a5ef17`; ready hypotheses `trials/ready-01.json`.
- cap-30min sha256 `76c9137f…e58792e` (611,979,689 B);
  cap-2h sha256 `2f1b5cc6…17c490` (1,548,306,631 B).
- Linux images: `w3batt` (no ps), `w3batt-ps` (colima-retained).
