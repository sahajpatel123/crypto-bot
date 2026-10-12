# CEO implementation order — autonomous crypto bot v0.1
Repository: https://github.com/sahajpatel123/crypto-bot  
Reviewed baseline: 1a3c0701c78c1fd09f3d3ef0395e02541300b8e0  
Issued: 12 October 2026, Asia/Kolkata

Read this entire order and execute it through the existing manager and three workers. The next deliverable is a running application. Do not stop after specifications, import checks, new unit tests, or another handoff saying the next dispatches are ready.

## 1. Decision and outcome

**Primary language: Python. Runtime framework: pinned NautilusTrader 1.231.0 using its compiled components. No wholesale Rust or C++ rewrite.**

Retain the existing strategy, accounting, risk and data work. Use one Nautilus execution runtime for the application; translate the reviewed protection/recovery policy into that runtime. Keep FakeVenue and its OrderManager path as fault-test/reference infrastructure, not an economic fill engine running alongside Nautilus.

Precision matters: the installed 1.x Python runtime includes Cython and Rust components. Do not call it the fully Rust-native v2 runtime. Current latest documentation covers 2.x APIs that are not interchangeable with 1.x. Use the installed package and version-pinned source as the authority, keep 1.231.0 initially, and do not silently upgrade to a release candidate. The owner’s trial environment already imported this pin on Python 3.14.6; reuse that successful cached installation or an explicitly verified compatible environment. Align project Python requirements and lockfile with the runtime actually used.

Programming language determines implementation performance and ergonomics; it does not create trading intelligence or profitability. Intelligence here means causal features, explicit strategies, empirical calibration, cost-aware selection and reliable feedback.

**Deliver Bot v0.1: real-time public Binance USD-M data plus local paper execution, autonomous session control, all available strategies, position management, risk, persistence and net accounting.** Replay and paper modes use the same strategy/selector/exit/risk logic. Paper is simulated trading against live public data; no Binance testnet or mainnet order submission is included in this order.

The following are NEW acceptance commands to implement, not claims about commands already available:

```sh
uv run --locked cryptobot doctor --config configs/paper.toml
uv run --locked cryptobot run --mode paper --config configs/paper.toml --duration 24h
uv run --locked cryptobot status --run-id <actual-run-id>
uv run --locked cryptobot stop --run-id <actual-run-id> --flatten
uv run --locked cryptobot replay --capture <retained-capture-directory> --config configs/paper.toml
```

The manager returns the actual working commands, environment and run ID. Console scripts must work without a manually injected PYTHONPATH. TOML configuration can use Python’s built-in parser. CLI/status/JSON reports are sufficient; a dashboard is not required.

## 2. Baseline acceptance and factual boundaries

The external CEO review obtained all 169 tracked snapshot files, verified their Git blob hashes, independently ran **340 tests successfully in 19.65 seconds**, and ran the integrated M1 lifecycle with recovery and flat reconciliation. That is real code progress.

The same review identified the next application gap: there is no continuous paper-session application connecting data, strategies, selector, execution, account state and operator controls.

Do not repeat outdated claims:
- The 0.021375 ms median in stream_cap-30min_report.json is collector processing after message receipt: parsing/book/bar update/write buffering. It excludes strategy evaluation, selection, risk and order submission. Rename it collector_processing_latency_ms and measure the actual runtime stages separately.
- The 150 synthetic trials execute signal mechanics and cost-exposure counts. They do not execute trade-return economics or validate profitability.
- The tracked report describes 1,129,445 events. The external review did not access the owner’s full local 1.2 GB capture, so its hashes and cap-2h result require local verification.
- S5_RULING.md was based on an older checkout without flow/depth/bar modules. Those modules now exist. Reassess current end-to-end availability instead of automatically refusing S5 because of the old inventory.
- Nautilus import checks proving enum/class existence do not prove Binance native OCO/bracket submission support.
- README and reports/m1_report.json remain stale at this snapshot. Update current app instructions and link per-run evidence; do not represent historical outputs as current results.

