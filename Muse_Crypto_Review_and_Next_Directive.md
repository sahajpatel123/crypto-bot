# CEO review and next implementation directive — crypto-bot
Review baseline: 871d1043c70aa0328e7be01053d8afd71b2cafe0  
Repository: https://github.com/sahajpatel123/crypto-bot  
Review date: 11 October 2026 UTC / 12 October 2026 Asia/Kolkata

This is the next instruction for the main Muse CLI manager. The owner communicates with the manager; the manager coordinates the same three workers. Read this entire file, independently reproduce the findings, and execute the authorized development work. Preserve the existing project and its history.

## 1. Review verdict and observed evidence

The initial implementation is a useful foundation. It is not a verified scalping system, and M1 needs integration corrections before acceptance as the specified end-to-end slice. No strategy has demonstrated an economic edge or the owner's 2–3% daily net-account target.

The external CEO review retrieved all 110 tracked files at the baseline commit and checked their Git blob hashes. It independently ran the existing test suite: **167 passed in 1.22 seconds** using Python 3.12 and pytest 9.1.1. It also ran the M1 demo successfully and reproduced its one synthetic fill, one rejected intent and timeout scenario. These are functional checks, not evidence of profitability. The owner’s Mac, worker processes, private local logs and exchange account were not inspected.

The extra adversarial probes below passed through public module interfaces, with state inspected to explain the result. They expose failures that the existing suite does not cover.

| Finding | Observed result | Consequence and required correction |
|---|---|---|
| F-CEO-01: partial-close accounting | Buy 10 at 10, sell 4 at 11, sell 6 at 12, zero fees: equity gain is 16, but net_realised() reports 76. | The first partial exit resets the remaining position’s entry basis to zero. Keep that basis until flat; handle reductions and reversals correctly. False realized profit can corrupt profit protection. |
| F-CEO-02: partial-fill exposure | A 50% entry fill cannot attach protective siblings. After entry expiry, execution releases its reservation, risk reports no open position, and approves another entry although the filled exposure remains. | Track every fill delta, protect/reduce the filled quantity, cancel only the unfilled remainder, and keep risk occupied until reconciled flat. |
| F-CEO-03: timeout is treated as proof of no exposure | Risk approves a new intent after the prior reservation’s TTL expires, without venue/order reconciliation. | Intent expiry stops further submission; it cannot establish that an ambiguous or resting order has no exposure. Retain an unresolved-exposure block until reconciliation proves a safe outcome. |
| F-CEO-04: entry-band sizing | On synthetic equity 1,000, entry band 100–110, stop 99 and costs 1/1/1/0 bps, budget is 2.5. A permitted fill at 110 produces modeled stop loss plus stressed costs of approximately 4.568. | Sizing uses the band midpoint. Bound loss at the adverse permitted price for each side; round quantity down and recheck costs, notional, venue filters and margin. The wide band is an adversarial example, not a claim about S1’s usual band. |
| F-CEO-05: false success status | Injected pytest and M1 failures both returned exit 1, but generate_evidence.main() returned 0. | The tool is a report generator with unconditional success, not a working evidence gate. Required failed checks must make the gate fail. Keep diagnostics and distinguish optional checks. |
| F-CEO-06: external flows trigger targets | Deposit 30 into a synthetic 1,000 account: zero realized trading profit, but SliceRisk rejects the next trade as daily-target reached. | Wire flow-adjusted daily equity and global capital references into the runtime. A helper tested in isolation does not establish integration correctness. |
| F-CEO-07: nonfinite risk values | ForecastCost(fee_bps=NaN, ...) is accepted, and RiskPolicy returns Approved with NaN notional and quantity. | Reject nonfinite costs/prices/account values, invalid enums, nonpositive size/reference values, bad configuration and invalid timestamps before persistence or approval. |
| F-CEO-08: incomplete M1 integration | tools/m1_vertical_slice.py generates a fixture and uses its own inline FakeVenue. It does not execute through execution.OrderManager, market-data discovery/replayer, protective exits or a completed ledger/report round trip. | Replace the inline execution path with the shared components. Produce closed-trade accounting, fees, exposure reconciliation and restart evidence. Clearly distinguish synthetic metadata/recordings from observed ones. |
| F-CEO-09: stale coordination state | coord/tasks.json accepts E-004; coord/outbox/E-004.json records completion at 17:55:06Z. coord/workers.json still says awaiting-go-ahead, and the handoff repeats that stale status. README still describes risk stubs and 87 tests. | Repair current state from accepted task/outbox evidence and actual worker contact. Do not redispatch completed E-004. Keep current status separate from historical logs. |
| F-CEO-10: data and research work stalled | The tracked observed dataset contains a discovery summary and one 60-row one-minute kline recording. The latest commit adds five evidence-log lines for two premiumIndex samples. EXP-001/002 remain plans with zero recorded trials. | Endpoint connectivity samples do not replace continuous event capture, strategy execution, or completed experiments. Change the work loop and deliver those capabilities. |

