# Backtest + performance shared interfaces (manager-owned)

Baseline: `59b1143` (nautilus 1.231.0 locked in project env). Contract:
CONTRACTS.md v0.2.0 + app_runtime_interfaces.md + this file.
All workers branch from origin/main tip, rebase before filing.

## Ownership (exact, no overlap)

| Area | Owner | Paths |
|---|---|---|
| Manager: integration, CLI (`backtest`/`report`), Session backtest mode + protection/timer/entry-bound wiring, selector cost admission, store, configs/datasets index, benchmark execution, paper | Manager (young-polaris) | `src/cryptobot/app/`, `src/cryptobot/cli.py`, `src/cryptobot/coordination/`, `configs/`, `datasets/*.toml`, `uv.lock`, `pyproject.toml`, `specs/backtest_interfaces.md`, `reports/*_index.md`, `tests/unit/test_app_*`, `tests/unit/test_session_*`, `tests/unit/test_selector.py`, `tests/unit/test_replay_*` |
| Data + execution (W2 cloud-vega) | W2 | `src/cryptobot/adapters/`, `src/cryptobot/market_data/`, `src/cryptobot/execution/runtime_*`, `datasets/manifests/`, `tests/unit/test_adapters_*`, `tests/unit/test_market_data_*`, `tests/unit/test_execution_*`, `coord/outbox/E-008.json` |
| Strategies + backtest harness (W1 whisper-redshift) | W1 | `src/cryptobot/strategies/`, `src/cryptobot/features/`, `src/cryptobot/research/`, `specs/strategies/`, `specs/cards/`, `tests/unit/test_strategies_*`, `tests/unit/test_research_*`, `coord/outbox/Q-007.json` |
| Risk + reporting (W3 cool-amalthea) | W3 | `src/cryptobot/risk/`, `src/cryptobot/accounting/`, `src/cryptobot/reporting/`, `specs/acceptance-*`, `tests/acceptance/`, `tests/ceo_review/test_runtime_*`, `coord/outbox/V-007.json` |

Frozen: ceo_review record tests, FakeVenue/OrderManager semantics (fault-test
tools; excluded from economic benchmarks). No worker touches another's paths.

## B1. Backtest execution path (one engine, one account policy)

- `cryptobot backtest` (manager CLI) drives the SAME `Session._ingest` path as
  paper: strategies → selector → risk → Nautilus engine → ledger → store.
  ReferenceEngine is never instantiated in backtest/paper (constructor guard
  stays; tests select it explicitly with `reference-only` labels).
- Dataset iterators yield normalized events (same schema as live). Session
  runs on a virtual clock (W2) set from event time; no wall clock, no network,
  no wall restamping in replay. Determinism: same dataset + config + code
  fingerprint ⇒ identical fills/curve/metrics (stable execution IDs; UUID-like
  display IDs may vary only if results stay comparable — prefer deterministic
  IDs throughout).
- Missing seconds are preserved as gaps (BarMissing + gap flags), never
  compressed out. Stale-input evidence is retained in the report.

## B2. Engine additions (W2 implements, manager consumes)

```python
def account_margin(self) -> tuple[float, float]: ...
# (available_margin_usdt, free_margin_usdt) from the SIMULATED account.

def valuation_mark(self, instrument: str) -> float | None: ...
# Valuation-only mark. note_mark updates valuation ONLY and MUST NOT
# create an executable quote in economic mode (CEO probe: BBO 59999/60001
# + mark 60000 filled a buy at 60000 — forbidden). Fills cross actual
# bid/ask + liquidity from note_event quotes/trades/depth only.

def submit_protected(self, cmd: EngineOrder, limit_price: float) -> str: ...
# Price-protected marketable IOC: fills at-or-better than limit_price or
# not at all (supported nautilus policy). Session uses it for ALL entries;
# reject/expire the opportunity when bounds cannot be honored.

STRICT replay flag (W2's proposal, accepted): replay feed construction
fails closed on shuffled history; live stays receipt-lenient with ts_event
preserved. One flag, two documented behaviors, both tested.
```

- Leverage: simulator account leverage parameter aligns with
  `risk.leverage_cap` (same number, asserted at session start).
- Funding/settlement: engine emits EngineEvent(kind="funding") with signed
  amounts at real settlement times for the replayed window (sourced rates or
  explicitly assumed profile, labeled).

## B3. Timers independent of arrivals (W2 + manager)

- W2: bridge/dataset iterators yield `None` as a 1s idle heartbeat (never
  block longer than 1s on network/sleep/REST).