**Focused correctness fix: replay numeric agreement.** tools/replay_stream.py compares only sets of (symbol, window_start_ms, type). A CEO probe rebuilt the committed 400-event fixture, changed one captured close to 123456789.0, and still obtained exit 0 / bar_rebuild_agrees=true. Compare complete canonical bar contents, sequence/order, multiplicity, OHLCV, trades, flow, spread and gap flags. Mutating any relevant value, adding a duplicate, or removing a record must fail. Reconstruct and compare book/feature state where those features drive decisions. Matching hashes of two reads of one input is not proof that derived outputs agree.

## 3. Start three workers and integrate a running slice immediately

The manager retains decision authority and integration ownership. Existing routine implementation, local setup, public collection, tests and project commits are authorized. Do not ask the owner to approve each ordinary task.

Use the verified messaging/activation route; a file on disk is not an acknowledgment. Repair the previous containment_limited/self_hop_limit_reached situation using supported transport or a worker-side task poller with confirmed activation. Do not bypass enforced CLI permissions. If activation is impossible, name the exact required owner action once and keep doing executable manager work; never spend hundreds of turns checking unchanged idle sessions.

Publish shared interfaces and exact ownership first, then dispatch concurrently. Workers use separate worktrees. No agent silently creates a competing execution engine.

### Worker 1 — Q-005/Q-006: strategies and economic research

Own: src/cryptobot/strategies/, features/, research/, specs/strategies/, relevant tests/unit/test_strategies_* and test_research_*, own completion files.

1. Execute EXP-003 and EXP-004: current manifests plan 60 and 40 trials respectively. Preserve failed trials and reconcile totals; promotion remains NONE.
2. Adapt S1–S4 to the common runtime boundary with bounded per-symbol history and typed executable exit policies. Each evaluation returns an intent or explicit reject reason. Strategy expiry/holding duration uses causal availability time rather than an invented earlier decision time.
3. Recheck S5 against current data with Worker 2. Implement a complete independent S5 order-flow continuation baseline once its inputs pass the availability check; it must be more than “confirm S1.” Use real signed trade volume and synchronized book features, explicit long/short entries, invalidation, target/time exits, cost checks and data-quality rejection.
4. Freeze one small initial S5 parameter set before looking at evaluation outcomes. Its values are research candidates, not proven optimal. Missing/unsynced flow or depth makes S5 ineligible with a precise reason; never substitute generated flow.
5. Implement observed event-driven return evaluation through the SAME runtime risk/execution/ledger policy as paper. Chronological splits and embargo must cover the maximum feature/label/entry-expiry/holding horizon. Retain a final untouched holdout; no selecting a winning seed or tuning against final results.
6. Replace descriptive cost-only counts with real closed-trade gross and net returns, including fees/funding and execution effects. Synthetic diagnostics, observed replay economics and forward paper reports remain separate.

Research-paper execution of unvalidated candidates is permitted for measurement, explicitly labeled experimental. It does not promote them to live or establish profitability. Every candidate still passes health, cost, execution and risk controls.

### Worker 2 — E-007: Nautilus runtime, data bridge and execution

Own: src/cryptobot/adapters/, execution runtime modules under execution/, market_data/, relevant execution/market-data/adapter tests, own completion files. Coordinate shared changes through the manager.