Further design gaps to close while integrating: live-symbol filters are discovered but absent from the sizing interface, which uses a global minimum notional; risk halts/profit-floor updates are only evaluated on an incoming intent; the ledger has no durable fill/funding replay; the fake venue instantly fills LIMIT orders at their submitted price. This fake is useful for state-machine fault tests, but it must not become a profitability fill model.

These findings do not imply that the original 167 tests failed or that every component is unusable. They define additional acceptance cases that must be fixed.

Milestone disposition:
- M0: coordination artifacts and initial assignments exist; repair operational state and recurring worker-start stalls.
- M1: synthetic component demonstration reproduced; full required integration is pending.
- M2: public connectivity and small recorded samples exist; sustained capture and timing aggregation are pending.
- M3 and later: no strategy validation accepted. Keep promotion NONE until the relevant research/paper gates are earned.

## 2. Mandate, authorization and working rules

Continue implementation, local setup, public data collection, reproducible research, tests and normal project-scoped commits. The existing three workers are authorized to execute manager-assigned tasks within that scope without asking the owner to approve each routine task. Do not claim a worker has started merely because an inbox file exists. Use actual verified transport/activation, obtain an acknowledgment and observe worker-produced progress.

If an independently enforced CLI permission prevents a worker from starting, identify the exact blocking action and permission source immediately; use a permitted alternative or report the smallest one-time owner action. Do not bypass enforced permissions. Do not spend hundreds of manager turns checking an unchanged idle worker. The manager continues executable integration/research work while other tasks are blocked.

Stop the turn-by-turn endpoint-snapshot/test/commit loop. Commit logical changes or accepted evidence batches. Run focused tests after changes, the relevant regression suite on integration, and the complete suite at milestone boundaries or when a new failure warrants it. Repeatedly running unchanged tests is not a milestone.

Use separate worktrees and exact file ownership; shared coordination stays at the canonical manager checkout. Workers may edit only their assigned completion files in coord/outbox. Manager alone integrates shared contracts and publishes the final status. Preserve local work; inspect dirty state before branching or integrating, and never discard unrelated changes.

Keep the baseline risk settings as simulation candidates: 0.25% planned equity risk including stressed execution costs, 3x cap, one global position including unresolved/in-flight orders, 1% daily loss circuit, upward-only global 70% realized-gain protection after 1% activation, and new-entry pause at 2% flow-adjusted daily net-liquidation gain. These are testable policies, not guarantees. Holding preference remains 30 seconds–5 minutes, with earlier protective exits permitted.

Capital remains ₹10,000 excluding operating costs; USDT is the accounting currency. Use a clearly labeled synthetic USDT balance for engineering checks. Any INR conversion is a dated display/proposal, not an invented current exchange rate. The owner’s 2–3% whole-account daily goal remains a research objective, never a daily trade quota or forced optimization target.