- Manager: session ticks monitor/risk timers, stop requests and duration on
  EVERY wake (event or heartbeat). Tests: silent feed advances timers, stop
  during silence lands <2s, expiring holding deadline fires without arrivals.

## B4. Book/flow views + S5 (W2 supplies, W1 consumes, manager wires)

```python
# W2: market_data/views.py
@dataclass(frozen=True)
class BookView: ...   # synchronized top-N levels + sync age + quality
@dataclass(frozen=True)
class FlowView2: ...  # signed trade aggregates + window + completeness
def book_flow_for(symbol, ts_ms, depth_store) -> tuple[BookView|None, FlowView2|None, str]: ...
# Third element is the precise ineligibility reason when views are absent.
```
- Session builds MarketView with synchronized views (or precise reasons) and
  passes mark-based valuation + funding events to accounting.
- Archive data without quotes/depth ⇒ labeled `research-spread-profile`
  execution assumption + sensitivity analysis (W1); S5 ineligible there with
  reasons, never estimated BBO presented as observed.

## B5. Datasets (W2 acquires/freezes, W1 consumes via API)

- `datasets/captured.toml` → retained run-dirs + per-file sha + channels +
  gap inventory (immediate benchmark).
- `datasets/benchmark_30d.toml` → frozen 30-accounting-day manifest: archive
  URLs, published checksums, coverage per symbol/day/channel, missing periods,
  filter profile used (historical or frozen-assumed, labeled). Target
  12 Sep–11 Oct 2026 IST-complete; availability-based fallback recorded BEFORE
  scoring. Offline replay after preparation (no fetch during runs).
- Reader API (W2, `market_data/datasets.py`): `open_dataset(toml) -> handle`
  with `.events(symbol, day)`, `.coverage()`, `.manifest_sha()`. Stream/chunk;
  never load a month of ticks into one list. Normalized Parquet partitioned by
  symbol/date/channel with observed-vs-modeled fields explicit.

## B6. Portfolio backtest harness (W1 owns, drives manager Session)

- `research/backtest.py`: runs each BASE strategy separately + combined bot +
  cash reference under one account/risk policy; enforces cooldowns, one
  position, expiry, sizing, margin, exits, daily pauses/halts, profit
  protection (all through Session — no parallel scoring).
- Frozen splits for 30d: dev days 1–15, validation 16–22, test 23–30
  (boundaries frozen in the harness; purged entry/holding overlap; causal
  warmup; test scored once). No parameter search in the baseline.
- Strategy cards (`specs/cards/S1..S5.md`): inputs, setup, trigger, rejects,
  entry bounds/expiry, invalidation, stop/target/time, holding range, units.

## B7. Selector cost admission (manager implements)

Replace the 25bps cap with reward-vs-cost: admit requires
`planned_gross_reward_bps >= round_trip_cost_bps * min_reward_multiple`
(config, default 1.0) where round-trip = commission forecast + spread +
slippage + funding share from the Intent forecast + exit distance. Missing
reward ⇒ infeasible with reason. No win probabilities.

## B8. Protection invariant (manager implements, W3 verifies)

`protected` flips True ONLY when required stop quantity is acknowledged by
the engine AND verified via poll. On attach failure: entries blocked,
exposure retained as unresolved, bounded retries, then reduce-only emergency
close at realistic adverse modeled price/cost/delay. Never falsely protected.
Regressions through Session with a fault-injecting engine stub.

## B9. Reporting (W3 owns `reporting/`, manager persists run files)

- Session persists per-run: `fills.jsonl`, `equity.jsonl` (marked equity +
  open exposure per bar/heartbeat), `rejections.jsonl`, `risk.jsonl`
  (transitions), `ledger.json`, `config.toml`, `dataset_manifest.json`.
- W3 `reporting/build.py` reads those (+ store) and writes: `summary.json`,
  `trades.csv`, `equity.csv`, `daily_returns.csv`, `rejections.csv`,
  `report.html` (standalone, embedded charts, no CDN). Metrics per directive
  §3 table; every number reconciles to episodes/fills/funding/cash.
- Position episodes: one row per completed position (strategy owner, entry/
  exit legs, fees, funding share, exit reason, holding, MFE/MAE if available).
  Partials are legs, not episodes. End-of-data closes labeled.
- `cryptobot report --run-dir` rebuilds all artifacts from persisted files.

## B10. Ingestion performance (W2 profiles, manager trims session writes)

- Bounded queues/history everywhere; isolate network/snapshot reads from the
  decision loop; no fsync-per-tick of unchanged health state (heartbeat
  batching stays, per-event store writes go).
- Report queue lag + healthy coverage in every run; stale events labeled,
  never concealed.