1. Promote the pinned dependency from an import-only trial into the application’s reproducible runtime environment. Prove a real BacktestEngine replay and a live-data TradingNode plus SandboxExecutionClient path at the installed 1.x API.
2. Bridge current normalized events, metadata, real trade-flow fields and synchronized depth into the node. Public data must not require private exchange credentials. Keep actual receipt order, source times and quality/sync state.
3. Persist the REST depth snapshots plus diff events/synchronization boundaries required to replay book features. A snapshot hash alone is insufficient to reconstruct S5’s book state.
4. Translate approved intents into engine orders with durable client identity/reservation correlation. Engine fills feed our ledger and risk by unique execution ID. Select one order authority and one authoritative position/account state; reconciliation compares views rather than independently “owning” exposure twice.
5. Reuse the reviewed partial-fill, protective sibling, entry-expiry, time-exit, halt and restart semantics. Protection operates on actual filled exposure; terminal order state never implies flat. Handle close/retry/cancel races without reversing the position.
6. USD-M futures protection uses independent reduce-only conditional exits. Do not assume native futures OCO or bracket submission. Disable simulator-only contingent behavior that would make paper artificially safer than the planned venue.
7. Make paper fills economically meaningful: taker execution first, crossing the current executable side/depth, respecting latency and available liquidity. No unconditional instant fill at the submitted LIMIT price. Maker behavior stays disabled until there is an explicit conservative queue/fill model.
8. The pinned SandboxExecutionClient source constructs LatencyModel(0) and has simulator contingency support enabled by default. Override/extend the VERIFIED pinned APIs to apply a configured nonzero submission/fill delay and realistic contingency semantics. If the adapter cannot do this directly, extend the sandbox execution client within Nautilus rather than silently launching a second engine.
9. Distinguish modeled latency from measured public feed age. Log every simulator assumption. Forecast costs and booked actual modeled-fill costs are separate; do not double-charge spread/slippage already present in fill prices.

Finish a public event → strategy intent → risk → simulated order → fee-bearing fill → protective exit → reconciled flat example through the new application. Use a separately labeled deterministic replay if natural live conditions produce no valid signal; never inject fake trades into a live observed session.

### Worker 3 — V-005 continuation / V-006: independent runtime and risk verification

Own: risk/, accounting/, tests/acceptance/, tests/ceo_review/ for independent runtime regressions, relevant acceptance specs, own completion files.

1. Complete V-005 against the actual retained capture and cap-2h result, including numeric replay agreement and fresh S5 inventory. Record precisely which local files/hashes were independently checked.
2. Make strict instrument metadata enforcement mandatory in run mode. Fresh min/max quantity, quantity step, price tick, notional and relevant order-specific filters must apply to EVERY order; missing or stale required filters block new entries. Current optional empty-filter configuration is not acceptable for the session runtime.
3. Add available/free margin, reserved entry/exit fee buffers and in-flight exposure to sizing. Leverage cap is not a substitute for free-margin accounting. Planned risk bounds use the adverse allowed entry price and rounded executable size.
4. Feed real engine paper commissions/funding events into the ledger; the legacy OrderManager currently records fee=0.0. Do not carry that placeholder into net-return reports. Configure clearly labeled simulation fee rates without claiming they are the owner’s actual account rates.
5. Ensure cash, realized P&L, open P&L, marked equity, net-liquidation estimates, external flows and capital references agree after partial reductions/reversals, funding, restart, midnight and halt.
6. Run risk/health monitoring on a timer, independently of incoming signals or market traffic. A quiet feed, clock stall, stale book or blocked REST call cannot suspend position oversight.
7. Test callback/recovery checkpoint races with idempotent event IDs. A stale callback for a closed position must not clear a newer exposure. Reconcile unresolved exposure before admitting new trades.
8. Independently validate selector rejection cases, strategy-owned exits, all forced risk exits, data interruptions, storage pressure and graceful/forced restart. Test market gaps through stops; planned risk and operational circuit triggers are not guaranteed maximum losses.

### Manager — A-001: application, selector and session control

Own: src/cryptobot/app/ (or equivalent runtime package), cli.py/__main__.py, coordination/selector, shared contracts/configuration/lockfile, lifecycle/integration tests and current app README/report index.

Create the console application and wire the workers’ real components. First deliver a runnable integrated slice on one instrument, then extend the same code to all eligible symbols and available strategies. A first slice must run before work expands into a dashboard or a broader research framework.