No real exchange order placement, account-mode changes, transfers, withdrawals, paid services or credentials are needed for this directive. Live deployment requires the later concrete pilot decision.

## 3. First work packet — correctness and integrated M1

Dispatch these three tasks immediately. Allow public collector development and synthetic diagnostic research to progress in parallel, but do not publish trusted P&L or advance the execution acceptance gate before accounting/exposure fixes pass.

### Worker 3 — V-004: ledger and risk corrections
Own: src/cryptobot/risk/, src/cryptobot/accounting/, tests/acceptance/, tests/fixtures/, specs/acceptance*, coord/outbox/V-004.json.

Reproduce and correct F-CEO-01, 03, 04, 06 and 07. Coordinate the partial-fill risk contract with Worker 2 through the manager. Requirements:
- Partial reduction preserves the entry basis for remaining quantity; full close and reversal compute the correct realized P&L for both long and short. Include fees and signed funding cash flows; external flows never become trading P&L.
- Fill accounting uses durable unique execution/event identities, including partial-fill increments. Replay/restart cannot double-charge fees or lose basis. Preserve useful existing APIs where possible.
- Runtime snapshots contain the required as-of time and flow references. Daily marked-equity loss and daily net-liquidation target use their correct adjusted denominators; global profit protection cannot be replenished by a deposit or tripped just by a withdrawal.
- First nonzero fill counts as exposure. Entry cancellation/expiry never proves the remaining position is flat. Expired unresolved reservations do not silently disappear. Reconciliation decides when the risk block can be lifted.
- Planned loss is bounded at the adverse allowed fill price, including stressed costs and conservative rounding. Use per-instrument filters and available margin inputs; unknown/stale metadata blocks submission. Never round up to meet a minimum and exceed the loss budget.
- Health/daily-loss/profit-floor monitoring runs even without a new strategy intent. Latch required daily state and drive execution exposure reduction through the integrated runtime.
- Validate all money/price/quantity/cost/configuration values and timezone-aware times; reject future evidence outside a documented clock-skew allowance and expired-at-boundary intents.
- Migration of persisted state is explicit and tested. Maintain the modular single-process scope; do not build distributed locking to solve an unrelated problem.

Deliver focused failure-before/fix-after regressions and a concise invariant report. Worker 1 independently checks this work.

### Worker 2 — E-005: partial fills, protection and recovery
Own: src/cryptobot/execution/, relevant tests/unit/test_execution_*, coord/outbox/E-005.json.

Reproduce and correct F-CEO-02 and the execution side of F-CEO-03. Requirements:
- Propagate every new fill delta to accounting/risk; manage actual exposure quantity independently of original requested quantity and order terminal state.
- Protect filled exposure promptly, with a documented bounded response if stop submission fails. Partial entry cancellation leaves a position to manage.
- Reconcile cancellation and ambiguous submission outcomes before declaring expiry/release/flat. A late fill must still be booked and protected.
- Protective exits reduce existing exposure. Stop/target races, retries or delayed sibling cancellation cannot create a reverse position. Simulate those cases; do not assume atomic brackets.
- Persist submission intent/client identity before an external side effect, and design idempotent recovery across every checkpoint. A log append alone does not give exactly-once cross-component callbacks.
- Scope orphan recovery to verifiably bot-owned client identities and positions; unrelated account activity must never be cancelled or changed. The current all-orders fake sweep is not a safe general venue policy.
- Recovery rebuilds the ledger, outstanding entry reservations, partial positions, protection state and halt state consistently.

Update the fake venue to model the required fault cases. Retain explicit “fault simulator” labels. Conservative market/limit fill economics belong to the research simulator, with a separate clearly documented purpose.

### Worker 1 — Q-003: independent reproduction and executable experiments
Own initially: tests/ceo_review/, a new specs/acceptance-ceo-review.md, coord/outbox/Q-003.json. Own subsequent research work: existing quant-owned strategies/features/research/specs/strategies/ and relevant strategies tests.

