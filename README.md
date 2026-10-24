# cryptobot — evidence-gated crypto perp research and execution

Status: **NO-GO for live capital today.** Family A (H1–H6) has no dev
edge. Family B killed all seven hypotheses on the frozen gates after
the B4 leg-size correction (D-042). An earlier B4 holdout screen is
void and is not a pass. Arming still requires a human TTY. Read
[RESEARCH_VERDICTS_B.md](RESEARCH_VERDICTS_B.md).
Status (2026-10-24): **no strategy has a validated edge — do not trade
real money** (see [RESEARCH_VERDICTS.md](RESEARCH_VERDICTS.md) and
[REAL_CAPITAL_READINESS.md](REAL_CAPITAL_READINESS.md)). The live route
exists but is disabled by default and refuses any strategy that a PASS
verdict did not score; [LIVE_RUNBOOK.md](LIVE_RUNBOOK.md) describes it.
Production submission is disabled by default (see `configs/prod.toml`:
`allow_live_submission = false`, plus the `gate` + `arm` evidence chain). The
E-007 Nautilus paper adapter IS integrated
(`src/cryptobot/adapters/paper_engine.py` exists; an older revision of this
README claimed it missing — corrected in T0.4); the reference engine still
refuses paper by construction.

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

`cryptobot selftest --all` is hermetic and talks only to localhost. It
runs the command matrix, risk/chaos/determinism acceptance subsets,
vault/verdict/gate/arm refusals, adjudicator branches, a recorder
smoke over emulator streams, host-check and background status. A real
demo-account drill, legal access to the venue, and tax treatment are
owner steps (`cryptobot owner`). `cryptobot recorder start` is a
separate public-data smoke test and is not required for the quick start.

## Operator commands (emulator/sandbox/demo only)

```sh
cryptobot ops status --mode emulator
cryptobot ops order --mode emulator --symbol BTCUSDT --side BUY --qty 0.002 --kind MARKET
cryptobot ops order --mode emulator --symbol BTCUSDT --side SELL --qty 0.002 \
  --kind STOP_MARKET --stop-price 60000 --reduce-only --client-id stop-1
cryptobot ops order --mode emulator --symbol BTCUSDT --side BUY --qty 0.002 \
  --kind LIMIT --price 59000 --post-only
cryptobot ops cancel --mode emulator --client-id stop-1
cryptobot ops cancel-all --mode emulator
cryptobot ops flatten --mode emulator --symbol BTCUSDT
cryptobot ops kill --mode emulator
```

Every action is journaled and refuses `--mode prod` without a valid
human arm. `sandbox` and `demo` are aliases for the in-process
emulator: no venue is contacted, and no real or demo order is placed.
The emulator drill (`cryptobot emulator drill`) is provenance EMULATED
and cannot satisfy the gate's demo-drill check.

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
## Data use audit (retained stores)

The project keeps large observed datasets outside git.  One read-only command
proves every retained store is present, hash-verified, and actually readable
by its consumer (benchmark, pilot, lake, holdout metadata, recorder, vault,
and the reserved confirmation campaign):

```sh
uv run --locked cryptobot data assets --json-out reports/data-use/audit.json
```

`tools/eval_h123.py` and `tools/eval_h4.py` run the benchmark preflight
before scoring, so a missing or hash-mismatched `datasets/cache` fails closed.
`tools/recorder_book_scan.py` uses the recorder's full-depth snapshots for an
H1 signal-frequency diagnostic (no fills; not a verdict).  Current evidence
and gaps are recorded in [reports/DATA_USE.md](reports/DATA_USE.md).


## Application commands (manager-owned, current)

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