Implement:
- Config validation and doctor command: installed versions, mode, data access, metadata/fee profiles, persistent state, disk budget and exact runtime fingerprint.
- Lifecycle states: starting, warming, ready, holding, paused/halted, recovering, stopping. State transitions have reasons and durable IDs.
- Dynamic supported USDT perpetual discovery and eligibility. The initial subscription count is bounded by measured throughput; no permanent six-coin whitelist. Selection considers spread, depth, data quality, volatility, size feasibility and metadata freshness. Leave unsupported/nonlisted coins outside the executable universe.
- Per-symbol causal warmup and bounded rolling features. Do not recompute from an ever-growing full-session history every second.
- Strategy selector: regime eligibility, cost feasibility, quality, deduplication, opposing-signal handling, deterministic ownership and cooldown. The current “first valid intent” coordinator is insufficient.
- Initial selection can use frozen transparent rules and net reward potential; label heuristic scores as such. Do not invent calibrated win probabilities or expected-value estimates from synthetic signal counts. Statistical expectancy ranking requires held-out economic evidence.
- One global position including unresolved/in-flight exposure; no size multiplication when several strategies agree. The position retains its owning exit policy, with global health/risk overrides.
- Separate steady risk/health and position-exit timers. No AI API, model reasoning call, download, blocking snapshot request, full-history scan or raw-log compression in the critical decision/exit path.
- Transactional single-writer local persistence, preferably SQLite WAL, for run IDs, approved intents, execution events, ownership, risk transitions and account/reconciliation checkpoints. Existing JSON logs can remain diagnostic/derived views; crash recovery must have a defined authoritative source.
- Operator status/stop, graceful shutdown with managed paper exposure, reconnect/backoff, stale-input entry block, restart reconciliation, and a local supervised process with heartbeat/PID and bounded restart policy.

No frontend, cloud purchase, distributed microservices or multi-exchange expansion is required for v0.1.

## 4. Planned behavior and economic accountability

Carry the confirmed scope into executable configuration:
- Trading capital goal ₹10,000 excluding subscriptions/server; primary ledger USDT. Any INR display conversion is dated and labeled. Engineer with synthetic USDT balances or a documented paper capital conversion, never an invented live balance.
- Holdings normally 30 seconds–5 minutes; emergency exits can be earlier. Leverage remains capped at 3x in initial simulation and is chosen from risk/margin limits, not automatically raised just because holding time is shorter.
- At most 0.25% planned equity loss per trade including stressed costs; one global position/in-flight reservation.
- Flow-adjusted 1% daily marked-equity loss circuit; new-entry pause at 2% daily net-liquidation gain; persistent upward-only 70% global realized-gain protection after 1% activation. Test these as policies and preserve healthy/reconciled next-day behavior.
- UTC raw events; Asia/Kolkata accounting day; deposits/withdrawals are not trading profit.
- Owner objective: 2–3% whole-account net gain per day after costs. Implement measurement and target-pause behavior, never a guaranteed minimum return, trade-count quota, forced late-day risk increase or promise to recover losses.

No-trade is a normal operational result. Show why each opportunity was rejected and which condition prevented action. Demonstrate autonomous order capability in replay rather than loosening gates to manufacture live-paper activity.

## 5. Practical speed, durability and local resource requirements

Use measured performance, not language folklore:
- The capture report’s p50 event age 74 ms and p99 576 ms are uncorrected for clock offset; they are not exchange execution latency.
- Report collector processing, queue wait, feature/strategy evaluation, selector/risk, local order dispatch and modeled order/fill delay separately. Include per-stage p50/p95/p99, sample count, channel/symbol and timestamp definition.
- Initial internal engineering target: receipt-to-local-order-dispatch p99 below 10 ms on the owner’s hardware under the recorded workload, with critical durable writes included. This is a target to measure, not a guarantee. Also report signal-ready-to-dispatch separately so bar-close/lateness/warmup delays are visible.
- Replay the recorded load at real time and at least twice real time with bounded queues. Quantify scheduling lag, event loss and resource use. Do not quietly drop price/depth events that are needed for execution or S5.
- If a measured hot function misses the budget after bounded history, batching and I/O separation, move that specific function into the compiled/native path. No full rewrite without a measured reason.
- Treat disk/network calls and the collector’s potentially 15-second synchronous REST snapshot as isolated data work; they cannot block the risk/exit loop.
- Paper data currently costs approximately 1.2 GB per 30 minutes with duplicate raw/normalized JSON streams. A 24-hour session needs compression/chunking, a configured storage budget and nonblocking retention policy. Preserve existing research captures; do not delete them automatically.
- Use immutable hashed chunks and bounded writer queues, preserving replay evidence and critical execution journal durability. If capacity is exhausted, stop admitting entries, manage exposure and shut down cleanly with a specific reason.
- Record CPU, RAM, disk, backlog and heartbeat age. The laptop must remain awake/powered/networked for the timed session; report suspended time and actual healthy coverage.

