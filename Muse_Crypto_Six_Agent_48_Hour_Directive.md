# Crypto bot: six-session implementation directive and 48-hour review
Issued: 12 October 2026, Asia/Kolkata  
Reviewed baseline: 01487ac9cdf8d3ec3bb16e898c429d7ed3bcb247  
Repository: https://github.com/sahajpatel123/crypto-bot  
Recipient: the Muse engineering manager; the owner communicates only with you.

## 1. Assignment and deadline

The owner has already created SIX Muse CLI sessions: you, the existing three workers, and TWO new idle workers you have not yet onboarded. Discover those existing sessions, verify their identities and communication routes, and assign them the roles below. Do not create duplicates or pretend a dispatch file alone activated a session.

Deliver the strongest evidence-supported release possible by **14 October 2026, 17:46 Asia/Kolkata** (12:16 UTC), approximately 48 hours after the owner's request. Record your actual start and remaining time. This is an engineering deadline and a readiness decision, not a guarantee of profits or an instruction to activate production orders automatically.

The current backtest/performance assignment is **partially complete**. Installation, execution corrections and reporting have improved. However, the real 30-day account benchmark was aborted before results, observed-data trials admitted no trades, and this review found additional correctness defects. Carry unfinished work forward without restarting the project.

Owner-facing outcomes:
1. **Usable market data and correct execution.**
2. **A completed, credible backtest with clear economic results.**
3. **A monitored paper application and a concrete live-readiness decision.**

Keep task codes internal. Report progress in those terms.

### Standing requirements

- Binance USDT perpetuals initially; long and short strategies, intended holdings of 30 seconds to 5 minutes. Protective exits may occur sooner.
- Intended one-time capital: INR 10,000, excluding development/subscription/server costs. Account in USDT; INR is a dated display conversion.
- Owner objective: 2–3% net whole-account return daily. Measure it across ALL complete days, including no-trade days. It is neither a guaranteed minimum nor an order quota.
- Profits remain in the account; planned risk amounts adapt to reconciled equity. Losses never justify increased leverage, looser stops, martingale, averaging down or forced recovery trades.
- Retain Python and locked NautilusTrader 1.231.0. No language rewrite or second economic execution engine.
- No LLM in per-trade decisions. Optional later background news analysis must demonstrate additional value.
- Dynamic supported-symbol discovery remains a requirement. Explicitly use BTCUSDT and ETHUSDT for the first economic benchmark; preserve the other downloaded symbols for later research.
- Retain CEO-selected simulation settings: maximum 0.25% equity planned loss per position including stressed costs, 3x leverage cap, one global position including pending/unresolved exposure, 1% flow-adjusted daily loss halt, 2% daily target pause, and the existing upward-only 70% realized-profit floor after gains reach 1% of original pilot equity. Verify units and persistence. These are simulation defaults, not guaranteed loss limits or owner-selected thresholds.
- The 2% pause makes 3% outcomes dependent on overshoot/existing exposure. Do not silently change it to manufacture target attainment.
- Halts block entries and retain exposure management. They do not guarantee a bound on realized loss.
- The owner has not agreed to a permanent cumulative capital-loss cutoff. Do not claim otherwise. Report cumulative drawdown; any additional policy must be separately documented and tested.
- Public data, local implementation, ordinary tests, scoped commits and preparation of a disabled exchange adapter are authorized. No production-capital orders, transfers, withdrawals or paid purchases through this directive.

## 2. Independent review findings

The reviewer materialized and verified Git blob hashes for all **276 tracked files** at the baseline. A fresh environment installed with uv sync --locked --extra dev; uv run --locked pytest -q passed **664 tests in 51.99 seconds** on the review machine.

This validates installation and the supplied suite, not profitability. Full owner-local captures, benchmark Parquets and /tmp reports were unavailable to the reviewer. Original live sessions and full historical economics were not independently rerun.

### Reproduced defects: fix before economic scoring

