# OWNER ACTIONS — things only the owner can do (credentials/host/demo)

Nothing in this program ever placed real or demo orders, read API keys,
or touched `data/captures/campaign-1day-20261017` (reserved untouched
confirmation data). Production submission stays OFF by default
(`configs/prod.toml: allow_live_submission = false`); it is enabled
only through `cryptobot gate` + `cryptobot arm` (T6.1), and even then
the prod path must be separately reviewed. This environment is
correctly NO-GO today: `cryptobot gate` prints `NO-GO` (verified).

## 1. Demo credentials + demo drill (T4.2/T4.3)

```sh
export BINANCE_DEMO_KEY=... BINANCE_DEMO_SECRET=...   # demo only, env only
uv run --locked cryptobot demo-drill --out drill.json
uv run --locked cryptobot run --mode paper --config configs/demo.toml --duration 10m
uv run --locked cryptobot readiness --config configs/demo.toml
uv run --locked cryptobot reconcile --config configs/demo.toml --expect-flat
```

Expected: drill JSON `verdict: PASS` with per-step pass/fail and
measured ack/protection latencies; readiness all PASS; reconcile FLAT.
Kill -9 mid-position, then rerun with `--resume --run-id <same>`:
recovered exposure must flatten before new entries. Then SIGTERM:
the run must flatten and confirm flat (or `--leave-protected` only
with confirmed live protection legs).

## 2. Latency probe on the candidate host (T2.3)

```sh
uv run --locked cryptobot latency-probe --out latency.json
```

Expected JSON with `rest_rtt_ms` and `clock_skew_ms`, verdict
`MEASURED-REST-ONLY`. Gate still needs WS feed-age p99 < 250ms and
drops < 0.1% measured on the host's live feed — collect from a paper
run's report (`dropped_feed`, feed-age stats) and record both numbers
next to `latency.json`. Do not arm without them.

## 3. Record real venue fixtures (T4.1)

With demo credentials, capture redacted responses (account, income,
openOrders, openAlgoOrders, leverageBracket, commissionRate) into
`tests/fixtures/recorded/` — strip keys/signatures/timestamps — then:

```sh
uv run --locked pytest tests/unit/test_binance_live_contract.py -q
```

## 4. Does countdownCancelAll preserve conditional stops? (T3.2)

On demo only: open a tiny position with a live STOP_MARKET algo leg,
call `countdownCancelAll`, then list open algo orders. Record whether
the stop survives in `OWNER_ACTIONS` evidence. Until a PASS record
exists, the watchdog (`tools/watchdog.py`) must flatten reduce-only
via its `--flatten-cmd`, never via countdownCancelAll.

## 5. Supervision + watchdog trial (T3.1/T3.2)

```sh
sudo cp ops/systemd/cryptobot.service /etc/systemd/system/
python3 tools/watchdog.py --heartbeat runs/heartbeat.json --max-age-s 90 \
  --flatten-cmd "<owner demo flatten command>"
```

Expected: >5 restarts/hour stays down (StartLimitBurst=5) + alert;
stale heartbeat with exposure triggers one flatten + exit code 3.

## 6. Arming (only after every gate is green) (T6.1)

```sh
export CRYPTOBOT_ARM_ACK="I UNDERSTAND LIVE CAPITAL IS AT RISK"
uv run --locked cryptobot gate --verdict-json verdict.json \
  --drill-json drill.json --latency-json latency.json --out gate.json
uv run --locked cryptobot arm --capital-usdt <X> --max-daily-loss <Y> \
  --gate-json gate.json
```

Expected today: gate `NO-GO` (no PASS verdict, no drill PASS) and
arm refuses (exit 2). First 10 trades after a real arm are canary
minimum-size (T6.3); promotion beyond canary is manual only.

## 7. Confirmation discipline (T5.4)

The campaign capture stays untouched until exactly one confirmation
run per hypothesis (H1–H3 in `research/prereg/`) is authorised. Log
the run in `research/DATA_LEDGER.md`. No re-runs, no tuning after.
