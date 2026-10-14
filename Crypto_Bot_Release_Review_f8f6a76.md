# Manager execution instruction — own the assignment through completion

Issued 14 October 2026. This instruction and the review/evidence below form one assignment. It supersedes conflicting process instructions in earlier handoffs; retain the owner's safety and runtime limits. The owner does not need to forward a new prompt for every internal fix.

## 1. Deliverable and authority

You are the integration owner for the existing crypto-bot repository and its five workers. Finish a reproducibly operable trading application, obtain a real demo demonstration when credentials are available, and reach a defensible conclusion about one finite strategy investigation. Do not declare a profitable production bot unless its economic and venue gates actually pass.

You may inspect, implement, refactor within the existing Python/Nautilus architecture, create isolated worktrees/branches, assign/reassign work, repair tests, resolve merge conflicts, and run bounded verification without another CEO instruction. Preserve unrelated changes. Keep production submission disabled during this assignment. This instruction authorizes implementation and the bounded demo drill with owner-installed demo credentials; it does not authorize a new production order or an unapproved purchase.

No language rewrite, new engine, extra workers, dashboard expansion, LLM trading brain, broad new strategy catalog, or longer monitoring session is part of this assignment. Concentrate effort on the demonstrated failures, data suitability and economic evidence.

## 2. Start by reproducing, then work in parallel

Inspect the current Git revision and local changes; record the actual starting SHA. The historical review was against f8f6a76, not necessarily today's working tree. Never reset newer work to that revision. Read the review below and reproduce its applicable cases. If a defect has already been fixed, prove the same behavior at current HEAD and avoid duplicating the fix.

Use one integration branch and the existing coordination mechanism. Allocate ownership as follows:

| Owner | Accountable output | Boundary |
|---|---|---|
| Manager | Working integrated driver, acceptance command, final release decision | Own cross-worker interfaces and integration; resolve conflicts promptly |
| W1 | Session/adapter event ownership, durable booking, recovery, independent halt reasons | Own shared lifecycle changes |
| W2 | Normal-Session demo drill, truthful exits, deployment/operator commands | Consume W1's interface; coordinate any shared-file changes |
| W3 | Historical-data feasibility audit and bounded replay input | Own provenance, timestamps, coverage and dataset manifests |
| W4 | Correct causal diagnostics and one finite research round | Own strategy experiment definitions and economic reporting |
| W5 | Independent adversarial acceptance through actual default command paths | Do not substitute component fixtures for the integrated operator path |

Each task must have an observable acceptance condition and one owner. If a worker does not acknowledge after one retry within five minutes, reassign the task or take it over. Worker absence is not an external blocker. Do not request more agents. Workers can implement independently; the manager controls integration and schedules CPU-heavy runs to avoid contention on the laptop.

## 3. Execution limits and continuity

Every command/job, including descendants and cleanup, must end in less than 30 minutes. Use a 1,500-second total work budget, stop new trading activity early enough for closure, and reserve cleanup time inside that budget. Do not auto-restart a forward-capture process to bypass the prohibition. Do not restart owner-stopped monitoring. A deadline that leaves unknown exposure is an unsuccessful, explicitly exposed termination; it must never be reported flat.

Offline historical replay may use genuine resumable slices. Preserve state, warmup, open orders, pending events and positions across slices; a slice boundary is not permission to reset exposure or improve P&L. Mark truncated/incomplete results explicitly. Do not rescore completed cells merely to select a better outcome.

Maintain a small durable completion board: requirement, owner, current state, acceptance command, evidence path and SHA. At context/session limits, save the exact next action and resume from this board. Do not make a new general plan after each context reset. Run affected tests during implementation; run the complete release suite once on the final integrated revision, repeating only when subsequent changes invalidate it.

## 4. Close engineering acceptance first

The detailed source findings and reproducer below are the starting evidence. Convert the failing behaviors into permanent regression tests; do not simply rerun the diagnostic script after fixes and call its historical expectations a release gate.

Required behavioral outcomes:

1. The default private-stream thread cannot mutate Session/ledger/SQLite state outside its owner. Socket messages and recovery results enter a bounded, supervised handoff. Queue overflow, event-application failure and excessive lag halt new entries without silently discarding evidence.
2. A received fill remains recoverable until durable booking is acknowledged. Transport-level deduplication cannot consume an unbooked execution. Recovery must also find fills from orders that have become terminal. Prove crash boundaries before receipt persistence, before booking and before protection acknowledgement, with no duplicate accounting or entry resubmission.
3. Every admitted fill is booked once and protected through the normal driver. Partial fills resize protection, terminal siblings remain tracked until confirmed, and emergency exits are idempotent and limited to bot-owned exposure. Preserve foreign/manual positions.
4. Halt reasons are independent. A healed user stream may clear its own reason only; it cannot clear daily-loss, booking-error, stale-data or operator-stop reasons.
5. The demo `full` command exits nonzero when any required phase is blocked, failed or incomplete. Failed preflight prevents entry. Include normal entry/protection/exit, private-stream interruption, restart/adoption and authoritative account reconciliation. Use the normal Session and adapters. An explicitly labeled demo-only synthetic intent may exercise mechanics without a profitable strategy; it must not enter economic results or the production path.
6. Unknown outcomes remain unknown until reconciled. Engine, journal, ledger, reservations, venue positions and standard/algo orders must agree before declaring flat. A failed protection/exit leg must invoke the defined exposure-handling path, not merely terminate with a success-looking report.
7. Reproduce deadline containment on the supported operator/deployment environment. A platform-dependent failure must be fixed or that environment must refuse unsupported execution. Do not weaken the failing assertion or claim untested portability.

W5 must exercise the actual default thread, real RunStore and normal Session loop—not a stub store, synchronous polling substitute, swallowed exception or direct ledger call. Include fast offline fault injection for all failure cases. Preserve the existing stricter risk limits, one global pending/open/unresolved exposure, and the 30–300-second strategy scope. Do not raise leverage, widen risk or relax fees to obtain activity.

Once offline acceptance passes, run the exact documented demo command with owner-held demo credentials if present. Never print keys. A credentialed demonstration may be bounded to 20 minutes of activity plus closure inside the 25-minute job budget. No keys means demo validation remains BLOCKED; finish every credential-independent task first. A short drill proves those mechanics only, not long-term uptime or profitability.

## 5. Correct the evaluator and settle the data question

W4 repairs causality before scoring another economic hypothesis. Separate evidence timestamp, availability/receipt timestamp, evaluation time, submission and arrival. No execution may precede the decision or use future book information. Stops and targets trigger actions; triggering prints are not automatically executable exit prices. Apply quote-age, available-size, expiry and capture-coverage rules. Unsupported markout horizons are unscorable. Fees, funding, spread and slippage must be represented once with explicit provenance; missing funding must not silently become zero or an invented universal bound.

Recompute H-R2 once with corrected semantics. Archive superseded figures and account for all original 61 candidates, including any now unscorable. Preserve the development-data designation. A corrected negative or zero result is valid and must not lead to loosening execution realism.

In parallel, W3 audits historical data instead of declaring ten new calendar days mandatory. Check existing legally accessible sources and a small available vendor sample first. The Tardis documentation cited below is a lead, not a verified dataset or purchase instruction. Check quotes/depth/trades, local and exchange time, sequencing, snapshots, channel cadence, gaps, funding settlements and historical instrument filters needed by the chosen candidate. Record precisely which strategy families a dataset supports. Do not require unused channels merely to construct a larger checklist, and do not invent unavailable microstructure data.

If an appropriate source is paid, prepare one concrete choice with exact date/symbol/channel coverage, sample audit, price, license and the smallest adequate purchase. Ask only for that purchase/access decision; do not spend money automatically. If access is unavailable, complete the ingestion interface and sample proof, then state the exact missing input and resume command. Never use synthetic tapes or minute bars as tick-execution profitability evidence.

## 6. One finite economic investigation

Do not repeat old configurations under a new name. Preserve old registry identities and tests; version the new strategy/parameters separately. An old 120-second contract pin is not a prohibition on a correctly versioned 300-second hypothesis within the owner's scope.

Before viewing new outcomes, the manager and W4 must write one research hypothesis and its rejection rule. Choose one economic mechanism and at most four genuinely different, justified configurations, plus CASH and an unchanged baseline. Cap initial development/validation at 12 scored cells. Mechanical reruns are allowed only for a demonstrated implementation/data defect, must preserve provenance, and cannot become hidden tuning. Do not add extra variants after seeing a loss.

