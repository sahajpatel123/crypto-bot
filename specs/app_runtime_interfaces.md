# App runtime shared interfaces (Bot v0.1, manager-owned)

Baseline: `1a3c070`. Contract: CONTRACTS.md v0.2.0 + this file.
All workers branch from origin/main tip, rebase before filing.

## Ownership (exact, no overlap)

| Area | Owner | Paths |
|---|---|---|
| A-001 app, CLI, selector, config, store, lifecycle/integration tests, README/reports index | Manager (young-polaris) | `src/cryptobot/app/`, `src/cryptobot/cli.py`, `src/cryptobot/__main__.py`, `src/cryptobot/coordination/selector.py`, `configs/`, `pyproject.toml`, `uv.lock`, `specs/app_runtime_interfaces.md`, `tests/unit/test_app_*`, `tests/integration/` |
| Q-005 strategies runtime boundary + S5 | W1 (whisper-redshift) | `src/cryptobot/strategies/`, `src/cryptobot/features/`, `specs/strategies/`, `tests/unit/test_strategies_*`, `coord/outbox/Q-005.json` |
| Q-006 EXP-003/004 execution + return evaluation | W1 (whisper-redshift) | `src/cryptobot/research/`, `tests/unit/test_research_*`, `specs/exp-*`, `coord/outbox/Q-006.json` |
| E-007 Nautilus runtime, data bridge, execution | W2 (cloud-vega) | `src/cryptobot/adapters/`, `src/cryptobot/execution/runtime_*`, `src/cryptobot/market_data/`, `tests/unit/test_execution_*`, `tests/unit/test_market_data_*`, `tests/unit/test_adapters_*`, `coord/outbox/E-007.json` |
| V-006 verification + risk/accounting hardening | W3 (cool-amalthea) | `src/cryptobot/risk/`, `src/cryptobot/accounting/`, `tests/acceptance/`, `tests/ceo_review/test_runtime_*`, `specs/acceptance-*`, `coord/outbox/V-006.json` |

Frozen: `FakeVenue` + `OrderManager` semantics (fault-test/reference only, no
competing fill engine). `tests/ceo_review/test_ceo_finding_*` (prior record).
No worker touches another worker's paths; shared changes go through the manager.

## Seams (import direction: app -> worker modules)

### S1. Runtime strategy boundary (Q-005 implements, manager consumes)

```python
# strategies/runtime.py (W1 owns)
@dataclass(frozen=True)
class MarketView:
    instrument: str
    bars: tuple[Bar | None, ...]  # ALIGNED slots oldest->newest; None = missing (F1).
                                  # Adapters never strip (time compression); anchor at last present.
    now_utc: datetime            # availability/causal time, tz-aware
    depth: DepthView | None      # synchronized book features or None + reason
    flow: FlowView | None        # signed trade aggregates or None + reason
    quality: DataQuality
    quality_reason: str = ""

@dataclass(frozen=True)
class StrategyOutcome:
    intent: Intent | None        # exactly one of intent / reject_reason set
    reject_reason: str = ""      # machine-readable: <stage>:<cause>
    exit_policy: ExitPolicy | None = None

class RuntimeStrategy(Protocol):
    strategy_id: str             # S1..S5 arm id from contract.ARM_IDS (+S5 arms)
    def evaluate(self, view: MarketView) -> StrategyOutcome: ...
```

Rules: `evaluate` is pure w.r.t. I/O (no network/disk/AI); bounded history
only (caller-provided window, no full-session scans); holding/expiry durations
use causal `now_utc`, never an invented earlier decision time. Every evaluation
returns an `Intent` or an explicit `reject_reason`.

### S2. Typed exit policy (manager owns type, W1 builds per strategy)

```python
# coordination/exits.py (manager owns)
@dataclass(frozen=True)
class ExitPolicy:
    stop_price: float            # invalidation-derived protective exit
    target_price: float | None   # None = no target (time/stop only)
    time_exit_utc: datetime      # entry_time + holding_limit (causal)
    reduce_only: bool = True
    policy_id: str = ""          # e.g. "S1:stop+target+time"

def encode_exit_rule(policy: ExitPolicy) -> str: ...   # -> Intent.exit_rule
def decode_exit_rule(rule: str) -> ExitPolicy: ...     # raises ValueError
```

`Intent.exit_rule` remains the wire format (v0.2.0 compat); runtime decodes it
to drive exits. Strategies MUST emit encodable rules; undecodable rule blocks
the intent at selection with reason `exit:undecodable-rule`.

