# R3 24-hour paper session — owner launch package

R2 passed; R3 is ready to launch. It runs ~24h wall-clock, which exceeds
agent-managed sessions on macOS, so the owner launches it in their own
terminal (tmux recommended). No credentials are needed (public data +
simulated execution only); live trading stays disabled.

## Pre-flight (manager-verified 2026-10-12, main `e4ec8a1`+)

- Suites: 534 trial / 477+5 project, evidence gate PASS, M1 exit 0.
- R2 `r2-1h-003`: 1 live round-trip + kill -9 + resume, exit 0, flat.

## Launch (from `/Users/sahajpatel/Code/cryto-bot`)

```sh
tmux new -s r3-paper
cd /Users/sahajpatel/Code/cryto-bot
PYTHONPATH=/Users/sahajpatel/Code/cryto-bot/src \
  /tmp/cryto-bot-w2-e007/.venv-trial/bin/python -m cryptobot.cli run \
  --mode paper --config configs/r3.toml --duration 24h --run-id r3-24h-001 \
  2>&1 | tee /tmp/r3-24h-001.log
```

Config: paper + nautilus engine, BTCUSDT+ETHUSDT (throughput-bounded per
measured 2-symbol p50 118ms vs 8-symbol 3.7s lag), strict run-mode with
live venue filters, 120 USDT synthetic paper capital, 5bps labeled fees.

## Supervise (second terminal)

```sh
cd /Users/sahajpatel/Code/cryto-bot
uv run --locked cryptobot status --run-id r3-24h-001
uv run --locked cryptobot stop --run-id r3-24h-001 [--flatten]
```

Heartbeat cadence: 30s. Filter refresh: hourly. Day roll: IST midnight
(auto-reconcile). If the process dies, resume with the same command plus
`--resume` (same `--run-id`); resume re-warms (~130s) and flattens any
orphaned exposure first.

## Controlled interruption (R3 repeats the R2 drill once)

```sh
kill -9 <pid-from-status>
# then resume:
PYTHONPATH=/Users/sahajpatel/Code/cryto-bot/src \
  /tmp/cryto-bot-w2-e007/.venv-trial/bin/python -m cryptobot.cli run \
  --mode paper --config configs/r3.toml --duration 24h --run-id r3-24h-001 \
  --resume 2>&1 | tee -a /tmp/r3-24h-001.log
```

## Done criteria

Exit 0, `runs/r3-24h-001/report.json` written, position flat, ledger
reconciled. Report back: equity open/close, fills/fees, reject top-5,
latency blocks, interruption + resume record.