Specify signal timing, causally observable eligible regime/symbols, entry, invalidation, 30–300-second time exit, target rationale, liquidity/participation limits and full cost assumptions. The movement forecast must come from market evidence or an explicitly testable hypothesis, not a target moved until it clears a cost gate. Adding filters to a zero-admission control does not constitute a new mechanism.

Use suitable chronological development and validation data; select at most one candidate. Candidate selection and thresholds are frozen before opening the untouched evaluation. Historical unseen data may be used when chronology, embargo/purge and prior-use checks support it. Never relabel used captures as untouched. Preserve the existing minimum 100 closed out-of-sample positions across at least 10 days; sample size alone does not qualify a candidate.

For a selected candidate, report daily net equity returns, average net per closed episode, win rate, profit factor, drawdown, tail losses, turnover, fees/funding/slippage, fill/cancel rates and rejection funnel. Reconcile to engine/ledger balances. Report uncertainty with methods appropriate to dependence between trades, concentration by symbol/day and sensitivity to worse costs/latency. Predeclare the adverse assumptions and acceptable risk before viewing evaluation results. Zero-trade metrics remain undefined, not evidence of safety or profit.

Evaluate both candidate economics and the configured daily-loss/profit-protection policy. No martingale, loss-recovery quota or automatic leverage increase. The 2–3% daily target must be reported against observed account returns; it cannot be manufactured or promised. Retain operational stop/floor policies while acknowledging that market gaps and outages can exceed planned loss budgets.

If no candidate survives development/validation, stop the research round and report NO QUALIFYING STRATEGY. Do not consume holdout data or start a fifth variation without a separately approved research scope. If a selected candidate lacks enough qualifying data, report INSUFFICIENT with the exact missing sample/access. This completes the finite investigation, not the goal of profitable production trading.

## 7. One acceptance artifact and one final handoff

Use the existing release report and evidence location. Build or repair one executable acceptance entry point that produces separate machine-readable statuses for engineering, credentialed demo, economic qualification and production eligibility. Missing mandatory evidence is non-success. Every result identifies the tested code SHA, config hash, dataset identity, command, exit and evidence path. Do not mix incompatible revisions into one green verdict; code edits after acceptance invalidate the affected checks.

The final operator route must cover: locked install, configuration, doctor/preflight, bounded replay/paper/demo execution, status, stop/flatten, resume, reconciliation and report generation. Commands must use stable project paths and pinned dependencies, not a worker's temporary virtual environment. The production driver must remain fully implemented and default-off; avoid leaving a missing implementation disguised as an activation boundary.

The manager's final message must contain:

1. Final integrated SHA and how to install/run from a clean checkout.
2. Each reviewed failure: before result, fixed behavior, independently executed proof.
3. The exact demo outcome and authoritative end-state; BLOCKED if no credentialed execution happened.
4. Corrected economic results and whether a strategy actually qualified; no inferred profit from mechanics tests.
5. One explicit overall decision: production eligible or ineligible, with exact blockers.
6. Only unavoidable external inputs, each with a prepared next command. Do not list routine unimplemented work as an external dependency.

Continue internally through fixes, integration and verification. Do not stop at worker handoffs, a higher test count or a draft plan. Do not ask the owner to send individual workers prompts. Escalate only a genuine external dependency or a required safety boundary, after completing all work that does not depend on it. Send concise progress, but do not require a fresh CEO directive to continue.

Production activation remains a separate explicit owner decision on the accepted revision, with actual account configuration and all gates passed. Do not submit real-capital orders as a shortcut to testing software or discovering an edge.

---

# Supporting review and reproductions — historical baseline

The following review is preserved as evidence. Its observations describe the reviewed revision and must be rechecked against the current implementation. The execution instruction above controls this assignment.


# Release review: what must change before another sign-off

Reviewed on 14 October 2026. Repository: https://github.com/sahajpatel123/crypto-bot

Reviewed HEAD: `f8f6a76bdf2e48d177d228956721661502eb74a6`. Its two commits after the report's `eb63acc` change evidence/report files, not application code.

