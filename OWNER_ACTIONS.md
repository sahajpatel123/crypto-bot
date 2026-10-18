# OWNER ACTIONS — one ordered checklist

Only physical/credentialed steps remain. Commands assume the repo is at
`/opt/cryptobot`, the venv exists, and you are user `cryptobot` unless a
step says `sudo`. Never paste keys into chat, git or logs. Production is
NO-GO until the final two steps pass; today it is expected to be NO-GO.

Each step: run the command, compare with the expected output/pass
criteria, and keep the named file. If it fails, bring back that file and
the command output.

## 1. Provision the host

```sh
sudo bash deploy/bootstrap-ubuntu.sh
sudo cp deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo timedatectl set-ntp true
uv sync --locked --extra dev
uv run --locked cryptobot host-check --out host.json
```

Expected: `"verdict": "PASS"` with `python`, `open-files`, `disk`,
`time-sync-daemon`, `venue-rtt`, `clock-skew` all PASS.
Pass criteria: Python ≥3.12, nofile ≥4096, free disk ≥20GB, NTP
synchronized, RTT measured, |clock skew| ≤250ms.
On failure bring back: `host.json`.

## 2. Start the recorder (public data; no keys)

```sh
uv run --locked cryptobot recorder start --out data/recorder \
  --symbols BTCUSDT,ETHUSDT --disk-budget-mb 50000
# in another shell:
uv run --locked cryptobot recorder status --out data/recorder
uv run --locked cryptobot recorder verify --out data/recorder
```

Expected: `status.json` state `recording`; `verify` `"ok": true`, zero
gaps, a growing hash-chained `manifest.json`.
Pass criteria: chunks keep sealing hourly; `dropped` remains 0; verify
ok. Leave it running (systemd `cryptobot-recorder.service`).
On failure bring back: `data/recorder/status.json`,
`data/recorder/manifest.json`, `cryptobot recorder verify` output.

## 3. Add demo-only credentials

```sh
sudo install -m 600 /dev/null /etc/cryptobot.env
sudo editor /etc/cryptobot.env   # fill BINANCE_DEMO_KEY/SECRET only
```

In the Binance demo UI: disable withdrawals, enable trade-only, add the
host IP to the allowlist. Do not use production keys yet.
Pass criteria: key is demo/testnet only, 0600, withdrawals disabled,
IP allowlisted.
On failure bring back: `cryptobot readiness --config configs/demo.toml`
(never the key file).

## 4. Run the demo drill (owner-run; the agent never places orders)

```sh
export BINANCE_DEMO_KEY=... BINANCE_DEMO_SECRET=...   # demo only
uv run --locked python tools/demo_drill_live.py \
  --config configs/demo.toml --execute-orders --out drill.json
uv run --locked cryptobot readiness --config configs/demo.toml
uv run --locked cryptobot reconcile --config configs/demo.toml --expect-flat
```

Expected: `tools/demo_drill_live.py` writes `"verdict": "PASS"` with
measured auth/filter/leverage/entry/protection/flatten latencies;
readiness all PASS; reconcile FLAT.
Pass criteria: drill PASS, flat after the drill, no unknown orders.
If the drill fails, flatten in the demo UI and bring back `drill.json`.
Note: the offline `cryptobot demo-drill` command is intentionally
BLOCKED; it is a scaffold, not the credentialed drill.

## 5. Measure feed latency and drops on the host

```sh
uv run --locked cryptobot latency-probe --feed-seconds 120 --out latency.json
```

Expected: JSON with `rest_rtt_ms`, `clock_skew_ms`,
`p99_feed_age_ms`, `drop_rate`, and `"verdict": "PASS"`.
Pass criteria: p99 feed age ≤250ms, drop rate ≤0.1%, |clock skew|
≤250ms. Re-run at peak hours; keep the worst file.
On failure bring back: `latency.json`.

## 6. Ingest recorded demo fixtures

```sh
mkdir -p /tmp/recorded
# save redacted account/income/openOrders/openAlgoOrders/leverageBracket/
# commissionRate JSON responses into /tmp/recorded here
uv run --locked cryptobot fixtures ingest /tmp/recorded \
  --dest tests/fixtures/recorded
uv run --locked pytest tests/unit/test_binance_live_contract.py -q
```

Expected: `index.json` with SHA-256 per fixture; contract tests pass.
Pass criteria: no credential-like keys (the ingester refuses them), all
fixtures installed. On failure bring back: the ingester error and the
offending file name (not its contents).

## 7. Calibrate the cost model

```sh
# after paper/demo fills exist (fills.jsonl from the run directory)
uv run --locked cryptobot calibrate --fills runs/<run-id>/fills.jsonl \
  --out research/cost-model.json --previous research/cost-model.json
```

Expected: `"version"` increments; `slippage_bps`, `latency_ms`,
`taker_bps`, `spread_bps` are populated.
Pass criteria: version ≥1, costs did not decrease without a matching
PASS verdict (the tool refuses relaxation).
On failure bring back: `research/cost-model.json` and the command output.