Create independent black-box regression cases from Section 1, including long/short reductions, partial-fill-then-expiry, unresolved timeout, deposit/withdrawal target distortion, worst-price sizing and NaN rejection. Run against the reported baseline and against manager-integrated fixes. Record the correct expected business result; do not merely copy an implementation’s current output as the assertion.

Then implement a real, resumable command for the already preregistered EXP-001 and EXP-002 descriptive runs. Derive the expected trial manifest from each experiment’s frozen arms, scenarios, seeds and split definition. Execute that manifest, persist successes and failures, include fixture hashes/configuration/version/seed/split boundaries, and reconcile planned versus completed trial counts. Zero signals is a valid executed result; an empty log is not an execution. These synthetic experiments test signal mechanics and cannot promote a strategy or establish profitability.

Audit the split procedure: indicators may warm up causally, but no training outcome crosses into a scored validation window. Embargo/purging for future trade-return evaluation must cover the actual overlapping label/holding horizons, not an arbitrary percentage assumed to be sufficient.

### Manager — MG-001: shared integration and trustworthy evidence
Own: shared contracts, coordination/coordinator, tools/m1_vertical_slice.py, tools/generate_evidence.py, top-level project configuration/docs and reports.

Version any genuinely changed risk/execution interfaces and publish them before conflicting worker edits. Integrate V-004/E-005 and obtain Q-003’s independent reproduction.

Fix F-CEO-05 and test that a failing required check yields nonzero status while retaining its diagnostics. Build a machine-readable evidence result with baseline/head SHA, commands, exit codes and paths. Run the full suite once after the integrated change; distinguish local test reproduction from GitHub CI.

Replace M1’s inline venue with the shared execution manager and fake venue. Route explicit metadata and a labeled recording through the real replay input boundary; use the same virtual clock across strategies, execution, risk and accounting. Synthetic and observed runs stay separate.

Complete a position lifecycle: entry, partial-fill case, protective exit/time exit, cancelled sibling, booked fees, flat reconciliation and a closed-trade report. Include at least one rejected opportunity and crash/restart while exposure is open. Report actual synthetic realized/unrealized/net-liquidation values and prove that balances/fills/reservations agree. Do not shift future prices into the signal window or fill at the same bar’s known close before the signal was available.

Repair README links/status, worker current-task/status fields, task timestamps and the E-004 inconsistency. Historical records remain intact. No need to repeat or re-open completed E-004.

## 4. Second work packet — M2 continuous public data and usable research

After E-005’s focused acceptance, Worker 2 proceeds to E-006; the manager integrates continuously while Worker 1 runs its diagnostics and Worker 3 verifies data/runtime invariants.

### E-006: sustained capture, replay and latency report

Build a persistent public-data collector for trades, BBO/depth, mark price and relevant funding context. Discover the full supported USDT perpetual universe dynamically, then select a small configured concurrent capture set using explicit feasibility/liquidity criteria. A small initial capture set is an engineering scope, not a permanent coin whitelist.

Use currently documented Binance WebSocket routes and per-stream mapping. Official documentation checked for this review uses routed /public, /market and /private surfaces; do not assume old generic fstream URLs carry every channel. Follow the USD-M snapshot/diff-depth sequence protocol and resynchronize after sequence discontinuity. Recheck the official docs at implementation time.

Write raw payloads plus normalized events, exchange timestamps, local wall-clock receipt and monotonic processing timestamps, IDs/sequences, metadata snapshot/hash, input/source labels and configuration. Preserve the fields needed for real trade-flow features. Do not fabricate buy_frac or spread from a one-minute candle.

Build causal closed one-second bars from trade events for the existing S1/S2 interface. Define timestamp meaning, lateness/watermark policy, missing intervals and data-quality transitions. Never relabel one-minute bars as one-second observations, nor carry final OHLC values backward into an unfinished bar.