The trader runs as a local application, independently of whether the Muse agents are reasoning or idle. The four agents build/review the bot; they are not its continuously running trade-decision engine.

## 6. Completion gates — executable demonstrations

Proceed sequentially through acceptance; work not dependent on an elapsed-time gate continues in parallel.

**R0: runtime boot**
The locked environment starts the new CLI, loads actual metadata, initializes/reconciles account state and reaches warmup/ready. Prove paper mode cannot instantiate or route orders through a Binance live execution client. No credentials are needed. Missing required metadata/margin/fee configuration blocks readiness with diagnostics.

**R1: complete autonomous replay session**
Run all implemented strategies through the application on labeled replay inputs. Prove automatic entry, modeled fee-bearing fills, partial protection, target/stop/time exits, conflict/dedup rejection, no-trade, profit/loss pauses, IST midnight and restart with exposure. Show opening/closing equity and all costs reconcile. Numeric bar corruption must fail the replay gate.

**R2: one-hour live-feed research paper**
Launch a supervised paper run on dynamic eligible symbols, exercise one controlled interruption, reconcile and recover, and produce status plus an account/session report. Separate injected recovery evidence from untouched observed returns. Zero trades may be valid if there are no admitted opportunities; report signal/reject counts and retain R1’s actual execution demonstration.

**R3: 24-hour paper session**
Once R2 passes, launch the 24-hour session autonomously and return run ID/PID/start time/log/report locations while it is running. Do not claim 24 hours elapsed early. Continue independent evaluation/reliability work, then report actual healthy duration, all calendar/trading-active returns, costs, drawdown, holdings, data gaps and interruptions. A one-day run proves operation only, not profitability.

**R4: economic evidence and pilot package**
Continue chronological observed-data evaluation and longer forward measurement until there is defensible evidence. Report positive or negative expectancy, cost/latency stress, drawdown, uncertainty and data sufficiency. Implement the future Binance live adapter against pinned verified APIs offline, with protective/reconciliation checks, without sending exchange orders. No live enablement occurs from the presence of an API key or a CLI typo. Live capital deployment remains a later concrete pilot decision.

## 7. Next handoff format

Send the owner one compact implementation handoff:
1. Final SHA and actual runnable install/doctor/run/status/stop/replay commands.
2. Runtime framework/version and which execution client actually handled the paper orders.
3. A strategy table S1–S5: implemented, paper enabled/ineligible and reason, economic evidence status.
4. Numeric replay-corruption regression result and independent V-005/V-006 verdict.
5. Complete autonomous session evidence: equity, fees/funding, trades/rejections, positions/reservations and recovery.
6. Per-stage performance and CPU/RAM/disk results; measured versus modeled latency clearly separated.
7. EXP-003/004 completed totals and observed return-evaluation results, including negative findings.
8. R2/R3 actual run IDs, times and current status; open blockers with next executable action.

The handoff must contain a runnable bot or a precisely demonstrated blocker. “Ready for the next dispatch” and a new specification alone do not complete this order.

## 8. Versioned implementation references

Inspect the installed package before copying APIs from any example:
- https://github.com/nautechsystems/nautilus_trader/tree/v1.231.0
- https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/docs/concepts/architecture.md
- https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/docs/integrations/binance.md
- https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/nautilus_trader/adapters/sandbox/config.py
- https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/nautilus_trader/adapters/sandbox/execution.py

The pinned architecture documents Rust components plus the Python/Cython runtime. The pinned sandbox source constructs a zero-latency simulation unless changed. The pinned Binance capability tables list futures OCO as unsupported and brackets denied at submission. Those facts matter more than enum presence.

Current online documentation explains the overall design but warns that v1 and v2 Python APIs are not interchangeable:
- https://nautilustrader.io/docs/latest/getting_started/installation/
- https://nautilustrader.io/docs/latest/concepts/architecture/
- https://nautilustrader.io/docs/latest/integrations/binance/
