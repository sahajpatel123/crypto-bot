# LIVE RUNBOOK — from clone to (small) real trading

Read this top to bottom before funding anything. The bot trades Binance
USD-M perpetuals (strategies S1–S5) with hard risk limits: ≤0.125% of
equity risked per trade, ≤3x leverage, 0.5%/1% daily operating/emergency
stops, one position at a time, protective stop attached after every fill.

**Honest warning:** no strategy in this repo has yet produced a
hash-bound PASS verdict (≥300 trades, 95% CI lower bound > 0, positive
at 2× costs). The machinery is complete and guarded; profitability is
NOT proven. Trade only money you can afford to lose, start at the
canary size, and let the gate — not optimism — decide.

## 0. Install

```sh
uv sync --locked --extra dev
uv run --locked cryptobot doctor --config configs/paper.toml
uv run --locked pytest -q   # expect: all green
```

## 1. Keys (you do this last, in your own terminal)

Create a Binance USD-M API key with **Futures trading enabled,
withdrawals DISABLED**, IP-restricted to your trading host. Export:

```sh
export BINANCE_DEMO_KEY=... BINANCE_DEMO_SECRET=...       # demo first
export CRYPTOBOT_API_KEY=... CRYPTOBOT_API_SECRET=...     # prod, later
```

Keys are read only from the environment. They never belong in TOML,
files, chat, or git (see `.env.example`).

## 2. Paper trading (no keys, no risk) — do this first

```sh
uv run --locked cryptobot run --mode paper --config configs/r2.toml --duration 24h
uv run --locked cryptobot status --run-id <run-id>
uv run --locked cryptobot report --run-dir runs/<run-id>
```

Watch `report.json`: `pnl_stress.pnl_2x` (P&L at double costs) matters
more than the headline return.

## 3. Demo drill (fake money, real venue mechanics)

```sh
uv run --locked cryptobot demo-drill --out drill.json
uv run --locked cryptobot run --mode paper --config configs/demo.toml --duration 10m
uv run --locked cryptobot readiness --config configs/demo.toml
uv run --locked cryptobot reconcile --config configs/demo.toml --expect-flat
```

Then chaos-test: `kill -9` mid-position, rerun with `--resume`, and
SIGTERM once — the run must flatten (or stay protected) every time.

## 4. Measure your host

```sh
uv run --locked cryptobot latency-probe --ws-seconds 120 --out latency.json
```

Gate needs `ws_p99_ms < 250` and `drop_rate < 0.001` in that file.

## 5. Earn a verdict (the edge gate — no shortcuts)

Score a frozen strategy on untouched data, then:

```sh
uv run --locked cryptobot verdict --trades trades.jsonl --hypothesis <ID> \
  --strategies <runtime strategy ids> --config configs/paper.toml \
  --family-size <N> --out verdict.json
```

Only `verdict: PASS` counts. UNDERPOWERED means keep collecting data.
`--strategies` names the runtime strategies that produced the trades;
the gate carries them (and the scored code commit), and prod refuses
any enabled strategy outside that list or any other commit. As of
2026-10-24 no hypothesis has a PASS (H2 was killed on history).

## 6. Gate + arm (only when 3–5 are green)

```sh
export CRYPTOBOT_ARM_ACK="I UNDERSTAND LIVE CAPITAL IS AT RISK"
uv run --locked cryptobot gate --verdict-json verdict.json \
  --drill-json drill.json --latency-json latency.json --out gate.json
uv run --locked cryptobot arm --capital-usdt 200 --max-daily-loss 10 \
  --gate-json gate.json --out armed.json
```

`arm` needs an interactive terminal and retyping the phrase. The gate
expires in 24h and binds the evidence files by SHA-256.

## 7. Go live — canary first

In `configs/prod.toml` set `allow_live_submission = true` (only now),
confirm `symbols`, then:

```sh
uv run --locked cryptobot preflight --config configs/prod.toml
uv run --locked cryptobot run --mode prod --config configs/prod.toml \
  --gate-json gate.json --armed-json armed.json --duration 24h
```

The first 10 trades are automatically minimum-size (canary). Promotion
beyond canary size is manual: re-arm with a larger `--capital-usdt`.

## 8. Stop / supervise

```sh
uv run --locked cryptobot stop --run-id <run-id> --flatten
python3 tools/watchdog.py --heartbeat runs/heartbeat.json --max-age-s 90 \
  --flatten-cmd "<your flatten command>"
sudo cp ops/systemd/cryptobot.service /etc/systemd/system/  # optional
```

Daily routine: `reconcile --expect-flat` before starting, review
`report.json` after stopping, never re-arm on a red day.

## Hard refusals you should expect (they protect you)

| Refusal | Meaning | Fix |
|---|---|---|
| `BLOCKED on CRYPTOBOT_API_KEY/...` | keys not exported | step 1 |
| `REFUSED — allow_live_submission is false` | config switch off | step 7 |
| `REFUSED — need a valid GO gate.json...` | gate/armed missing, expired, or mismatched | step 6 |
| `gate: NO-GO` | verdict/drill/latency not PASS | steps 3–5 |
| `account:stale-cache` / `risk:liquidation-gate` | stale venue data or stop too close to liquidation | wait / do not override |
