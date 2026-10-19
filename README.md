# cryptobot — evidence-gated crypto perp research and execution

Status: **NO-GO for live capital today.** Family A (H1–H6) has no dev
edge. Family B killed all seven hypotheses on the frozen gates after
the B4 leg-size correction (D-042). An earlier B4 holdout screen is
void and is not a pass. Arming still requires a human TTY. Read
[RESEARCH_VERDICTS_B.md](RESEARCH_VERDICTS_B.md).

Read [ARCHITECTURE.md](ARCHITECTURE.md), [SECURITY.md](SECURITY.md),
[RUNBOOK.md](RUNBOOK.md), [RESEARCH_VERDICTS.md](RESEARCH_VERDICTS.md),
and the single ordered [OWNER_ACTIONS.md](OWNER_ACTIONS.md).

## Quick start (no credentials needed)

From a fresh clone. These commands do not place orders and do not read keys.
The gate stays NO-GO. There is no demonstrated edge.

```sh
uv sync --locked --extra dev
uv run --locked --extra dev cryptobot doctor --config configs/paper.toml
uv run --locked --extra dev cryptobot selftest --all
uv run --locked --extra dev cryptobot final-status
uv run --locked --extra dev cryptobot owner
uv run --locked --extra dev cryptobot background status
```

`cryptobot selftest --all` is hermetic and talks only to localhost. A real
demo-account drill, legal access to the venue, and tax treatment are
owner steps (`cryptobot owner`). `cryptobot recorder start` is a separate
public-data smoke test and is not required for the quick start.

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

## Family B: low-frequency research on public history

Multi-year Binance Vision data (klines, funding, OI metrics) lives in a
versioned parquet lake (`data/lake/`, see `DATA_INVENTORY.md`). The
split is preregistered (`research/prereg/SPLIT.md`): DEV before
2024-01-01, sealed HOLDOUT after, FORWARD for paper. Slow strategies
(B1–B7, `research/prereg/B*.md`) run in a dual-engine backtester
(`research/slow_backtest.py`, differential-tested) with walk-forward
OOS, deflated Sharpe, PBO and reality-check statistics
(`research/slow_stats.py`).

```sh
python tools/run_family_b.py dev-all --lake data/lake/dev   # frozen 59-cell DEV eval
cryptobot autopilot run-once --root research/autopilot_b --family B
cryptobot verdict --holdout-screen --hypothesis B1 --config research/configs/B1.toml \
  --vault-root data/vault --vault-token <tok> --holdout-chunk <id> \
  --cell-params cell.json --lake data/lake/dev --dev-sharpe 1.2 \
  --out research/verdicts_b/B1.json
```

Family B states: REGISTERED → DEV_EVAL → {KILLED | FROZEN} →
HOLDOUT_SCREEN → {FAIL | SCREEN_PASS} → FORWARD_PAPER →
FORWARD_COMPARE → GATE_READY. The holdout is a SCREEN, not proof
(detectable Sharpe ≈ 0.98, see SPLIT.md). HOLDOUT bytes are hashed at
seal time and decoded only by `verdict` with a one-shot token.

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
