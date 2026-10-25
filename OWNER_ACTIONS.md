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
`time-sync-daemon`, `venue-rtt`, `clock-skew`, `dns-sinkhole` all PASS.
Pass criteria: Python ≥3.12, nofile ≥4096, free disk ≥20GB, NTP
synchronized, RTT measured, |clock skew| ≤250ms.
On failure bring back: `host.json`.

## Network: ISP DNS sinkhole (India/Jio)

Some ISP resolvers (observed: Reliance Jio) answer `*.binance.com` / `*.okx.com` with a dead
address, so every connect times out even though Binance is reachable. This is a DNS problem,
**not** a VPN or geo-block. It is opt-in and only for networks where host-check proves it:

```sh
uv run --locked cryptobot host-check --out host.json   # look for the dns-sinkhole row
# only if dns-sinkhole is FAIL (system address dead, DoH address connects):
export CRYPTOBOT_DOH=1          # every cryptobot command and network tool then re-resolves
                                # exchange hostnames over DNS-over-HTTPS
uv run --locked cryptobot host-check --out host.json   # dns-sinkhole: PASS (mitigated)
```

Cleaner alternative: set a public DNS (1.1.1.1 / 8.8.8.8) in the OS network settings. For
launchd/systemd/recorder lines see `tools/netshim/README.md`. Leave `CRYPTOBOT_DOH` unset on a
healthy network: it is off by default and never needed there.

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

## 15. Family B data refresh (public files only; no keys)

The long-history lake is Binance Vision USD-M data under `data/lake/`.
DEV is everything before 2024-01-01. HOLDOUT is sealed. Do not unzip or
parse `data/lake/holdout_raw/` except by `cryptobot verdict`.

```sh
# new months only; filename dates assign DEV / HOLDOUT / FORWARD
uv run --locked python tools/vision_pull.py plan --datasets klines fundingRate \
  --intervals klines:1d,1h --workers 16 --out data/lake/plan-refresh.json
uv run --locked python tools/vision_pull.py pull --plan data/lake/plan-refresh.json \
  --dev-dir data/lake/raw --holdout-dir data/lake/holdout_raw \
  --workers 16 --disk-floor-gb 10 --state data/lake/pull-refresh.json
```

Expected: new files checksum-match. Any file dated after 2026-10-17 is
FORWARD, not a second look at the sealed screen.
Pass criteria: pull exits 0; holdout files are sealed (hash only) before
anyone decodes them.
On failure bring back: the pull JSON summary.

## 16. Family B autopilot timer and forward paper

B1–B7 are KILLED on the corrected dev gates (D-042/D-043). Do not arm.
The file `research/verdicts_b/B4.json` is a voided screen from the
25%/leg bug. Do not treat it as a pass, and do not start forward paper
for a killed hypothesis.

```sh
uv run --locked python -c 'from cryptobot.research.autopilot import Autopilot; print(Autopilot("research/autopilot_b", family="B").run_once()["hypotheses"])'
```

Expected: every B hypothesis stays `KILLED`; `verify_log()` is empty;
no `armed.json`. The only path to forward paper is a new, separately
preregistered family, never a retune of B1–B7.
Pass criteria: no state transition out of KILLED; no arm file.
On failure bring back: `research/autopilot_b/transitions.json` problems.

## 17. Recorder disk and retention (owner resource step)

`cryptobot background status` projects recorder disk against the next
adjudication. Today it reports `disk_alert: true` (about 16 days of
disk against about 103 days to adjudication) and the recorder plist
stops at its 8192 MB guard. The recorder cannot run unattended to
adjudication on this disk without an external data root.

1. Attach a disk with enough free space and set `EXTERNAL_DATA_ROOT`
   (or `CRYPTOBOT_EXTERNAL_ROOT`) before starting the recorder.
2. Copy the recorder root there; verify `manifest.json` and
   `cryptobot recorder verify` before retiring a local copy.
3. Optional: `cryptobot compact --root <recorder>` writes zstd Parquet
   plus a hash-chained equivalence proof. Raw deletion is manual and
   only on a verified copy until manifest v2 lands.
Pass criteria: `projected_disk_days` exceeds `days_to_adjudication`
and `disk_alert` is false.
On failure bring back: the `background status` JSON.

## 18. Legal and tax (owner decision; not a code step)

Before any later arm, confirm from your own counsel:

1. You may access the venue from your jurisdiction.
2. How trading gains and losses are taxed where you file.

The software does not decide either point. Production stays NO-GO until
step 13 is done on a fresh GO gate after forward paper, and only then
with a small first tranche. 120 USDT cannot place the B4 BTC hedge
(quantity floors through the 0.001 step). 1,000 is the smallest of
120 / 1,000 / 10,000 that can. See RESEARCH_VERDICTS_B.md.