| Finding | Reproduced behavior | Required correction and proof |
|---|---|---|
| Future trades affect an earlier modeled quote | research/spread.py:apply_profile uses the entire second's VWAP, then emits a quote at window+100ms. Trades at 1050ms/100 and 1950ms/200 produce a 1100ms quote centered at 150, although only price 100 was known. | Modeled quotes must use information available by their timestamps. Changing future data must not change earlier quotes, decisions, orders or fills. Retain explicit modeled-liquidity/cost labels. |
| Minute close published at minute open | datasets/prepare_benchmark_30d.py:_convert_marks pairs open_time with close. A closing value available at 60999ms is emitted at 1000ms in the probe. | Publish values no earlier than actual availability; preserve open/close/availability times. Version and rebuild affected derived data while retaining raw archives. |
| Deduplication deletes another symbol's event | prepare_split_capture fingerprints channel, timestamp and payload without symbol. Two different symbols with identical quote payloads become one event. | Include venue, symbol, channel and appropriate event identity. Preserve legitimate repeated updates and detect conflicting duplicates. |
| Known trade-ID gap becomes a usable strategy bar | A 1→3 ID jump sets gap_before=True, yet to_s1_bar returns a normal bar. Session also constructs MarketView with CLEAN quality. | Propagate quality through bars, views and admission. Define causal recovery/warmup; adapters must not discard missing-data evidence. |
| WebSocket messages can be stranded behind select() | Two text frames in one socket write: recv_message returns the first, a complete second remains in _buf, but select says the socket is not readable. The outer loop only reads sockets returned by select. | Drain complete application-buffered messages and TLS pending data without awaiting new kernel readability. Preserve fair service across routes. Test coalesced frames, fragmentation, ping/pong, bursts and quiet routes. |

The buffering defect is confirmed and is a candidate contributor to delay. It does **not** establish the cause of the reported venue-wide gaps. Trace actual records before attributing those gaps to Binance or quiet markets.

### Source-inspected integration gaps

1. **Memory and run completion.** Preparation gathers an entire split into lists, globally sorts it, creates a large string dedup set, and joins the entire JSON output. DatasetHandle materializes day tables; run_cell reads a whole capture just to inspect its first record; Session.run_replay loads/sorts the whole capture again. max-events truncates AFTER preparation. The manifest declares about 171.36 million rows across eight symbols. This is not the streaming design requested.
2. **S5 book wiring.** Session's DepthStore receives diffs but the active Session path never installs snapshots. A separate StreamPump implements synchronization; its existence does not prove the normal CLI uses it.
3. **Independent time.** Heartbeats from the same blocking generator do not isolate risk from socket dialing or synchronous REST operations. On None, Session does not explicitly advance the native simulation clock; poll documents that it does not advance time.
4. **Margin and bounded entry.** Session's account snapshot still omits available margin, fee buffers and in-flight commitments, despite an engine accessor. Session still submits MARKET entries despite bounded entry-price sizing. Urgent simulated submission still advertises bypassing modeled delays.
5. **Funding and valuation.** Archive preparation joins earlier realized funding rates to later funding times, substitutes zero for missing terms, and the engine extrapolates eight-hour intervals. Actual settlement rate/time/position exposure needs explicit treatment. Session ledger/risk valuation uses last-trade/BBO feed.mark, which need not match the engine's exchange mark.
6. **Reporting ownership.** Combined-run episodes inherit a run-level strategy or unknown; actual exit reasons are not retained in the episode builder. Full effective configuration and assumptions are not preserved in the small run metadata subset.
7. **Holdout tracking.** A test-COMPLETED file in one directory does not prevent rescoring elsewhere. Track dataset/time-window exposure across experiments. Reproduction is not independent new evidence.
8. **Coverage and integrity.** The supplied manifest has 84 funding-terms-absent gaps and four absent mark-day files. day_has_quotes tests whether a symbol has quotes anywhere, not in the requested window. Preflight should validate selected scope. Source-archive hashes are not hashes of the derived Parquets named in local paths; store and verify both.