Start a bounded 30-minute engineering capture, then extend to a two-hour operational check if healthy. Those durations are smoke/operational gates only, not statistical evidence of alpha. Include one controlled disconnect/reconnect and book resync, separately marking natural gaps and injected faults. A gap invalidates affected book features until synchronization completes; retain damaged intervals with their labels.

Report event counts, start/end times, symbol/channel coverage, disconnects, duplicate/out-of-order/gap counts, missing durations, spread and depth summaries, and timing distributions. Distinguish:
- REST round-trip time;
- exchange-event-to-local-receipt age, with clock offset/uncertainty;
- local receipt-to-feature/decision duration measured by monotonic clock;
- execution/ack latency, which cannot be measured from a public-only collector.

For each percentile report p50/p95/p99 with sample size, channel, time window and metric definition. Never interpret the latency of a price snapshot as order execution latency.

Run collectors as supervised local processes with PID/run ID, log path, health checks, bounded storage, clean stop and restart behavior. While time passes, the agents implement/review other tasks. Report “capture running” when that is the actual state; do not fill waiting time with repetitive agent turns.

Keep bulk recordings outside the normal Git history. Commit small fixtures, manifests/checksums, reports and runnable capture/replay commands. Document retained local dataset paths and retention rules.

Nautilus remains unresolved, not verified. Inspect existing cached download progress and compatible interpreter requirements; make one bounded, resumable installation/import/adapter smoke attempt without restarting a large download repeatedly. If blocked, preserve the cache, report the specific blocker, and continue public capture/research. Do not treat slow transfer as upstream incompatibility or invent a successful production-engine adoption.

### Q-004 / manager: chronological evaluation path

Implement an event-driven simulator through the corrected accounting/risk/execution boundary, with realistic spread, fees, latency, partial fills, and explicit cost assumptions. A fault simulator that instantly fills every LIMIT at its own submitted price is prohibited for economic evaluation.

For initial comparisons, conservative taker execution is preferable to an unsupported maker-fill claim. Passive fills need queue/available-liquidity assumptions and adverse-selection treatment; a touched price alone is not a fill. Use actual modeled fill prices without charging the same spread/slippage twice. Funding is a signed cash flow at its applicable event, not automatically a proportional hourly fee.

Register the observed-data evaluation before examining validation outcomes: data as-of selection, candidate variants, execution model, chronological train/validation/final holdout, horizon-aware purging, costs and stress scenarios, and admission rules. Keep synthetic diagnostics, observed engineering replay and economic research in separate reports.

First run an observed replay smoke test on clean available data. If coverage is insufficient, explicitly keep it as a smoke test and start the longer collection/backfill work. One-minute OHLC cannot validate 30-second microstructure execution, and current order-book snapshots cannot reconstruct historical depth.

Report net P&L, per-trade expectancy, turnover/cost breakdown, equity/drawdown, holding distribution, rejected orders/intents, exposure and cost-model sensitivities. All returns use whole-account equity with flows partitioned. Show all-calendar-day results separately from trading-active days; include no-trade days. Do not claim daily 2–3% feasibility from a short sample, synthetic profitable seeds or isolated selected days.

## 5. Remaining strategies and selector

The five candidates remain S1 breakout momentum, S2 trend-pullback continuation, S3 range/VWAP mean reversion, S4 failed-breakout reclaim reversal, S5 order-flow continuation. S5 needs a complete independent entry/exit specification; the present short “confirm S1” draft is insufficient for that requirement.

After an executable S1/S2 research path exists, Worker 1 implements S3 and S4 with exact causal long/short rules, no-trade conditions, invalidation, exit/holding limits and costs. Implement S5 only when its required synchronized data is actually available. Keep it explicitly unavailable otherwise, without substituting synthetic flow and calling it validated.

