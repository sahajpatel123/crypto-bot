# Crypto scalping bot — research and simulation (M0/M1)

Status: implementation authorised for simulation and research only. No live orders.
Mode: replay/offline simulation first; live-feed paper trading is the next runtime mode.

This repository is managed by the engineering manager session (young-polaris)
coordinating exactly three worker sessions. See [DECISIONS.md](/Users/sahajpatel/Code/cryto-bot/DECISIONS.md),
[CONTRACTS.md](/Users/sahajpatel/Code/cryto-bot/CONTRACTS.md) and [coord/README.md](/Users/sahajpatel/Code/cryto-bot/coord/README.md).

## Quick start (project-local environment)

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python tools/m1_vertical_slice.py --help
pytest -q
```

## Entry points (manager-owned, evolving)

- `python tools/m1_vertical_slice.py` — M1 runnable vertical slice on synthetic data
  (SYNTH_V1 fixture → real S1 baseline intent → coordinator → real risk gate
  → inline fake venue → report). Every synthetic input is labelled.
  Rewire to the shared OrderManager/replayer/ledger is in flight per the CEO
  review directive. Not a validated trading system.
- `pytest -q` — maintained tests (170 green on main: coordination +
  market-data + execution + strategies + risk/ledger + evidence-gate suites).
- `python tools/generate_evidence.py` — evidence gate: exits nonzero when a
  required check fails; `--json-out` writes a machine-readable result.

Worker-owned entry points (accepted, live on main):

- `python tools/capture_public.py discover` — list current USDT-perp symbols
  from Binance USD-M metadata (no hardcoded whitelist).
- `python tools/capture_public.py capture` — record public klines to JSONL
  under data/observed/.
- `python tools/replay_public.py --in <recording>` — deterministic replay
  with gap/stale detection.

Accepted scope so far: E-001 through E-004 (market data, execution
lifecycle, v0.1.1 handoff, data fix), Q-001/Q-002 (S1/S2 baselines, S3/S4
specs, preregistered EXP-001/EXP-002), V-001/V-001R/V-002/V-003 (risk policy,
independent reproduction, S1 verification, slice wiring). In flight per the
CEO review directive: V-004 (ledger + risk corrections, Worker 3), E-005
(partial fills + recovery, Worker 2), Q-003 (independent reproduction +
executable experiments, Worker 1). No strategy is validated; S3/S4/S5 and
the selector await the corrected research path. Task state lives in
[coord/tasks.json](/Users/sahajpatel/Code/cryto-bot/coord/tasks.json).
Documented commands only; no invented package commands in status reports.

## Safety

No withdrawal-enabled credentials, fund transfers, paid subscriptions, external
publication or live orders. Research and verification workers use public or
simulation data only. Secrets are never pasted into messages, commits or logs.