Fixes require before/after reproduction on the integrated commit and review by someone other than the implementer.

## 3. Six-session team and ownership

Verify earlier session names rather than assuming they remained unchanged.

| Session | Ownership | First output |
|---|---|---|
| Manager, previously young-polaris | Shared contracts, Session/CLI integration, integration branch, scheduling and owner report | Verified six-session map, exact file ownership and prioritized dependency board |
| Worker 1, previously whisper-redshift | Strategies, research/backtest.py, spread assumptions and strategy cards | Causal spread correction, streaming benchmark orchestration and frozen comparisons |
| Worker 2, previously cloud-vega | Market data, WebSocket transport, dataset conversion/readers and native paper adapter | Correct transport/readers, causal marks/funding data and synchronized live books |
| Worker 3, previously cool-amalthea | Risk, accounting and disabled real-venue adapter contract | Margin/entry/protection invariants, funding reconciliation and venue contract tests |
| New worker 4: Events and market monitoring | Calendar/event-gate module, source adapters and anomaly-policy interface | Tested event restrictions and explicit stale/missing-source behavior |
| New worker 5: Independent verification and operations | Audit probes, report validation, process supervision and performance measurement | Reproduce findings, profile actual bottlenecks and supervise durable runs |

Manager owns shared app/session.py and CLI integration. Workers submit narrow patches/interfaces through the manager; avoid simultaneous edits. Worker 2 owns dataset files, Worker 1 the consumer. Worker 3 owns financial invariants, Worker 5 independently verifies them. Worker 5 may implement reporting corrections; another worker/manager checks that reconciliation.

Onboarding:
- Discover the two already-created idle sessions through supported session tools/registry. Get real acknowledgments and record identity, branch/worktree and role.
- Give each worker this directive, its relevant current contract and a concrete first task.
- Use durable tasks/inbox/outbox plus supported native messaging. Board writes do not prove activation.
- If routing fails, identify the exact failure and smallest owner action needed; continue with available workers. Do not make the owner relay all worker messages.

Working rules:
- Use isolated worktrees/branches from an identified base; manager serializes merges.
- Integrate useful fixes promptly and maintain a runnable checkpoint.
- Run targeted checks during development and the full suite at integration/release checkpoints. Avoid full-suite reruns and commits on every conversational turn.
- Keep concise restart notes: completed evidence, current command/PID/run ID, pending dependencies and next action. Resume after compaction rather than repeating work.
- Verify process persistence within actual platform permissions; a detached command is not proof of continued execution.
- Agent concurrency is separate from heavy computation. Begin with one substantial replay plus one capture/paper process; increase only after resource measurements support it.

## 4. Deadline checkpoints

These are target checkpoints, not prewritten success claims. Missing one triggers diagnosis and a scope decision, never relaxed trading invariants.

| Time from activation | Required result |
|---|---|
| First 1–2 hours | Six-session handshake; preserve old artifacts; reproduce findings; trace actual data path; measure representative throughput; freeze selected BTC/ETH scope and missing inputs |
| By hour 6 | Correct causal transforms/dedup/quality; show bounded preparation/replay on observed data; diagnose live ineligibility; wire books/timers or name precise blockers |
| By hour 12 | Complete an observed-data account run and report; benchmark one full accounting day; report measured memory/throughput and 30-day ETA; start corrected paper observation once execution passes |
| Hours 12–30 | Complete reusable baseline partitions/comparisons; integrate event controls; repair attribution/funding; test disabled venue contract/demo path without production funds |
| Hours 30–42 | Finish validation and frozen final test; run predeclared cost/latency stress; compare event restrictions on development/validation; continue forward observation and independent reconciliation |
| By hour 48 | Deliver executable release, reports and an evidence-based readiness decision for a proposed small pilot; report actual observation time and all remaining blockers |

If measured throughput puts the month beyond the deadline, address the bottleneck early. A small prefix is not a 30-day result. Preserve a labeled partial result, exact coverage, remaining ETA and next action.

