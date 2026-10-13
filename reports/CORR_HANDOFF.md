# CORR handoff — correction assignment (final, manager)

Reviewed baseline: tag `review-cdcd10c-baseline` = `cdcd10c`.
Integrated HEAD: `ed26d75` + evidence/acceptance commits (see SHAs below).
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

## 2. Runnable bounded commands (all ≤30min jobs, verified)

```
# Full suite (275s of 1500s budget)
python3 tools/run_budget.py --budget-s 1500 --checkpoint-dir <ck> --report-out <rep> \
  -- uv run --locked --extra dev pytest -q -p no:cacheprovider

# Reviewer probes (3.2s of 300s)
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
| 5 | Nested deadline unreliable (8.07s vs 1.12s report) | Daemon-reparent escape + pipe-blocked caller + ps-fail-open | W5 repair: Linux subreaper, birth-registry kill identity, output relay, fail-closed verified/UNVERIFIED → `b88117b` | Battery 10/10 (4 pre-fix holes proven, stash-verified); budget 5/5; manager gate asserts enforcement+pgr
...[truncated 4672 chars]