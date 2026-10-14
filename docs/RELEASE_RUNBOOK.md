# Crypto bot release — operator runbook

Locked environment: Python 3.14.6, `uv.lock` (NautilusTrader 1.231.0).
All commands run from the repo root with the locked env; no `/tmp` venv
prerequisite. Prefix: `uv run --locked --no-sync python -m cryptobot.cli`
(short: `cryptobot ...` below).

## Everyday commands (proven, exit codes observed)

| Command | Result |
|---|---|
| `cryptobot doctor --config configs/r2.toml` | 0 READY |
| `cryptobot readiness --config configs/demo.toml` | 3 BLOCKED (no creds; unsigned checks stand) |
| `cryptobot preflight --config configs/prod.toml` | 3 BLOCKED (no creds) / 0 READY-EXCEPT-SUBMISSION when green |
| `cryptobot reconcile --config configs/demo.toml [--expect-flat]` | 3 BLOCKED (no creds) / 0 FLAT or EXPOSED |
| `cryptobot run --mode replay --config <replay.toml> --capture <dir> --run-id <id> [--resume]` | 0, writes `report.json` (b-proof-1: 1.13M events, 601 s) |
| `cryptobot run --mode paper --config configs/paper.toml` | live paper (Nautilus sim venue) |
| `cryptobot run --mode paper --config configs/demo.toml` | 2 without `BINANCE_DEMO_KEY/SECRET`; live demo with them (private stream attached, halt-until-first-heal) |
| `cryptobot run --mode prod --config configs/prod.toml` | 3 BLOCKED (no creds) / 2 REFUSED at submission switch (full driver verified) |
| `cryptobot status --storage runs --run-id <id>` | 0 run state/counts/heartbeat |
| `cryptobot stop --storage runs --run-id <id> [--flatten]` | 0 stop requested (graceful/flatten) |
| `cryptobot report --run-dir runs/<id> --out <dir>` | 0 equity/daily/rejections CSVs + report.html |
| `cryptobot backtest --dataset <name> --splits mechanism --symbols A,B --armsets S1 --config <cfg> --out <dir> [--require-round R --round-params P --require-config C]` | 0 comparison.json |

Research scoring is gated: production round cells run only with
`--require-round/--round-params/--require-config` against a frozen
`trial
...[truncated 2481 chars]