The manager implements/test-drives the selector: data quality, regime eligibility, net cost/expectancy evidence, deduplication, conflicting signals, deterministic ownership and one global exposure. Current first-intent selection is a minimal coordinator, not a validated selector.

Compare individual strategies, the selector and profit-protection policies against preregistered baselines on the same chronological data. Changing risk/selection settings based on results consumes a recorded research trial. Never force a strategy to pass; no-trade and negative findings are valid outcomes.

## 6. Acceptance and handoff

Finish correctness and the integrated M1 first, then deliver the first continuous-capture and executed-research evidence. Do not call later calendar-time gates complete early, but keep advancing independent runnable work.

Every finding from Section 1 needs one of: reproduced and fixed with regression evidence; independently disproved with exact output; or still open with owner and a concrete blocker. Self-authored risk tests are not the sole acceptance evidence.

Return one compact current-state handoff containing:
1. Starting baseline and final integrated/pushed SHA; dirty/unpushed work if any.
2. A finding table F-CEO-01 through F-CEO-10 with fix commits, regression commands, outputs and unresolved limitations.
3. Current worker task/state and actual acknowledgments; no stale awaiting-go-ahead labels for accepted work.
4. Integrated M1 report, full-suite result and demonstration that the evidence gate fails on injected check failure.
5. Collector command, run ID/PID, dataset manifest/hash, current duration and latency/data-quality report.
6. EXP-001/002 expected and completed trial counts, trial-log paths/hashes and promotion NONE.
7. Observed evaluation status and honest data sufficiency; statistical validation and forward-paper duration remain separately stated.
8. The next measurable task, with no profitability promise.

The external review made no changes to the GitHub repository. Your manager and workers own the implementation of this directive.

## 7. Reproduction commands for the reviewed failures

Run from the repository root with its Python environment. This probe is diagnostic; convert each case into an independent regression assertion and test corrected behavior. It does not use credentials or network access.