### S3. Paper engine seam (E-007 implements, manager consumes)

```python
# adapters/paper_engine.py (W2 owns; Nautilus-backed)
@dataclass(frozen=True)
class EngineFill:
    execution_id: str            # globally unique; ledger dedup key
    client_order_id: str         # durable client id <-> reservation correlation
    instrument: str
    side: Side
    qty: float
    price: float                 # modeled executable price (taker cross), never assumed mid
    fee: float                   # modeled commission in quote (>= 0, labeled rate)
    ts_utc: datetime
    liquidity: str               # "taker" (maker disabled until queue model exists)

@dataclass(frozen=True)
class EngineEvent:
    kind: str                    # fill | cancel | reject | expire | funding
    payload: ...                 # EngineFill | EngineCancel | ...
    ts_utc: datetime

class PaperEngine(Protocol):
    # Canonical types live in src/cryptobot/app/engine.py; E-007 imports them.
    def submit(self, cmd: EngineOrder) -> str: ...
    def submit_immediate(self, cmd: EngineOrder) -> str: ...  # exits ONLY
    def resolve(self, client_id: str) -> str | None: ...
    def cancel(self, client_order_id: str, reason: str) -> None: ...
    def poll(self) -> list[EngineEvent]: ...         # non-blocking drain
    def attach_protection(self, entry_client_id: str, stop_price: float,
                          target_price: float | None) -> list[str]: ...
    def open_orders(self) -> list[EngineOrderStatus]: ...
    def filled_qty(self, client_order_id: str) -> float: ...
    def set_exit_only(self, halted: bool, reason: str = "") -> None: ...
    def note_mark(self, instrument: str, price: float) -> None: ...
    def recover(self, outcome_sink) -> None: ...
    def close(self) -> None: ...
```

Guarantees: nonzero configured submission/fill delay; taker crosses executable
side/depth with liquidity check; reduce-only conditional exits are independent
orders (no native futures OCO assumption); every simulator assumption logged at
startup (`doctor` prints them); forecast costs and booked fill costs never
double-charged. Paper mode MUST NOT instantiate or route through a Binance live
execution client (R0 proves by construction + test).

### S4. Risk/accounting hooks (V-006 hardens, manager calls)

Existing `RiskPolicy`, `plan_size`, `RiskState`, `Ledger` stay the entry points.
V-006 adds (backward-compatible): strict instrument-filter enforcement in run
mode (missing/stale filters block entries), available/free margin + fee buffers
+ in-flight exposure in sizing, real engine commission/funding ingestion
(`note_fill`/`note_funding` with nonzero fees; legacy fee=0.0 path stays only
for fault tests), timer-driven health monitor (`monitor_tick(now)` independent
of market traffic), idempotent event IDs for callback/recovery races.

### S5. Persistence (manager owns `app/store.py`, SQLite WAL)

Tables: `runs(run_id, mode, config_hash, started_utc, state, pid, heartbeat_utc)`,
`intents(run_id, intent_id, strategy, instrument, side, decision, reason, ts_utc)`,
`execution_events(run_id, execution_id UNIQUE, kind, payload_json, ts_utc)`,
`risk_transitions(run_id, ts_utc, from_state, to_state, reason)`,
`checkpoints(run_id, ts_utc, kind, payload_json)`.
Single-writer; JSON logs remain diagnostic views only.

### S6. Selector input (manager owns `coordination/selector.py`)

Input per cycle: list of `StrategyOutcome` (accepted intents + reject reasons),
account/position view, risk state. Output: at most ONE admitted intent (global
one-position rule incl. in-flight) or no-trade with per-opportunity reasons.
Frozen heuristic scoring labeled as such; no invented win probabilities.

## Cross-worker dependencies

- Q-005 needs S2 ExitPolicy type: manager lands `coordination/exits.py` first;
  W1 codes against this spec meanwhile (type will match verbatim).
- Q-005 S5 needs E-007 depth/flow availability verdict: E-007 publishes
  `specs/depth_flow_availability.md` early; manager relays path to W1.
- E-007 needs engine-fee ingestion: V-006 publishes `note_fill`/`note_funding`
  signatures early (append-only to `accounting/ledger.py`); manager relays.
- V-006 verifies against E-007/Q-005 outputs post-integration; files V-006
  after manager announces integrated main SHA (V-005 continuation items:
  retained-capture + cap-2h numeric check ride along in V-006).