**Decision: substantial implementation exists, but software-complete is not supported. No strategy qualifies for production. Demo credentials and ten days of capture are not the only remaining dependencies.**

This is a focused review with reproductions, not a replacement architecture or another general development phase. No repository changes were pushed, no credentials used, and no real orders submitted.

## Independently checked

- Materialized 520 repository files and verified their Git blob hashes, including the application source and selected release tests. Bulk capture tapes were unavailable here; their economic results were not independently replayed.
- Ran the four release/checkpoint/stream test files listed below: **29 passed, 1 failed in 23.34 seconds**. The failure is the Linux deadline-descendant test. This is a subset, not a reproduction of the reported 1,285-test suite.
- Ran the accompanying offline probes against the current source, repository venue fixtures, actual Session and actual SQLite RunStore. They finished in about half a second, with no network or credentials. The nonzero result means defects were reproduced.
- Reviewer environment: Linux, Python 3.12.14, NautilusTrader 1.231.0. The claimed release environment is Python 3.14.6. The platform difference matters to the deadline failure; it does not remove the cross-thread ownership defect demonstrated below.

## 1. Default private-stream threading can lose a fill from the Session

**Observed:** the real attachment's default background thread delivered an injected fill through the Session's original bound handler. SQLite raised `ProgrammingError` because the connection was created on the owner thread. The attachment swallowed the exception and kept running.

At observation: adapter-adopted quantity 0.083; durable fill rows 0; ledger position absent; protection submissions 0; stream halt false; engine exit-only false. Re-delivering the same event on the owner thread still produced zero durable fills because adapter deduplication had already consumed it. These are synthetic mechanics observations, not a live-account incident.

Relevant source:
- `src/cryptobot/adapters/user_stream.py`: `_pump`, `poll_once`, `_checkpoint`, `_release_halt`.
- `src/cryptobot/adapters/binance_live.py`: `_note_order_trade`, `_emit`, `_trades_booked`.
- `src/cryptobot/app/session.py`: `_SessionEngineHandler`, `_apply_engine_event`, `_apply_fill`.
- `src/cryptobot/app/store.py`: connection ownership and `record_event`.

**Required closure:** establish one owner for Session, ledger, risk, SQLite, and adapter state transitions. Marshal socket input and recovery results to that owner with bounded queues and explicit failure handling. Preserve a durable/recoverable event until booking is acknowledged; transport deduplication must not destroy an unbooked fill. Booking failures halt new entries and trigger reconciliation while exit/protection handling remains available. A stream reconnect must clear only its own halt reason.

Do not fix this merely by disabling SQLite's thread check: that would leave shared-state races and the premature deduplication problem. The exact design may reuse the existing producer/control facilities; no second trading engine is requested.

**Acceptance:** run the actual default attachment with a real RunStore and normal Session loop. Prove entry fill → durable booking → protection, then duplicate delivery, booking failure, disconnect/recovery, restart with exposure, and independent halt preservation. Test both normal traffic and the failure path through the same entry point used by the operator.

## 2. The published demo command is not an accepted venue drill

**Observed:** `demo_drill.py full` without keys returned **0 / PASS with four BLOCKED phases**. Injecting a failed preflight still invoked the entry phase. The command therefore contradicts the release report's statement that the full no-key invocation returns BLOCKED.

The source also still contains an unwired stream-gap phase; `resume-adopt` discards adopted events and is omitted from `full`; the main drill constructs an adapter directly rather than driving the normal Session; reconcile does not establish complete account-position flatness. These are executable work, not credential dependencies.

**Required closure:** use the normal demo Session/driver. All required phases must run or produce a non-success outcome. Failed/blocked preflight must prevent entry. Include actual stream interruption and restart/adoption with durable booking, verified protection and authoritative account/order reconciliation. Preserve emergency handling for any exposure created before failure. Ensure deadlines cover the entire drill and cleanup; stop entries early enough to close within budget. Demo means demo hosts and demo credentials only.

**Acceptance:** the exact documented `full` command returns BLOCKED without keys, does not reach entry after preflight failure, cannot pass with an omitted drill leg, and only reports flat after venue positions, orders, journal and ledger agree. First test offline, then use owner-held demo credentials locally. Do not request production keys to fix this.

