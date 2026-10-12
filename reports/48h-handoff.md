# 48-Hour Integrated Assignment — Final Handoff

Integrated commit: `c6c567a` (main, pushed to
https://github.com/sahajpatel123/crypto-bot.git).
Suite: **825 passed, 0 xfailed** (base was 664 + 14 xfail at 01487ac).
Live trading: **disabled throughout; this handoff does not activate it.**

## Outcome 1 — Usable data and execution

- Benchmark cache promoted to E-009 v2 freeze (`transform_version=2`,
  manifest sha `e8255323…`, `verify_dataset` clean). Marks publish at
  close availability (ts-first tuples); Oct funding is absent-NULL with
  explicit status, never zero.
- WS transport drains app-buffered + TLS-pending data without kernel
  readability; fair round-robin service; 5s stale-partial reconnect.
- Readers are streaming (`iter_batches` + heap merge; no `read_table` in
  non-test code). Partitions are checkpointed and shared across armsets.
- DepthStore priming seam (manager): replay installs
  `depth_snapshots.jsonl`; live REST-primes configured symbols; every run
  records a `depth-prime` checkpoint (never aborts a run).
- All 5 directive findings closed (Q-008: 1+3; E-009: 2/4/5 core;
  manager: ts-first marks, session gap view, `has_pending` fallback).

## Outcome 2 — Credible backtest results (v2, dev split, BTC+ETH, 200k causal prefix)

- `CASH|dev`: flat 120.00, 0 admitted, 0 fills (control, as expected).
- `COMBINED|dev`: 1 intent, 2 real ETH fills
  (BUY 0.024 @2543.65 / SELL @2539.73 — independently reproduces the
  Q-008 proof fills on the integrated tree), net −0.13%, costs 0.061.
- Determinism re-run identical modulo `run_dir`. Promotion rule: NONE.
- Limitation: archive replays have no depth snapshots, so books stay
  unsynced there (11,976 S5-ineligible windows recorded, not hidden);
  full 30d replay needs `run_replay` streaming (directive item 57).

## Outcome 3 — Operational readiness

- Fresh 90s capture (`data/captures/cap-48h-90s`, with snapshots) →
  replay `replay-48h-90s`: 123,101 events, exit 0, both symbols synced.
- Live paper `paper-48h-120s` (Nautilus engine): 164,442 events, exit 0,
  REST-primed BTC+ETH, 0 failed.
- V-009 independent reconciliation: 4/4 checks pass on both runs, zero
  corruption; 3 follow-up findings (clock-domain, prime schema,
  stale count) all fixed in `c6c567a`.

## Runnable commands

```bash
uv run --locked --extra dev pytest -q          # 825 passed
uv run --locked python tools/capture_stream.py --symbols BTCUSDT,ETHUSDT --duration-s 90 --run-base data/captures --run-id <id>
uv run --locked python -m cryptobot.cli replay --capture data/captures/<id> --config configs/paper.toml --run-id <rid>
uv run --locked python -m cryptobot.cli run --mode paper --config configs/r2.toml --duration 120s --run-id <rid>
uv run --locked python -m cryptobot.cli backtest --dataset benchmark-30d --out <dir> --config configs/paper.toml --splits dev --armsets CASH,COMBINED --symbols BTCUSDT,ETHUSDT --max-events 200000
```

Evidence: `/tmp/bt48h/dev/comparison.json`, `/tmp/bt48h/combined/comparison.json`,
`runs/replay-48h-90s/report.json`, `runs/paper-48h-120s/report.json`,
`coord/outbox/{EV-001,OP-001,Q-008,E-009,V-008,V-009}.json`.

## Worker status

W1 whisper-redshift Q-008 accepted; W2 cloud-vega E-009 accepted;
W3 cool-amalthea V-008 + V-009 accepted; W4 white-aldebaran EV-001
accepted; W5 crystal-parallax OP-001 accepted. All idle, standing by.

## Readiness decision

**Paper-ready, not live-ready.** Replay/paper loops, causal data,
bounded streaming, reconciliation, and protection paths are verified
end to end. Live trading needs: test-split scoring (once), dev/val
tuning of anomaly thresholds, Oct funding backfill, full-30d streaming
replay, and a funded-venue drill — none of which this deadline
activated.
