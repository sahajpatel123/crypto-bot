# CORR handoff — correction assignment (final, manager)

Reviewed baseline: tag `review-cdcd10c-baseline` = `cdcd10c`.
Integrated HEAD: `1e65267` (final; code-identical to `1294528` plus
evidence/handoff docs and the origin PR-#1 merge).
Suite: **1107 passed, 1 skipped, 0 failed**. Production order submission
stayed disabled throughout. No live orders. No credentials in repo.

## 1. Integrated commits (main, all pushed)

| SHA | Content |
|---|---|
| `db58f3b` | Review inputs preserved (directive + probes + results + local repro) |
| `4a2d297` | Manager exchange boundary (demo.toml, readiness, prod-refuse, CONFIG-ONLY preflight) |
| `36e5b47` | W4 phase A: ROUND-01 allowlist + funnel v2 (from worktree) |
| `b88117b` | W5: nested-deadline battery + run_budget repair (merge) |
| `8f5710c` | W3: symbol-scoped freshness + dataset audit + warmup export (merge) |
| `86e5818` | W1: due-time IOC execution M1 (merge, after fixup ruling) |
| `b58fe67` | W2: v2 checkpoints + standing restart-equivalence regression (from worktree) |
| `3b83d7c` | Manager acceptance gate (10 reviewer-probe assertions, permanent) |
| `b92f9b2` + `c98075b` | W1 evidence staging + late W3 filing |
| `ed26d75` | W4 phase B: gated economic scoring code + panels inputs |
| `56c6c97` `3135656` `2281a7f` | W5 addenda (W1/W3/M1/W2 reviews + e2e, cherry-picked) |
| `1294528` | Manager: nested-test flake fix (enforcement + identity assertions) |
| `f9360c2` | Manager: this handoff + phase-B evidence package |
| `1e65267` | Merge origin/main (PR #1: W5 addenda 1–2; report-only, no code delta) |

## 2. Runnable bounded commands (all ≤30min jobs, verified)

```
# Full suite (275s of 1500s budget)
python3 tools/run_budget.py --budget-s 1500 --checkpoint-dir <ck> --report-out <rep> \
  -- uv run --locked --extra dev pytest -q -p no:cacheprovider

# Reviewer probes (3.2s of 300s) — HISTORICAL: the aggregate cdcd10c probe
# raises TypeError on this HEAD (freshness now requires a symbol argument).
# Rerun only its ioc/checkpoint/nested legs, or use the acceptance gate and
# Crypto_Bot_CORR_Independent_Probes.py instead. Never presented as verified
# in aggregate form on this HEAD.
PYTHONPATH=src .venv/bin/python Crypto_Bot_cdcd10c_Review_Probes.py

# Manager acceptance gate (4s of 300s)
uv run --locked --extra dev pytest tests/unit/test_corr_review_acceptance.py -q

# Adversarial deadline battery + budget self-tests (75s of 600s)
uv run --locked --extra dev pytest tests/runtime/test_nested_deadline_adversarial.py \
  tests/unit/test_run_budget.py -q

# Restart-equivalence regression (9s)
uv run --locked --extra dev pytest tests/unit/test_bench_restart_equivalence.py -q

# Dataset audit (6s / 16s)
PYTHONPATH=src .venv/bin/python tools/audit_dataset.py --dataset datasets/cap_30min.toml
PYTHONPATH=src .venv/bin/python tools/audit_dataset.py --dataset datasets/cap_2h.toml

# One scoring cell, S1 on cap-30min (327s of 1500s, manager re-ran)
python3 tools/run_budget.py --budget-s 1500 --checkpoint-dir <ck> --report-out <rep> \
  -- uv run --locked --extra dev python -m cryptobot.research.backtest \
  --dataset cap-30min --splits mechanism --symbols BTCUSDT,ETHUSDT --armsets S1 \
  --config configs/round01/R01-S1.toml --require-round trials/round-01.json \
  --require-config R01-S1 --out <out>

# Re-score all 10 panels from run dirs (deterministic, byte-identical)
uv run --locked --extra dev python tools/score_phaseb.py

# Read-only venue readiness (exit 3 = signed checks BLOCKED, no creds)
uv run --locked --no-sync python -m cryptobot.cli readiness --config configs/demo.toml
uv run --locked --no-sync python -m cryptobot.cli readiness --config configs/prod.toml

# Prod route (always REFUSES while disabled)
uv run --locked --no-sync python -m cryptobot.cli run --mode prod --config configs/prod.toml
```

## 3. Finding → cause → fix → independent proof

| # | Finding (reviewer) | Cause | Fix (owner → SHA) | Independent proof |
|---|---|---|---|---|
| 1 | Marketable IOC fills at 10s-later quote (90) | Tick-driven matching priced executions off future ticks | W1 due-time M1: IOC resolves at due time vs standing arrival book; pre-flush pricing; touch+size gate; opportunity-counted sweep → `86e5818` | Reviewer probe: fill @101 by 200ms, nothing at 10s; manager acceptance 3/3; W5 APPROVE + M1 APPROVE (timestamp nuance: occurrence at first opportunity after due, price at due-time book) |
| 2 | Checkpoint omits trading context (135 bars → 0 feeds, unwarm) | Snapshot saved ledger/cooldowns only | W2 v2 20-field preserve snapshots (feeds/bars/aggs, depth, engine, store cursors, files) → `b58fe67` | Probe: 135+warmed → 1 feed+warmed; W5 reran harness on integrated tree: ref/det/flat/expo COMPLETE + parity; standing regression 9s green |
| 3a | Completed round-trip called not-flat | `open_orders()` history counted as exposure | `_is_flat` counts only open/partial orders; terminal = history → `b58fe67` | Probe round-trip flat True; W5 APPROVE; 6→12 bench tests, none dropped |
| 3b | Orphan 0.5qty ledger called flat | Ledger/engine/policy unchecked | `_is_flat` spans position/flatten/ledger/engine-queues/IOC/positions/reservations/unresolved; unreadable → not flat → `b58fe67` | Probe orphan False; changed-config refused (10-key identity); exposed end = INCOMPLETE_EXPOSURE |
| 4 | Freshness not candidate-scoped (BTC admits/blocks ETH) | Gateless `_quote_age_gate()` + first-feed-wins mark | W3 `_quote_age_gate(symbol)`; executable vs exchange-mark ages; exchange-time stamping; per-candidate gating; fail-closed malformed → `8f5710c` | Probe matrix fixed both directions; manager acceptance 3/3; W5 APPROVE |
| 5 | Nested deadline unreliable (8.07s vs 1.12s report) | Daemon-reparent escape + pipe-blocked caller + ps-fail-open | W5 repair: Linux subreaper, birth-registry kill identity, output relay, fail-closed verified/UNVERIFIED → `b88117b` | Battery 10/10 (4 pre-fix holes proven, stash-verified); budget 5/5; manager gate asserts enforcement + pgrep identity |
| 6 | ROUND-01 vs runtime arms disagree; "18 arms"; funnel counts rows not decisions | `arms=all` resolved 11 arms incl. registry-excluded S2-V/S2-F; funnel buckets counted repeated rows | W4A: mechanical allowlist gate + `round01.toml` + 11 per-config TOMLs; funnel v2 (8 stages, unique decisions, symbol-time, original-verdict paths) → `36e5b47` | `allowlist --enforce` ok (9 arms, sha f08fa9c5); gated slice zero excluded rows; 15/15 focused; banked closes 11/1 reproduce |
| 7 | Paper falsely needs demo keys; preflight claims GO; prod route missing | Docs claimed paper needs keys; preflight printed production GO; no `run --mode prod` | Manager boundary: `demo.toml` split + `exchange-modes.md`; read-only `readiness` (GET-only, exit 0/2/3); prod route verifies-then-refuses; CONFIG-READY relabel → `4a2d297` | 9 CLI + 3 adapter tests; readiness 5 PASS + 1 BLOCKED live with no creds; values never echoed |
| 8 | No usable strategy evidence on corrected stack | Archive marks 60s vs 1s gate; pre-gate base rate ~1/day | W4B: gated singles+CASH on W3-audited captures (no tuning) → `ed26d75` | 10/10 cells zero-trade, 62/62 setups reward-below-cost; booked P&L exactly 0; panels re-scored byte-identical + 1 cell re-run identical by manager; H-NEXT filed |

## 4. Elapsed times (all jobs under run_budget; zero overruns)

| Owner | Job | Elapsed / budget | Outcome |
|---|---|---|---|
| W1 | repro + decisive probes | 3.3–3.5s / 300s | defect before, fixed after |
| W1 | IOC suites (19 tests) | ~2s each | green |
| W1 | full suite | 161.8–168.4s / 1500s | 1030+1 green |
| W2 | review probes before/after | 3.2s / 3.4s | 4/4 fixed |
| W2 | acceptance harness (6 bench runs) | 9.9s | ref/det/flat/expo parity |
| W2 | touched tests (27) | 110.7s | green |
| W2 | full unit suite | 170.9s / 1500s | 811+1 green |
| W3 | freshness repro probe | 0.3s | both directions wrong → fixed |
| W3 | dataset audits | 6.1s / 15.6s | both SCORABLE |
| W3 | warmup exports | 306.5s / 726.7s | 65-min explained (t+3925s) |
| W3 | full suite | 163.4s / 1500s | 1043+1 green |
| W4A | gated slice + funnel | 29.6s / 1.2s | allowlist + v2 verified |
| W4A | full suite | 202.6s / 1500s | 1035+1 green |
| W4B | 10 scoring cells | 452–1481s / 1500–1800s | 10 CHILD_EXIT (+2 INCOMPLETE rerun solo) |
| W4B | full suite | 230.5s / 1500s | 1107+1 green |
| W5 | base probes | 3.0s | 4/4 reproduced |
| W5 | adversarial battery | ~65–75s | 10/10 |
| W5 | e2e on 3b83d7c | full suite | PASS (1 flake documented → fixed) |
| Mgr | reviewer probe + acceptance | 3.2s / 4.0s | repro + 10/10 gate |
| Mgr | full suites (4×) | 168–276s / 1500s | green |
| Mgr | panel re-score + S1 re-run | seconds / 327.4s | byte-identical panels |

Note (budget discipline): W4B used 1800s budgets on cap-2h cells (no
reserve) and hit 2 contention INCOMPLETEs at 1500.5s on first attempts;
both reran solo to completion and no partial output was scored. The next
assignment caps work at 1500s with reserve (see readiness plan §4).

## 5. Remaining blockers (at CORR close)

1. Owner demo/prod credentials (signed checks + credentialed drill).
2. One Linux CI run for the subreaper proof (macOS verified only).
3. Session-owned followups disclosed by W2: paper path never calls
   `policy.note_fill` (reservations expire to unresolved); protection
   leg qty-short wipe orphans live targets; no paper-path OCO.
4. Fresh held-out data for H-NEXT confirmation (captures now dev knowledge).

## 6. Three verdicts

1. **Software correctness — PASS.** All five reproduced defects fixed and
   independently verified; suite 1107+1 zero-fail.
2. **Exchange-operation readiness — CONDITIONAL.** Credential-free paper,
   demo routing/guards, and read-only readiness verified; signed checks
   blocked on owner credentials; prod submission disabled by design.
3. **Strategy profitability — NO.** Zero fills after realistic costs on
   the corrected stack; no strategy qualifies; H-NEXT is the next step.
   The 2–3% daily objective remains unsupported. Status: research/paper only.

## 7. Identities

- Reviewed baseline tag: `review-cdcd10c-baseline` = `cdcd10c`.
- Integrated code HEAD: `1294528` (docs/merge-only after).
- ROUND-01 registry + params: sha `f08fa9c507a5ef17`.
- cap-30min events: sha256 `76c9137f…e58792e`, 611,979,689 bytes.
- cap-2h events: sha256 `2f1b5cc6…17c490`, 1,548,306,631 bytes.

---
*Repair note: the committed file ended mid-table with a literal
truncation marker (rows 5+ and §§4–7 lost in transit). Reconstructed
2026-10-13 from the cited outbox filings, budget reports, panels, and
the banked chat record; every figure above re-verified against those
artifacts. The §2 aggregate-probe command is marked historical (raises
TypeError on this HEAD) and must not be presented as verified.*