## 3. H-R2's execution timing is not causal

**Observed in committed artifacts:** all **60/60 filled diagnostic rows** have `fill_ts_utc` before their source candidate's `evaluated_now_utc`; median lead is **1.5845 seconds**. The first example fills at 22:04:09 although the candidate is evaluated at 22:04:10.535.

`tools/hr2_diagnostic.py` selects the first quote at/after evidence time, rather than the actual decision/arrival time. A crafted tape also demonstrates both entry and stop exit before the decision exists. Stop/target exits use triggering trade prices directly, rather than modeling executable exit-side quotes and arrival. The diagnostic can carry a final mark forward into unsupported later horizons.

**Required closure:** distinguish evidence time, information availability, evaluation time, submission and venue arrival. Never fill before the decision is available. Reuse the accepted execution semantics; separate a trigger from its executable fill. Bound quote/mark age and capture coverage; mark unavailable horizons unscorable. Compute funding from valid data or label it unknown instead of claiming an unverified universal bound.

Recompute these diagnostics once after correction. Retain the old numbers as superseded. A correction may improve or worsen the figures; it does not establish profitability. The already-known captures remain development data.

## 4. The recent research round did not resolve the economic question

The registry explicitly reuses the old S1/S2 parameters. Its variants only add volume/flow filters. Under the stated subset relationship they cannot admit trades when the control admits none. That is a valid rejection of those configured variants on those captures; it is not evidence that genuinely new entry/exit economics were researched, nor a general disproof of a strategy family.

The 300-second experiment was abandoned to preserve old contract pins. Old experiment identities should stay immutable, but a new versioned hypothesis can have new parameters and corresponding tests. Historical pins are not a reason to repeat an unchanged research question.

**Decision:** freeze broad engine feature development. Repair the execution/evaluation defects above. Then either run one genuinely new, preregistered, economically motivated candidate on suitable data or stop this research round with no candidate. Do not keep renaming old configurations, loosen costs to force trades, or interpret more agents as more market evidence.

For any new candidate, specify before outcomes: signal availability, eligible regime/symbols, 30–300-second exit logic, invalidation, achievable post-cost movement, sizing, participation limits, transaction costs, and a finite attempt budget. Choose data by these requirements. Advance only after useful development and validation results; untouched testing comes after candidate selection. Existing 100-position/10-day minimum screens remain screens, not guarantees or statistically universal proof.

## 5. Ten new calendar days are not the only data route

Tardis's official Binance USD-M documentation lists historical depth updates/snapshots, bookTicker, trades and one-second mark/funding streams, plus exchange/local timestamps. Historical data may therefore be a route to evaluating a frozen candidate without waiting ten new days. This is a feasibility finding, not an endorsement of any uninspected date range or paid package.

Source: https://docs.tardis.dev/historical-data-details/binance-futures

Audit a small sample first: continuity, channel coverage, timestamps, snapshots, funding settlement information, exchange filters, licensing and cost. A vendor label does not prove data suitability. Previously unseen historical data can be reserved for evaluation, but dates must be chosen without looking at outcomes, and development/validation must precede them chronologically with proper purging. Never relabel used captures as untouched.

Keep every execution below the owner's 30-minute limit, including descendants and cleanup. Use a 1,500-second work budget and genuine resumable offline slices. Do not disguise an extended forward-monitoring run as automatic short restarts. Buying data requires a concrete source/coverage/cost choice, not an open spending authorization.

## A working process that ends the forwarding loop

Keep the existing manager and five workers. The manager owns integration and acceptance until one terminal decision; routine implementation choices and bug fixes do not require another CEO prompt.

| Owner | Concrete responsibility |
|---|---|
| Manager | One integration branch, one operator entry point, one release checklist; reassign absent workers. Accept behavior at the actual command/default settings. |
| W1 | Close event ownership, booking acknowledgement, recovery and halt independence. |
| W2 | Complete the normal-Session demo drill and truthful command exits. |
| W3 | Audit suitable historical data and reproducible bounded replay slices; state exact missing access/cost if blocked. |
| W4 | Correct causal diagnostics; own one finite economic investigation and its honest conclusion. |
| W5 | Independently run real command paths with SQLite/default threading, adversarial events and reconciliation. Reproduce the Linux deadline failure on the deployment target before declaring portability. |