Do not abort useful jobs solely to produce a handoff. If owner instruction, resource protection or invalid assumptions require stopping, preserve completed partitions and record why. Previous aborted preparations produced no partial economic output; do not claim nonexistent checkpoints.

## 5. Usable data and a credible backtest

### Diagnose zero-trade results

Zero trades can validate rejection behavior. They do not validate profitability. Widespread missing/unsynchronized inputs cannot be attributed simply to a quiet market.

For each symbol/channel, report:
- Source timestamps and local arrivals; raw versus normalized message counts.
- Missing sequences, duplicates/reordering, reconnects and application-buffer backlog.
- Genuine trade-less seconds versus lost trades; unchanged quotes versus stale quotes.
- Bars rejected for gaps, absent spread, warmup, stale inputs and strategy conditions.
- Actual eligible time/percentage for every strategy.
- Candidates → selection → risk → submission → fill → completed position.

Compare suspicious windows with an independent public endpoint/archive where possible. Determine whether transport, clocks, filtering, bar construction or source coverage causes the failure. A healthy unchanged quote can remain valid under a defined freshness policy; a new quote is not required merely because the second changed. Do not carry stale quotes or invent trades.

Define indicator behavior during genuine empty intervals with elapsed time and explicit volume/missingness semantics. Never erase gaps, relabel modeled data as observed, or relax gates merely to generate activity.

### Stream once and reuse verified inputs

- Use Parquet batches/iterators and bounded merges over ordered partitions.
- Remove split-sized lists, giant JSON strings and unbounded dedup sets at EVERY stage, including replay and reporting.
- Preserve exchange time, receipt/availability time, original order and gap/sync boundaries. Define stable ties; observed arrival replay is not a perfect reordered feed.
- Apply development limits before unbounded loading; label truncated runs.
- Checkpoint partition progress and hashes; normalize once and reuse immutable inputs across arms.
- Bound presentation/chart memory while preserving exact metric aggregates and canonical account records.
- Profile before optimizing. Persist critical approvals/fills/risk transitions; avoid fsync of an unchanged health timestamp for every quote.
- Test any faster path against full event replay for identical decisions, stops, expiry, fills, fees and equity. Never replace execution with favorable bar-close fills.
- Avoid concurrent heavy replays on an unmeasured laptop. Account for agents and recorder resource use.

### Freeze and execute the economic experiment

Retain the 30 full IST-day target (12 September–11 October 2026) only if required coverage is verified. Freeze an availability-based alternative before scoring if necessary. Preserve raw inputs and version causal transformations.

Explicitly select BOTH BTCUSDT and ETHUSDT: the current default chooses only the first manifest symbol. Preserve other data for later work.

Compare the five BASE families separately, the combined single-account bot and cash under the same risk/account policy. S5 remains ineligible where historical synchronized depth is absent; test it on appropriate captures and forward data.

Use 15 development / 7 validation / 8 untouched test days, causal warmup and nonoverlapping scored outcomes. Track all inspection and tuning. Changing directories does not produce an unseen test period. Deterministic reproduction checks computation; it does not add statistical evidence.

After baseline, allow a small preregistered development/validation improvement batch. Record hypothesis, parameters, trial count and selection rule. Five workers must not run unlimited searches against the same final test. Preserve losing trials.

Execution and costs:
- Commission on actual fills, with sourced or explicitly assumed fee tier.
- Observed executable quotes/depth where available; separately labeled causal spread/liquidity assumptions otherwise.
- Verify native quote/trade/depth precedence. A buy must not receive a favorable trade print while ignoring a higher contemporaneous executable ask.
- Include partial fills, queue uncertainty and nonzero entry/exit delays.
- Count spread/slippage embedded in prices once; label additional stress allowances.
- Use historical funding settlement rate/time and actual position exposure. Missing funding is incomplete-cost evidence or an explicit sensitivity assumption, not an unqualified zero.
- Keep economic runs separate from synthetic mechanism fixtures and controlled fault drills.
- Diagnose losses as gross signal loss, costs, entry timing, exits, regime or coverage. Increasing trade count/leverage cannot repair negative expectancy.

