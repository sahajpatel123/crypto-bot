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
  (metadata → replay → S1 stub intent → coordinator → risk stub → fake venue → ledger → report).
  Every synthetic input is labelled. Not a validated trading system.
- `pytest -q` — maintained tests.

Worker-owned entry points for discovery/capture, deterministic replay, historical
research, live-feed paper trading, fault/integration checks and evidence reports
are tracked in [coord/tasks.json](/Users/sahajpatel/Code/cryto-bot/coord/tasks.json).
Documented commands only; no invented package commands in status reports.

## Safety

No withdrawal-enabled credentials, fund transfers, paid subscriptions, external
publication or live orders. Research and verification workers use public or
simulation data only. Secrets are never pasted into messages, commits or logs.