First make the demonstrated failures into regression tests. Fix and review those paths. Re-run affected tests while working, then one release suite and actual operator-command acceptance on the integrated revision. Do not spend cycles on per-turn full suites or new narrative handoffs.

Only three kinds of owner input warrant interruption: local demo credentials after the offline drill passes; a specific paid-data decision if needed; or a reviewed production-activation decision after a strategy and venue operation qualify. Never send credentials through chat.

Terminal outcomes must be separate: (1) engineering accepted or failed, (2) demo validated or blocked, (3) economic candidate qualified, rejected or insufficient. If the finite research budget produces no qualifying strategy, archive the research result and leave production off. Do not invent another generic release phase, and do not label this a profitable bot.

The 2–3% daily account target remains an aspiration, not an acceptance test that software can make true. The configured 0.5–1% loss actions likewise cannot guarantee a hard realized-loss ceiling through gaps, slippage or outages. No loss-recovery quota or leverage increase is authorized by this review.

## Reproduce this review

The following selected tests were run from the repository root:

```bash
PYTHONPATH=src:tests python -m pytest -q \
  tests/unit/test_release_checkpoint_a.py \
  tests/acceptance/test_rel_integrated_challenge.py \
  tests/unit/test_user_stream_attach.py \
  tests/unit/test_adapters_user_stream.py
```

Result: 29 passed; `test_rel_deadline_reparent_contained_or_refused` failed because its daemon-survival marker was written. No assertion was weakened. This local failure does not establish identical behavior on the manager's Mac.

Save the Python block below as `release_review_probes.py` outside tracked source. Run from the repository root under the existing budget wrapper:

```bash
PYTHONPATH=src:tests:tests/unit uv run --locked --extra dev python \
  /absolute/path/release_review_probes.py
```

It uses injected transports and repository fixtures. On the reviewed revision it prints the following observations and exits 1. It is a diagnostic reproducer; port the cases into permanent behavioral tests when implementing the fixes.

### Observed result

```json
{
  "reviewed_sha": "f8f6a76bdf2e48d177d228956721661502eb74a6",
  "provenance": "offline synthetic fault probes; not economic evidence",
  "demo_without_credentials": {
    "exit": 0,
    "final": {
      "ts_utc": "2026-10-14T09:37:46.854346+00:00",
      "phase": "full",
      "verdict": "PASS",
      "detail": "fails=0 blocked=4 (BLOCKED phases declared, see evidence)",
      "elapsed_s": 0.1
    },
    "blocked_phases": 4
  },
  "failed_preflight": {
    "exit": 1,
    "phases_executed": [
      "preflight",
      "entry",
      "gap",
      "reconcile"
    ]
  },
  "default_thread_fill": {
    "callback_errors": [
      {
        "type": "ProgrammingError",
        "message": "SQLite objects created in a thread can only be used in that same thread. The object was created in thread id 140173524096832 and this is thread id 140173501605568.",
        "thread": "user-stream"
      }
    ],
    "attachment_errors": 1,
    "durable_fill_rows": 0,
    "ledger_has_position": false,
    "adapter_adopted_qty": 0.083,
    "protection_submissions": 0,
    "attachment_halted": false,
    "engine_exit_only": false,
    "durable_fill_rows_after_same_event_on_owner_thread": 0
  },
  "counterfactual_decision_time": {
    "decision_time": "1970-01-01T00:00:02.500000+00:00",
    "scored": {
      "ref": "crafted",
      "strategy": "S1",
      "side": "LONG",
      "instrument": "BTCUSDT",
      "arrival_latency_ms": 0,
      "entry": "filled",
      "fill_ts_utc": "1970-01-01T00:00:01+00:00",
      "fill_price": 100.0,
      "fill_qty": 0.2,
      "unit_qty": 0.2,
      "exit": "stop",
      "exit_ts_utc": "1970-01-01T00:00:01.500000+00:00",
      "exit_price": 99.0,
      "gross_bps": -100.0,
      "net_bps": -110.0,
      "cost_note": "fees 5bps/leg labeled; spread/slippage 0 added (in touch fills); funding excluded (\u22640.01bp bound)",
      "markouts_bps": {
        "30": -10.0,
        "60": -10.0,
        "120": -10.0,
        "300": -10.0
      }
    }
  },
  "committed_hr2_timing_audit": {
    "diagnostic_rows": 61,
    "filled_rows": 60,
    "fills_before_evaluated_now": 60,
    "median_early_seconds": 1.5845,
    "first_example": {
      "ref": "S1:0.1.0:ETHUSDT:LONG:2026-10-11T22:04:09+00:00",
      "seconds_before_decision": 1.535,
      "fill": "2026-10-11T22:04:09+00:00",
      "decision": "2026-10-11T22:04:10.535000+00:00"
    }
  },
  "interpretation": "Diagnostic observations, not a permanent release gate. Nonzero exit marks reproduced defects. Convert cases to regression tests when fixing."
}
```