## 6. Event awareness and abnormal conditions

Worker 4 implements a small deterministic module while the core corrections proceed.

Initial sources: Federal Reserve FOMC decisions/press conferences, BLS CPI and Employment Situation, BEA Personal Income and Outlays/PCE and GDP, and reliable official exchange maintenance/delisting notices when available.

Persist event ID/source URL, scheduled time/timezone, first-seen time, fetch time, revisions, coverage horizon and expiry. Convert time zones correctly, including US daylight saving; display IST. Cache known schedules. Source outage or incomplete horizon cannot silently mean no events.

Initial **paper hypothesis**, frozen before comparison: block entries from 15 minutes before a designated event until 15 minutes after it. Treat the press conference separately and cover its verified end or an explicit conservative duration if unknown. Cancel unfilled entries, aim to be flat before the event, and keep protection until closure is confirmed. These buffers are not claimed optimal; test only modest preregistered alternatives on development/validation.

Resume only after the event window and a defined period of healthy spread/liquidity/feed conditions. Event restrictions never suppress protective exits.

Unscheduled-shock controls should measure spread widening, book thinning, abrupt returns, latency and exchange errors. Define windows, baselines, thresholds, hysteresis, cooldown and action. Actions include rejecting/canceling entries, reducing allowed risk or halting entries. Panic liquidation on every transient spike is not the default.

Historical tests may only use event/news information available at the time. No paid news feed or LLM purchase now. Propose one later only with a specific coverage/latency gap, cost and validation experiment.

## 7. Risk, recovery and real-venue preparation

Complete the integrated path:
- One budget for pending/open/unresolved exposure; timeout never proves flat.
- Identical venue rounding across risk, submission, fills and protection.
- Available/free margin, fee buffers and commitments actually supplied to admission.
- Ledger/engine reconciliation after funding as well as fills.
- Price-protected entry and expiration; skipped opportunities are valid.
- Protective stop quantity verified against filled exposure, including partials. Failure blocks entries and starts bounded recovery/close attempts, retaining unresolved exposure.
- Independent control/risk timers outside blocking network calls, bounded queues and tested dead-monitor behavior.
- Market channels and idle-time events advance execution/risk clocks causally. Silence must not create fresh executable liquidity.
- Idempotent recovery and exposure matching before entries resume. Midnight must not clear a continuing data/execution fault.
- Explicit exchange-mark, executable-liquidation, mark-age and close-cost semantics shared by risk and reports.

Prepare a Binance real-order adapter behind a default-disabled mode. Use verified pinned adapter capabilities where suitable and narrow wrappers where necessary. Inspect current Binance docs and pinned behavior; do not assume Futures offers native spot-style OCO/brackets.

Verify authentication/time sync, filters, fee tier, margin/leverage/account mode, stable client IDs, private fill/order updates, conditional stops, reduce-only exits, cancellation and reconciliation. Unknown submission outcomes require lookup/reconciliation before any retry can add exposure. Binance documents that some HTTP 503 responses have UNKNOWN execution status.

Start with recorded contract tests and demo/testnet once properly scoped demo credentials are configured locally. No production keys in messages/fixtures/commits. Demo mechanics do not prove real liquidity or profit. Credential setup must not block public-data work; give one precise owner secret-setup request when the code and exact test are ready.

Prepare, without activation, a concrete production pilot package: code/config fingerprints, actual allocated USDT, trading scope, size/leverage/stop rules, reconciliation, monitoring and stop command. The intended INR 10,000 is not a verified exchange balance. Do not transfer funds or change unrelated exposure.

## 8. Reports and sustained operation

Move important current/superseded evidence into durable project-owned directories with labels, hashes, commands and a central index. /tmp alone is not a handoff. Keep bulk data outside git; retain reproducible preparation, verified locations and small fixtures.