## 8. Install the autopilot timer

```sh
sudo systemctl enable --now cryptobot-autopilot.timer
sudo systemctl start cryptobot-autopilot.service
uv run --locked cryptobot autopilot status
uv run --locked cryptobot dashboard --out reports/dashboard.html
```

Expected: every hypothesis has a state, power ETA where available, and a
daily report under `research/autopilot/reports/`.
Pass criteria: state machine advances without manual edits; recorder
keeps running. On failure bring back: `autopilot status` and the latest
daily report.

## 9. Wait for evidence (no action; the system accrues data)

- DEV_EVAL runs when a dev artifact exists.
- Promotion to AWAIT_CONFIRM_DATA requires >+2bps, bootstrap 90% lower
  bound >0, and ≥2/3 folds positive.
- Power ETA >120 days is reported IMPRACTICAL; do not force a run.
- A failed hypothesis is permanently KILLED.

Pass criteria: the autopilot reaches AWAIT_CONFIRM_DATA for at least one
hypothesis, or the terminal NO-EDGE report is generated. Do not tune a
frozen hypothesis.

## 10. Freeze and confirm (exactly once per hypothesis)

Only after a DEV promotion:

```sh
uv run --locked cryptobot vault freeze --hypothesis <H> \
  --config research/configs/<H>.toml --commit "$(git rev-parse HEAD)" \
  --prereg research/prereg/<H>.md
# seal a chunk recorded AFTER the freeze commit
uv run --locked cryptobot vault seal --source <chunk> \
  --data-class CONFIRM --hypothesis <H>
uv run --locked cryptobot vault issue-token --hypothesis <H>
uv run --locked cryptobot verdict --vault-token <token> \
  --vault-chunk <chunk-id> --hypothesis <H> \
  --config research/configs/<H>.toml --family-size 6 \
  --out research/verdicts/<H>.json
```

Expected: verdict PASS/FAIL/UNDERPOWERED. PASS requires ≥300 trades, CI95
lower >0, >0 at 2x cost, ≥60% non-negative days, drawdown in budget, Holm.
Pass criteria: exactly one run; if UNDERPOWERED, extend only with newly
sealed data (never re-run the same window).
On failure bring back: the verdict JSON and vault access log.

## 11. 14-day paper stage

The autopilot starts PAPER_14D automatically after a PASS. Let it run
continuously; do not change the frozen config. At the end:
`PAPER_COMPARE` must show realized expectancy within tolerance of the
confirmed estimate; only then does the state become GATE_READY.
On failure bring back: `research/autopilot/state/<H>.json` and the paper
run report.

## 12. Gate (machine evidence only)

```sh
uv run --locked cryptobot gate --hypothesis <H> \
  --verdict-json research/verdicts/<H>.json \
  --autopilot-state research/autopilot/state/<H>.json \
  --cost-model research/cost-model.json --host-check host.json \
  --drill-json drill.json --latency-json latency.json \
  --watchdog-heartbeat runs/watchdog.json \
  --config research/configs/<H>.toml --out gate.json --require-commit
```

Expected today: `"gate": "NO-GO"`. A GO requires every check true.
Pass criteria: GO with sealed provenance (never SYNTHETIC), fresh cost
model (≤30 days), fresh host-check/drill (≤7 days), measured WS
latency/drops, fresh watchdog heartbeat.
On failure bring back: `gate.json` (the false checks name the missing
evidence). Never edit gate.json.

## 13. Arm (human-only; interactive TTY)

```sh
export CRYPTOBOT_ARM_ACK="I UNDERSTAND LIVE CAPITAL IS AT RISK"
uv run --locked cryptobot arm --capital-usdt <small X> \
  --max-daily-loss <Y> --gate-json gate.json --out armed.json
# type the phrase when prompted, on a real terminal
```

Expected: `arm: ARMED record written armed.json`, canary 10 trades.
Pass criteria: gate GO, not expired, typed phrase, positive capital/daily
loss, interactive TTY (non-TTY/CI refuses), armed record contains the
gate hash. First 10 trades are minimum size; promotion is manual only.
On failure bring back: `gate.json` and the arm refusal text.

## 14. Post-arm supervision

```sh
sudo systemctl enable --now cryptobot-watchdog.service
uv run --locked cryptobot status --run-id <id>
uv run --locked cryptobot reconcile --config configs/prod.toml
```

Expected: watchdog heartbeat fresh (`runs/watchdog.json`), reconcile
matches the venue, no unknown outcomes. Any of these auto-halts/demotes:
slippage >1.5x assumed, rolling expectancy CI upper <0, unknown outcome
aged, daily stop, watchdog fire. Promotion is manual only.
On failure bring back: `runs/<id>/watchdog.json`, `risk.jsonl`,
`reconcile` output.