```python
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import importlib.util, contextlib, io, sys, json

from cryptobot.accounting import Ledger
from cryptobot.coordination import Intent, Side, ForecastCost, DataQuality
from cryptobot.risk import RiskPolicy, AccountSnapshot, SliceRisk
from cryptobot.risk.sizing import plan_size
from cryptobot.risk.types import RiskConfig
from cryptobot.execution import FakeVenue, OrderManager

clock = [datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)]
cost = ForecastCost(1, 1, 1, 0)
account = AccountSnapshot(1000, 1000, 1000, 0, False)

def intent(low=100, high=100, stop=99, forecast=None):
    return Intent(
        "AUDIT", "1", "BTCUSDT", Side.LONG, clock[0],
        low, high, clock[0] + timedelta(seconds=5), stop,
        "stop-or-time", 30, forecast if forecast is not None else cost,
        "audit", DataQuality.CLEAN,
    )

ledger = Ledger(1000)
ledger.record_fill("BUY", 10, 10, 0, clock[0])
ledger.record_fill("SELL", 4, 11, 0, clock[0])
ledger.record_fill("SELL", 6, 12, 0, clock[0])
print("F-CEO-01 expected 16; actual:", ledger.net_realised(),
      "marked gain:", ledger.marked_equity(12) - 1000)

plan = plan_size(intent(100, 110, 99), 1000, RiskConfig())
loss = plan.qty * 11 + plan.qty * 110 * 3 / 10000 * 1.5
print("F-CEO-04 budget:", plan.reserved_risk, "adverse-price loss:", loss)

with TemporaryDirectory() as td:
    policy = RiskPolicy(state_path=Path(td)/"risk.json",
                        now_utc=lambda: clock[0])
    policy.reconcile_day(1000)
    approval = policy.evaluate(intent(), account)
    venue = FakeVenue()
    venue.fail_next_submit("partial", fractions=(0.5, 0.5))
    manager = OrderManager(
        venue, log_path=Path(td)/"orders.jsonl",
        now_utc=lambda: clock[0], outcome_sink=policy,
    )
    entry = manager.submit_entry(
        "BTCUSDT", "LONG", approval.qty, 100,
        expire_at_utc=clock[0] + timedelta(seconds=5),
        reservation_id=approval.reservation_id,
    )
    try:
        manager.attach_siblings(entry, stop_price=99, target_price=101)
        print("F-CEO-02 partial protection attached")
    except ValueError as exc:
        print("F-CEO-02 partial protection:", str(exc))
    clock[0] += timedelta(seconds=6)
    print("F-CEO-02 expiry events:", manager.poll())
    print("F-CEO-02 next decision:", policy.evaluate(intent(), account),
          "remaining venue fills:", venue.fills)

with TemporaryDirectory() as td:
    policy = RiskPolicy(state_path=Path(td)/"risk.json",
                        now_utc=lambda: clock[0])
    policy.reconcile_day(1000)
    first = policy.evaluate(intent(), account)
    clock[0] += timedelta(seconds=6)
    second = policy.evaluate(intent(), account)
    print("F-CEO-03 without reconciliation:", first, second)

with TemporaryDirectory() as td:
    gate = SliceRisk(state_path=Path(td)/"risk.json",
                     day_start_equity=1000, now_utc=lambda: clock[0])
    gate.ledger.record_flow(30, "deposit", clock[0])
    print("F-CEO-06 zero trading P&L:", gate.ledger.net_realised(),
          "decision:", gate.evaluate(intent(), 100))

with TemporaryDirectory() as td:
    policy = RiskPolicy(state_path=Path(td)/"risk.json",
                        now_utc=lambda: clock[0])
    policy.reconcile_day(1000)
    nonfinite = ForecastCost(float("nan"), 1, 1, 0)
    print("F-CEO-07:", policy.evaluate(intent(forecast=nonfinite), account))

spec = importlib.util.spec_from_file_location(
    "evidence_probe", "tools/generate_evidence.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.run = lambda cmd, cwd: (1, "INJECTED CHECK FAILURE")
old_argv = sys.argv
sys.argv = ["generate_evidence.py"]
try:
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        code = module.main()
    print("F-CEO-05 all checks injected failed; exit:", code)
finally:
    sys.argv = old_argv
```

Baseline output highlights: realized=76 versus equity gain=16; adverse-price risk approximately 4.568 versus budget=2.5; partial protection raises “siblings attach only to a FILLED entry”; expiry emits callback:release and the next entry is Approved; unresolved TTL permits another Approved; deposit triggers pause:daily-target with realized=0; NaN yields Approved; injected failed checks yield gate exit=0.

## 8. Primary references checked

Repository code and state above are pinned to the reviewed commit:
- https://github.com/sahajpatel123/crypto-bot/tree/871d1043c70aa0328e7be01053d8afd71b2cafe0
- https://github.com/sahajpatel123/crypto-bot/blob/871d1043c70aa0328e7be01053d8afd71b2cafe0/src/cryptobot/accounting/ledger.py
- https://github.com/sahajpatel123/crypto-bot/blob/871d1043c70aa0328e7be01053d8afd71b2cafe0/src/cryptobot/execution/order_manager.py
- https://github.com/sahajpatel123/crypto-bot/blob/871d1043c70aa0328e7be01053d8afd71b2cafe0/tools/generate_evidence.py
- https://github.com/sahajpatel123/crypto-bot/blob/871d1043c70aa0328e7be01053d8afd71b2cafe0/coord/tasks.json

Current Binance documentation for implementation checks:
- https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/Connect
- https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/Important-WebSocket-Change-Notice
- https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/How-to-manage-a-local-order-book-correctly
- https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade

The official trade catalog separates New Order and New Algo Order; TP/SL conditional-order support must be verified for the selected adapter/version. Public capture success does not establish authenticated execution capability.