### Offline reproducer

```python
"""Offline release review probes. No credentials, sockets, or venue orders.

Run from the reviewed repository with PYTHONPATH=src:tests:tests/unit.
The injected venue uses the repository's own release fixtures.
"""
import contextlib
import copy
import importlib.util
import io
import json
import os
import statistics
from datetime import datetime
from pathlib import Path
import tempfile
import threading
import time
from unittest.mock import patch

ROOT = Path.cwd()
RESULT = {'reviewed_sha': 'f8f6a76bdf2e48d177d228956721661502eb74a6', 'provenance': 'offline synthetic fault probes; not economic evidence'}

def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

def until(predicate, seconds=2.0):
    end = time.monotonic() + seconds
    while not predicate() and time.monotonic() < end:
        time.sleep(0.005)
    assert predicate(), 'bounded wait expired'

with tempfile.TemporaryDirectory(prefix='rc-review-') as td:
    tmp = Path(td)
    demo = module('rc_demo', 'tools/audit/demo_drill.py')
    output = io.StringIO()
    with patch.dict(os.environ, {'BINANCE_DEMO_KEY': '', 'BINANCE_DEMO_SECRET': ''}), patch('urllib.request.urlopen', side_effect=AssertionError('NETWORK FORBIDDEN')), contextlib.redirect_stdout(output):
        code = demo.main(['--dir', str(tmp / 'demo'), 'full'])
    logs = [json.loads(s) for s in (tmp / 'demo/drill_evidence.jsonl').read_text().splitlines()]
    RESULT['demo_without_credentials'] = {'exit': code, 'final': logs[-1], 'blocked_phases': sum(r['verdict'] == 'BLOCKED' for r in logs)}
    phases = []
    def phase(name, rc):
        def call(_):
            phases.append(name)
            return rc
        return call
    with patch.object(demo, 'cmd_preflight', phase('preflight', 1)), patch.object(demo, 'cmd_drill', phase('entry', 0)), patch.object(demo, 'cmd_stream_gap', phase('gap', 0)), patch.object(demo, 'cmd_reconcile', phase('reconcile', 0)), contextlib.redirect_stdout(io.StringIO()):
        code = demo.main(['--dir', str(tmp / 'failed-preflight'), 'full'])
    RESULT['failed_preflight'] = {'exit': code, 'phases_executed': phases}

    import venue_fixtures as venues
    import test_release_checkpoint_a as ca
    from test_user_stream_attach import FakeSocket
    from cryptobot.adapters.user_stream import attach_user_stream
    from cryptobot.coordination.selector import Candidate
    ready, orders = venues.ready_fixture(), venues.orders_fixture()
    engine, transport = venues.make_engine(tmp, [
        ('POST', '/fapi/v1/listenKey', None, ('ok', {'listenKey': 'offline-only'})),
        ('GET', '/fapi/v2/account', None, ('ok', ready['account'])),
        ('GET', '/fapi/v1/openOrders', None, ('ok', [])),
        ('GET', '/fapi/v1/openAlgoOrders', None, ('ok', [])),
    ] + venues.ready_script(ready) + [
        ('POST', '/fapi/v1/order', {'type': 'LIMIT'}, ('ok', orders['orderAck']))])
    session, store = ca._session(tmp, engine, 'thread-probe')
    socket = FakeSocket([])
    caught = []
    original_sink = engine._event_handler
    def sink(event):
        try:
            original_sink(event)
        except Exception as exc:
            caught.append({'type': type(exc).__name__, 'message': str(exc), 'thread': threading.current_thread().name})
            raise
    engine.bind_sink(sink)
    # Production default: start_thread=True. No synchronous manual poll.
    attachment = attach_user_stream(session, engine, lambda _: socket, idle_sleep_s=0.005)
    try:
        until(lambda: not attachment.halted)
        session._maybe_admit([Candidate('S1', ca._intent(session.now_utc()))])
        assert session._position is not None
        qty = ca._submitted_qty(transport)
        cid = session._position['entry_pre_id']
        trade = copy.deepcopy(orders['userStreamTrade'])
        trade['o']['c'] = cid
        trade['o']['l'] = trade['o']['z'] = f'{qty:.3f}'
        trade['o']['L'] = trade['o']['ap'] = '100.50'
        socket.script.append(trade)
        until(lambda: attachment.errors > 0)
        count = store._db.execute("SELECT count(*) FROM execution_events WHERE kind='fill'").fetchone()[0]
        RESULT['default_thread_fill'] = {
            'callback_errors': caught, 'attachment_errors': attachment.errors,
            'durable_fill_rows': count, 'ledger_has_position': session.ledger.has_position(),
            'adapter_adopted_qty': engine._adopted_qty.get(cid),
            'protection_submissions': sum(r[1] == '/fapi/v1/algoOrder' for r in transport.requests),
            'attachment_halted': attachment.halted, 'engine_exit_only': engine._exit_only}
        engine.note_user_event(trade)
        RESULT['default_thread_fill']['durable_fill_rows_after_same_event_on_owner_thread'] = store._db.execute("SELECT count(*) FROM execution_events WHERE kind='fill'").fetchone()[0]
    finally:
        attachment.close()
        store.close()

    hr = module('rc_hr', 'tools/hr2_diagnostic.py')
    row = {'evidence_ref':'crafted', 'strategy':'S1', 'side':'LONG', 'instrument':'BTCUSDT',
           '_ev_ms':1000, 'evidence_ts_utc':hr._iso(1000), 'evaluated_now_utc':hr._iso(2500),
           'entry_expiry_utc':hr._iso(10000), 'entry_low':99.0, 'entry_high':100.2,
           'stop_price':99.0, 'target_price':102.0, 'time_exit_utc':hr._iso(4000)}
    tape = ([(1000,99.9,100.0,1,1), (2500,100.9,101.0,1,1)],
            [(1500,1,99.0,1),(4500,2,101.0,1)], [(1000,100.0)])
    with patch.object(hr, '_load_window', return_value=tape):
        result = hr.evaluate_one(row)
    RESULT['counterfactual_decision_time'] = {'decision_time':row['evaluated_now_utc'], 'scored':result}

cs = {x['evidence_ref']: x for x in json.load(open(ROOT / 'outputs/ready-phasea/candidates.json'))}
ds = json.load(open(ROOT / 'outputs/hr2/diagnostics.json'))
early = []
for d in ds:
    if 'fill_ts_utc' not in d:
        continue
    decision = cs[d['ref']]['evaluated_now_utc']
    gap = (datetime.fromisoformat(decision) - datetime.fromisoformat(d['fill_ts_utc'])).total_seconds()
    if gap > 0:
        early.append({'ref': d['ref'], 'seconds_before_decision': gap, 'fill': d['fill_ts_utc'], 'decision': decision})
RESULT['committed_hr2_timing_audit'] = {
    'diagnostic_rows': len(ds), 'filled_rows': sum('fill_ts_utc' in d for d in ds),
    'fills_before_evaluated_now': len(early),
    'median_early_seconds': statistics.median(x['seconds_before_decision'] for x in early) if early else None,
    'first_example': early[0] if early else None}
RESULT['interpretation'] = 'Diagnostic observations, not a permanent release gate. Nonzero exit marks reproduced defects. Convert cases to regression tests when fixing.'
print(json.dumps(RESULT, indent=2))
raise SystemExit(1 if (RESULT['demo_without_credentials']['exit'] == 0 or caught or early) else 0)
```
