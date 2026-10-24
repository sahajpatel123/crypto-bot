# Crypto scalping bot — Bot v0.1 application

Status (2026-10-24): **no strategy has a validated edge — do not trade
real money** (see [RESEARCH_VERDICTS.md](RESEARCH_VERDICTS.md) and
[REAL_CAPITAL_READINESS.md](REAL_CAPITAL_READINESS.md)). The live route
exists but is disabled by default and refuses any strategy that a PASS
verdict did not score; [LIVE_RUNBOOK.md](LIVE_RUNBOOK.md) describes it.
Production submission is disabled by default (see `configs/prod.toml`:
`allow_live_submission = false`, plus the `gate` + `arm` evidence chain). The
E-007 Nautilus paper adapter IS integrated
(`src/cryptobot/adapters/paper_engine.py` exists; an older revision of this
README claimed it missing — corrected in T0.4); the reference engine still
refuses paper by construction.

This repository is managed by the engineering manager session (young-polaris)
coordinating exactly three worker sessions. See [DECISIONS.md](/Users/sahajpatel/Code/cryto-bot/DECISIONS.md),
[CONTRACTS.md](/Users/sahajpatel/Code/cryto-bot/CONTRACTS.md) and [coord/README.md](/Users/sahajpatel/Code/cryto-bot/coord/README.md).

## Quick start (locked environment)

```sh
uv sync --locked --extra dev
uv run --locked cryptobot doctor --config configs/paper.toml
uv run --locked pytest -q
```

## Data use audit (retained stores)

The project keeps large observed datasets outside git.  One read-only command
proves every retained store is present, hash-verified, and actually readable
by its consumer (benchmark, pilot, lake, holdout metadata, recorder, vault,
and the reserved confirmation campaign):

```sh
uv run --locked cryptobot data assets --json-out reports/data-use/audit.json
```

`tools/eval_h123.py` and `tools/eval_h4.py` run the benchmark preflight
before scoring, so a missing or hash-mismatched `datasets/cache` fails closed.
`tools/recorder_book_scan.py` uses the recorder's full-depth snapshots for an
H1 signal-frequency diagnostic (no fills; not a verdict).  Current evidence
and gaps are recorded in [reports/DATA_USE.md](reports/DATA_USE.md).


## Application commands (manager-owned, current)

```sh
uv run --locked cryptobot doctor --config configs/paper.toml [--capture DIR]
uv run --locked cryptobot run --mode replay --config configs/paper.toml --capture <retained-capture-directory> [--expect-class observed-public] [--run-id ID] [--resume]
uv run --locked cryptobot replay --capture <retained-capture-directory> --config configs/paper.toml
uv run --locked cryptobot status --run-id <actual-run-id>
uv run --locked cryptobot stop --run-id <actual-run-id> [--flatten]
```

- `run --mode paper` runs on the integrated E-007 Nautilus paper adapter
  (`src/cryptobot/adapters/paper_engine.py`). It never routes through a live
  client and needs no credentials. (This bullet previously claimed the
  adapter was missing; corrected in T0.4.)
- Replay runs strategies (S1–S4; S5 after the Q-005-F1 adapter fixup) through
  selector → risk → fee-bearing reference fills → protective exits → ledger,
  with crash/resume recovery. Reference fills are loop mechanics, not profit
  evidence. Economics await the Nautilus paper path (E-007) and V-006 hardening.
- Per-run evidence lives under `runs/<run-id>/` (untracked): `report.json`,
  `report.md`, `ledger.json`, `order_manager.jsonl`, plus the shared
  `runs/cryptobot.db` SQLite store. See [reports/runs_index.md](/Users/sahajpatel/Code/cryto-bot/reports/runs_index.md)
  for the current run log format. Historical outputs (`reports/m1_report.json`,
  `data/observed/stream_cap-30min_report.*`) are frozen records, not current
  results.

Worker-owned entry points (accepted, live on main):

- `python tools/capture_public.py discover` — list current USDT-perp symbols
  from Binance USD-M metadata (no hardcoded whitelist).
- `python tools/capture_public.py capture` — record public klines to JSONL
  under data/observed/.
- `python tools/replay_public.py --in <recording>` — deterministic replay
  with gap/stale detection.
- `python tools/replay_stream.py replay --run-dir <capture>` — numeric
  per-symbol ordered full-record bar agreement (mutating any value, adding a
  duplicate, or removing a record fails the gate).

Accepted scope so far: E-001 through E-007 (E-007 in flight: Nautilus runtime),
Q-001 through Q-005 (Q-006 + Q-005-F1 in flight), V-001 through V-005 (V-006 in
flight). No strategy is validated; nothing here is profitability evidence.
Task state lives in [coord/tasks.json](/Users/sahajpatel/Code/cryto-bot/coord/tasks.json).
Documented commands only; no invented package commands in status reports.

## Safety

No withdrawal-enabled credentials, fund transfers, paid subscriptions, external
publication or live orders. Research and verification workers use public or
simulation data only. Secrets are never pasted into messages, commits or logs.
