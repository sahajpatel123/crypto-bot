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
  (SYNTH_V1 fixture → real S1 baseline intent → coordinator → risk stub → fake venue → report).
  Every synthetic input is labelled. Risk gate stays a stub until V-001 lands.
  Not a validated trading system.
- `pytest -q` — maintained tests (87 green on main: coordination + market-data +
  execution + strategies suites).
- `python tools/generate_evidence.py` — reproducible status-evidence collector.

Worker-owned entry points (accepted, live on main):

- `python tools/capture_public.py discover` — list current USDT-perp symbols
  from Binance USD-M metadata (no hardcoded whitelist).
- `python tools/capture_public.py capture` — record public klines to JSONL
  under data/observed/.
- `python tools/replay_public.py --in <recording>` — deterministic replay
  with gap/stale detection.

Accepted scope so far: E-001 (market data + execution skeleton + observed
sample), Q-001 (S1 baseline + fixtures + preregistered EXP-001), V-002 (S1
verification, clean), E-002 (Nautilus trial, blocked-on-transfer; pin stays
a proposal per D-011). In flight: E-003 (v0.1.1 execution side + crash fix,
Worker 2) and V-001R (independent risk reproduction, Worker 1). V-001 risk
policy is review-passed, landing after independent reproduction. Historical
research, live-feed paper trading and fault/integration harnesses are tracked
in [coord/tasks.json](/Users/sahajpatel/Code/cryto-bot/coord/tasks.json).
Documented commands only; no invented package commands in status reports.

## Safety

No withdrawal-enabled credentials, fund transfers, paid subscriptions, external
publication or live orders. Research and verification workers use public or
simulation data only. Secrets are never pasted into messages, commits or logs.
