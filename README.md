# cryptobot — evidence-gated crypto perp research and execution

Status: **NO-GO for live capital today.** No strategy has a PASS verdict
(`research/verdicts/`). The arming path is built OFF and requires a human
TTY ceremony. The recorder, sealed vault, autopilot, calibration and
deployment kit are operational, so the system can discover (or disprove)
edge over time without further prompts.

Read [ARCHITECTURE.md](ARCHITECTURE.md), [SECURITY.md](SECURITY.md),
[RUNBOOK.md](RUNBOOK.md), [RESEARCH_VERDICTS.md](RESEARCH_VERDICTS.md),
and the single ordered [OWNER_ACTIONS.md](OWNER_ACTIONS.md).

## Quick start (no credentials needed)

```sh
uv sync --locked --extra dev
uv run --locked cryptobot doctor --config configs/paper.toml
uv run --locked cryptobot recorder start --out data/recorder --duration-s 120
uv run --locked cryptobot recorder verify --out data/recorder
uv run --locked cryptobot dashboard --out reports/dashboard.html
uv run --locked cryptobot autopilot status
uv run --locked pytest -q
```

`recorder start` is public data only. It writes hourly gzip chunks and a
hash-chained manifest. A short run is a smoke test, not confirmation data.

## Research loop

```sh
cryptobot research register --hypothesis H4 --prereg research/prereg/H4-cross-venue-lead-lag.md \
  --config research/configs/H4.toml --commit "$(git rev-parse HEAD)"
cryptobot autopilot run-once
cryptobot autopilot report
```

States: REGISTERED → DEV_EVAL → {KILLED | AWAIT_CONFIRM_DATA} → CONFIRM →
{FAIL | PASS} → PAPER_14D → PAPER_COMPARE → GATE_READY. A failed
hypothesis is permanently KILLED. Confirmation uses only sealed CONFIRM
chunks and a one-shot vault token.

## Confirmation and gate

```sh
cryptobot vault freeze --hypothesis H2 --config research/configs/H2.toml \
  --commit "$(git rev-parse HEAD)" --prereg research/prereg/H2-trend-vol-regime.md
cryptobot vault seal --source <sealed-chunk> --data-class CONFIRM --hypothesis H2
cryptobot vault issue-token --hypothesis H2
cryptobot verdict --vault-token <token> --vault-chunk <chunk-id> --hypothesis H2 \
  --config research/configs/H2.toml --family-size 6 --out research/verdicts/H2.json
cryptobot gate --hypothesis H2 --verdict-json research/verdicts/H2.json \
  --autopilot-state research/autopilot/state/H2.json \
  --cost-model research/cost-model.json --host-check host.json \
  --drill-json drill.json --latency-json latency.json \
  --watchdog-heartbeat runs/watchdog.json --config research/configs/H2.toml \
  --out gate.json --require-commit
```

The gate is NO-GO unless every machine check passes. `arm` is separate,
interactive, and refuses CI/non-TTY. It writes a record; it does not
submit an order.

## Safety invariants

- No live/demo orders are placed by research, tests or this repo's setup.
- Keys are env/0600-only and never logged; withdrawals must be disabled.
- One position; stop-first independent reduce-only exits; fail-closed on
  stale/unknown venue truth.
- Synthetic data is stamped and rejected by verdict/gate.
- Recorder writer overflow is counted and flagged, never silent.
- `data/captures/campaign-1day-*` is untouched confirmation data; only its
  metadata was read.