Every scored run must automatically produce summary.json, trades.csv, equity.csv, daily_returns.csv, rejections.csv and a standalone report.html.

Report:
- Net account return; reconciled gross P&L, commissions, funding and execution assumptions.
- Marked equity, net-liquidation value, maximum drawdown USDT/% including open losses, and cumulative decline.
- Completed positions, fills/partials, net win rate, profit factor, expectancy with uncertainty, holding times and actual exits.
- Owning strategy per position and contribution in the combined account.
- All full days and fractions reaching 2%/3%; partial/missing-data days labeled.
- Eligible-data time, missing inputs and rejected opportunities with reasons.
- Base/stress economics and separate development/validation/test results.
- Receipt-to-decision/dispatch p50/p95/p99, queue lag, event age with clock limits, resource use, healthy uptime and recovery.
- Evidence class: synthetic mechanism, historical with assumptions, observed capture, forward paper, demo integration or production. Do not blend them.

Do not invent a completed trade by closing open exposure at its entry/last-fill price. Keep open exposure, marked P&L and estimated exit costs separate; label any modeled end-of-data liquidation. Reconcile position/account results and avoid funding double allocation at boundaries.

Worker 5 independently recomputes metrics from canonical records, injects corruption to prove loud failure, and checks full effective config/data provenance.

Start corrected paper observation as soon as the execution gate passes. Use verified local supervision, durable run files, bounded logs and appropriate session-scoped keep-awake. Record PID/run ID, start/deadline, heartbeat and stop/resume commands. Do not claim 24 hours passed after a shorter session.

Keep fault drills separate from untouched observations. Demonstrate crash recovery with simulated exposure in a labeled test: a flat-account kill drill proves restart, not position recovery.

Give concise checkpoint updates: completed output, result, blocker and next action, with detailed evidence linked.

## 9. Release decision and handoff

Decide separately on software, economics and operations. Passing tests or a no-trade session cannot authorize a live pilot.

Required evidence:
- Reproduced defects corrected and independently checked on the integrated release.
- Real eligible data and completed selected benchmark with explicit cost/coverage limits.
- Net-positive candidate results on genuinely unseen data, uncertainty/drawdown understood, no obvious leakage or dependence on a handful of exceptional trades, and adverse execution sensitivity quantified.
- Sufficient independent market episodes and forward observations for the proposed risk. There is no magic trade-count threshold; correlated trades are not independent evidence.
- Verified venue lifecycle, protection, recovery, monitoring and a concrete pilot configuration.

Classify at the deadline:
- **NO-GO:** material correctness/execution defects or tested candidate losses under credible assumptions.
- **INSUFFICIENT EVIDENCE:** functioning implementation but inadequate coverage, observations, execution validation or economic support.
- **READY FOR A BOUNDED PILOT REVIEW:** relevant evidence supports that specific proposal; this is not a return guarantee or automatic activation.

The deadline must not trigger live orders. Prepare the exact reviewable package; production activation requires a separate explicit decision on that package. When a gate fails, continue the most useful research/paper work without forced trades or abandonment.

Final handoff:
1. Integrated commit and verified normal install/run/backtest/report/status/stop commands.
2. Five-worker identity/ownership map and completed/open/blocked work.
3. Before/after finding reproductions and independent checks.
4. Data coverage/fingerprints, actual elapsed runs and current long-run status.
5. Report files and concise economics: net result, drawdown, costs, completed positions, eligible time and strategy comparison.
6. Separate software/economics/operations decisions and next highest-value action.
7. Exact owner dependencies, their purpose and when needed.

## References

Review refers to the fixed commit above; the reviewer did not change GitHub files.

- Binance book synchronization: https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/How-to-manage-a-local-order-book-correctly
- Binance API/demo and unknown execution status: https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info
- Official historical data: https://github.com/binance/binance-public-data
- Federal Reserve calendar: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
- BLS calendar: https://www.bls.gov/schedule/
- BEA schedule: https://www.bea.gov/news/schedule

Use current official documentation during implementation. Handle source unavailability explicitly.
