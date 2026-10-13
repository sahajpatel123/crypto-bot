# Manager directive: crypto bot implementation under a 30-minute run limit

Issued 13 October 2026. Baseline checked: `main` at `d733a61273a9a954c56fd4aeeaf745ac939d3f60`; implementation parent `a890b19`.

Manager: execute this directive with the existing five workers. Own integration, resolve routine implementation decisions, and deliver working code and measured results. The owner communicates only with you. This document replaces previous instructions permitting long benchmarks or monitoring. Existing evidence and the previous readiness review remain applicable.

## 1. Outcome and boundaries

Build a bot capable of a controlled real-capital pilot, conditional on passing execution, accounting, operational and economic gates below. The product objective remains Binance USD-M crypto scalping, intended holds of 30–300 seconds, ₹10,000 initial capital, retained profits and an aspirational 2–3% net account return per day. Stops and emergency exits may close sooner than 30 seconds.

The current strategies have not demonstrated an edge: retained COMBINED validation returned -0.3063% over seven days with 11 closed positions; test returned -0.0770% over eight days with one. The previous independent suite passed 949 tests with one skipped. These are the starting facts, not release approval.

Deliver three separate verdicts: **software capability**, **evidence of positive net expectancy**, and **performance against the daily objective**. A positive backtest is not a guarantee of future profit. At a 0.125% per-trade risk ceiling, 2–3% account growth represents approximately 16–24 such risk units net per day. Do not increase risk, force trade frequency or relax evidence requirements to manufacture that result.

Keep Python and the existing pinned Nautilus integration. Profile before rewriting. No new LLM, paid news service, strategy framework or extra agents are required for this assignment. Preserve the one-position design. The first eligible pilot may use one validated strategy; retain the other families as disabled research candidates.

## 2. Hard runtime contract

**No continuous run may exceed 30 minutes.** Apply this to tests, downloads, preparation, replay, research, paper sessions, demo drills and their child processes. Long owner-stopped jobs stay stopped. This directive permits replacement work as genuinely bounded jobs.

- Default useful-work budget: **25 minutes**. Reserve the remaining five minutes for shutdown, checkpoints and reports. Prefer jobs of 2–15 minutes.
- Enforce an absolute monotonic deadline outside the worker being timed. Include setup, retries, subprocesses and cleanup. Children inherit the deadline; a restart must not reset it.
- An offline job reaching its deadline checkpoints and exits as `INCOMPLETE_BUDGET`, never PASS. A wedged offline process tree is terminated by the independent limiter before 30 minutes.
- No unattended loop that relaunches the same job every 29 minutes. Each batch ends, publishes results, and returns control to the manager. The manager inspects those results and selects a finite next job. Do not turn the old ten-hour run into a hidden continuous batch.
- A heartbeat is progress evidence, not permission to continue indefinitely. Emit elapsed time, records processed, checkpoint, throughput and remaining budget at least every minute.
- Every job declares an input hash, expected output, resource budget, maximum runtime and stopping condition before launch. If a two-minute throughput sample predicts an overrun, shrink the job before starting it.
- Use one heavy replay/preparation job initially; permit two only after measured memory and throughput show benefit. Five coding agents do not imply five simultaneous data replays on one laptop.

For paper/demo jobs: stop admitting entries by minute 20, begin closing/canceling by minute 25, and reconcile before the deadline. A venue outage can prevent flattening; record unknown exposure honestly and fail the drill. Never call a process timeout proof of a flat exchange account. No automatic continuation beyond 30 minutes is allowed.

Multiple short jobs may be necessary. This limit reduces the length of each run; it does not make total work or statistical evidence instantaneous.

## 3. Ownership and order of work

| Owner | Primary responsibility | First concrete deliverable |
|---|---|---|
| Manager | Integration, budgets, release decision | Frozen baseline and finite first batch; task ownership; brief progress/results page |
| Worker 1 — Execution | Correct paper/native IOC lifecycle; execution parity | Failing-before/passing-after IOC regression and corrected native integration |
| Worker 2 — Runtime | Independent control scheduling, bounded network work, explicit demo/production modes | Stuck-input drill and deterministic shutdown; production preflight implemented with order submission disabled |
| Worker 3 — Strategy research | Opportunity diagnosis, bounded candidate search and selection | Per-strategy signal-to-fill funnel and preregistered research round |
| Worker 4 — Data and performance | Shared cost contract, causal data, tracked bounded runner and checkpoints | Cost consistency examples, short throughput profile and resumable CLI |
| Worker 5 — Verification | Independent acceptance, risk/news checks, exchange-demo certification | Adversarial probes plus a ready-to-run bounded demo procedure |

Worker 4 owns the shared cost schema/formula; manager owns selector integration. Worker 1 owns paper execution; Worker 2 owns Session/CLI scheduling. Worker 5 reviews without silently editing another worker's files. Use the existing coordination mechanism and integrate small working changes. Do not build another task-management system.

First merge: run-budget enforcement plus execution regressions. Second merge: corrected execution/cost contracts and reliable control ticks. Economic scoring follows these corrections. Data preparation and demo packaging can proceed concurrently.

## 4. Correct execution and control behavior

### IOC regression

At T0, bid 99 / ask 101; submit BUY 0.001 capped at 100.50 with 50 ms submission delay and 50 ms modeled native latency. Advance to T0+200 ms. Then publish ask 100 at T0+1 s. The reviewed engine produces a fill at the later quote with `ioc_maker_relabeled=0`. The correct outcome is cancellation of the nonmarketable IOC remainder at arrival, with no revival on future liquidity.

Fix command-arrival scheduling and matching against the causally available book. Preserve separate execution and report-delivery timestamps. Merely changing a maker label to taker is insufficient. Use the existing native matching engine; do not introduce a second fill simulator or fabricate market ticks to drive it.

Acceptance covers both sides, marketable and nonmarketable IOC, partial fill plus canceled remainder, queued expiry, price-band enforcement, cancel/fill races, and genuine earlier fills reported late. Late reports must still update accounting exactly once when the execution was valid. Verify protective-order activation after partial fills and reduce-only behavior. Existing emergency exits currently bypass modeled latency: add a realistic nonzero-latency sensitivity and clearly label any immediate-exit diagnostic. Base economic results must not depend on instantaneous emergency execution.

### Independent controls

The current Session checks controls after the feed iterator yields; reconnect and REST work can block it. Move blocking input work behind bounded asynchronous/threaded I/O or a separate producer, while keeping one owner of account/order/risk state.

Use a 250 ms control-tick target and prove locally that a two-second blocked producer does not delay recognition of stop/entry-block instructions beyond one second. These are selected engineering acceptance limits, not exchange-latency promises. Network requests have deadlines within the job's remaining budget. Use a supervisor independent of the feed loop; a process restart enters reconciliation before new entries.

Record exchange-data age separately from local decision latency and order acknowledgement/fill latency. Start with a one-second maximum quote/valuation age for new entries, fail closed on missing timestamps, and validate the clock assumptions. Stale or lost data blocks entries while protective management continues. Measure p50/p95/p99 under a short burst replay; choose the number of active symbols from those measurements.

## 5. Make costs and market data consistent

There is a source-confirmed inconsistency to resolve before strategy tuning:

- `research/returns.py` and `specs/strategies/EXP-001.md`: `2*(fee+slippage)+spread+funding` = **26 bps** for the frozen 5/5/5/1 inputs.
- `coordination/selector.py`: `2*(fee+spread+slippage)+funding` = **31 bps** for the same inputs.
- The schema does not make one-way versus round-trip spread semantics explicit.

Define one versioned cost contract, with a price reference and leg-specific units, used by research, selector and risk sizing. Determine which existing consumers need migration; do not assume that reducing 31 to 26 is automatically correct. Actual booked P&L must come from fills, commissions and settlements, with spread already embodied in executable prices counted only once.

Golden example for the new explicit schema: 5 bps fee on each leg, a 5 bps full spread crossed through two 2.5 bps half-spreads, 5 bps additional adverse slippage per leg, and 1 bps total funding allowance gives 26 bps estimated total. Test asymmetric entry/exit costs and actual funding signs too. Replace assumed fees with verified account rates for production; absent rates keep production preflight blocked. Record estimated-versus-booked costs separately.

Audit the signal-to-trade funnel using unique candidate IDs and eligible time, not millions of repeated rejection rows. Distinguish: unavailable data, genuine missing sequence, a healthy interval with no trades, no setup, expected move below cost, quantity below minimum, stale/expired intent, nonmarketable band, IOC cancellation and exposure/cooldown blocking. Only create a zero-volume interval when feed completeness supports it; never fill a broken connection with invented clean bars.

Funding is zero only when actual position intervals avoid known settlement times or the applicable settlement is demonstrably zero. Short holds can cross a settlement. Wire provenance-backed funding into the frozen dataset. Unknown values remain unknown. Modeled quotes and unavailable historical depth remain visibly labeled; S5 cannot be validated on invented depth.

## 6. Historical coverage through short, honest jobs

Implement bounded execution in the tracked project CLI, reusing the streaming readers. Proposed controls: `--wall-budget-s 1500`, `--checkpoint-dir`, `--resume`, `--max-events`, `--report-out`. These are required additions, not claims that the flags already exist. Port useful `/tmp/w1bench` code into the repository; remove temporary-path dependencies from the supported workflow.

Reuse a causal columnar feature cache across strategies. Process source data in small batches with offsets/hashes; avoid repeatedly parsing the same multi-gigabyte stream. Aggregate repetitive diagnostic counters while preserving all financial events and material risk transitions. Profile CPU, parsing, database writes and fsync before optimizing.

**A checkpoint must preserve the economic experiment.** Do not reset equity, daily loss limits, profit floors, cooldowns or open-position state on each slice. Do not add forced exits just because a CPU budget expired.

Preferred first implementation: durable checkpoints at proven-flat boundaries, with no open/pending/unknown orders or undelivered execution events. Persist ledger/cash, daily reference and loss budget, cumulative profit floor, selector cooldowns, strategy state, causal warmup/book/mark/funding state, cursor and identity counters/seeds. If a budget expires mid-position, retain the uncommitted tail as incomplete and replay that tail from the last committed flat checkpoint on the next explicitly selected job. Never omit the tail from a final result because it contains a loss.

Do not assume native engine serialization is available. A new native instance may start at a verified flat checkpoint only after financial state and causally available market state are restored correctly. If exact restoration cannot be demonstrated, use separate predefined session experiments and label them as such; do not report their sum as a continuous-account backtest.

Acceptance: one reference replay finishing within ten minutes versus that same replay split across at least three process restarts must produce equivalent fills, equity, fees, daily stops and profit-floor actions, including a day boundary. Overlapping warmup is unscored and must not duplicate trades. Dataset/config/code changes invalidate incompatible checkpoints.

## 7. Research aimed at an executable edge

Use a two-stage process. First screen hypotheses cheaply using shared causal features; then run surviving candidates through the corrected production-equivalent strategy, selector, risk and execution paths. Coarse forward returns and bar-level diagnostics are research screens, not fill or profitability evidence. The older synthetic `research/returns.py` must not become the final execution model.

| Family | Hypothesis to test | Critical rejection/failure check |
|---|---|---|
| S1 breakout | Price expansion with usable directional activity continues after an executable entry | Chasing, false breaks, adverse movement during latency |
| S2 pullback | Resumption within an established trend offers sufficient net continuation | Late entry, ambiguous trend, stop distance/minimum-size conflict |
| S3 range/VWAP | Reversion toward value exceeds total execution costs in a quiet range | Range too narrow, trend transition, passive band used with IOC |
| S4 failed breakout | A measured reclaim supports a reversal toward the prior range | Genuine breakout mistaken for failure, insufficient remaining move |
| S5 depth/flow | Synchronized book and aggressive flow contain usable short-horizon information | Missing depth, stale snapshots, latency-sensitive apparent edge |

Run one bounded research round of **at most 12 preregistered configurations total**, including baselines and variants. Freeze every configuration, data split and stopping rule before its score is observed. Exclude ineligible families explicitly. Existing 2 bps bands, fixed holding periods and confirmation variants are hypotheses, not sacred optimal values; change them only for a stated mechanism and evaluate the change on development data. Never widen a band solely to improve fill count or lower costs solely to admit more trades.

The existing selector is a deterministic heuristic, not a calibrated expected-profit estimator. A target price above costs is not an expected-value calculation. Evaluate the distribution of actual net outcomes and cancellation opportunities. Initially deploy only the independently qualifying strategy/configuration. Enable a combined selector only if it improves out-of-sample behavior against that strongest single strategy under the same portfolio limits.

Use chronological folds, with boundary purging covering feature/outcome overlap, entry delay and maximum holding horizon. Preserve a trial registry including failed and discarded variants. Choose one final candidate before inspecting a fresh quarantined holdout. The already viewed validation/test dates are development/diagnostic knowledge for any subsequently tuned candidate; corrected reruns there are not new independent tests.

A fresh holdout can use suitable uninspected archive coverage if its chronology and selection history are defensible. If adequate data is unavailable, report that limitation; do not manufacture a holdout by renaming a split. If the round finds no candidate surviving costs, deliver the negative result and a specific next hypothesis. Do not keep adding infrastructure or tuning until one lucky curve is positive.

Required results: completed positions; net expectancy and uncertainty; gross/net P&L; fee/funding/slippage attribution; profit factor; maximum equity drawdown; worst trade/day; tail loss; holding times; eligible opportunities; fill/cancel rates; turnover; daily mean/median and frequency of hitting 2%/3%, including zero-trade days. Use actual account equity for account returns and point-in-time exchange filters/minimums for sizing. Report sensitivity to 1.5x variable execution costs and 2x modeled latency, with fees taken from their explicit schedule.

## 8. Preserve the intended operating behavior

Use the agreed candidate profile: one pending/open/unresolved position; leverage at most 3x; planned per-trade loss at most 0.125% of current equity including stressed costs; sizing limited further by remaining daily budget, profit-floor cushion and available margin. The daily operating stop is 0.5%; the 1% emergency threshold triggers an incident. Cancel entry orders, reduce/close permitted exposure and reconcile; a rejection label alone is insufficient. These thresholds trigger actions and cannot guarantee a maximum realized loss during gaps or execution failures.

Persist the 70% cumulative realized-gain retention floor after its arming threshold across days and process restarts. Keep the 2% daily profit pause. Deposits do not count as profits. Size down as capital falls; if exchange minimums cannot satisfy the risk budget, do not trade. Compounding follows reconciled equity. Never use loss-recovery sizing, martingale or a shorter-hold/higher-leverage rule. Report cumulative drawdown; do not silently invent a new owner-selected cumulative capital stop.

Keep authoritative FOMC, CPI and employment-release calendars with source, retrieved-at time, UTC conversion and expiry. Verify existing event gates instead of adding a new news subsystem. Start with a declared blackout from 15 minutes before to 30 minutes after each relevant event, extending through a separately scheduled press conference where applicable; these are policy defaults requiring evaluation. Manage exposure before the blackout; stale event coverage blocks entries. Unexpected shocks are handled by spread/volatility/depth/feed-health controls; a calendar cannot anticipate every shock. No LLM is needed in the trade path.

Discover eligible Binance USD-M perpetuals dynamically, then shortlist a small number using current liquidity, spread, feed quality and instrument filters. Start execution verification with BTC/ETH; expand only within measured resource limits and supported data. Preserve point-in-time universe membership in historical tests. The architecture may support many symbols while evaluating only the permitted active set; it cannot trade unsupported coins or every thin market indiscriminately.

## 9. Demo certification and real-capital capability

The current CLI exposes replay/paper modes and its live-engine route is demo-only. Implement an explicit production configuration/preflight path, separate from demo, with production order submission disabled by default. Demo keys must never be routed to production or vice versa. Bind any activation manifest to the reviewed code/config/strategy hashes and actual account identity; it must not self-approve because a test process exited zero.

Prepare a 15–25 minute demo procedure before asking for credentials. Owner credentials are configured locally. Verify account position/margin mode, available balance, fees, filters and server-clock offset. Use current Binance demo hosts and current conditional-order interfaces. Verify entry, IOC cancellation/partial remainder, exchange-side protection, reduce-only exit, user-stream loss, ambiguous submission without duplicate orders, restart adoption and final exchange/ledger agreement. Inject faults locally; keep exchange actions bounded and account-scoped. A missing credential is a specific blocker while other work continues.

Finish with a disabled-by-default, owner-launchable bounded pilot package only if the gates pass. Its duration obeys the same limit, with early entry cutoff and time reserved for closure. A fixed process deadline cannot guarantee venue closure during an outage: the package must include verified exchange-side protection, an incident handoff and an owner present for first activation. This assignment does not certify unattended 24/7 operation; short windows cannot establish long-duration reliability.

## 10. Release gates and final handoff

All gates must be reported separately:

| Gate | Required evidence |
|---|---|
| Runtime budget | Real wall-time limiter, child-deadline inheritance, incomplete status and no auto-relaunch; accelerated deadline tests |
| Execution/accounting | IOC conformance, nonzero-latency sensitivity, partial protection/recovery, exactly-once accounting, exchange/ledger agreement |
| State continuity | Short split-versus-reference parity; daily risk and cumulative floor survive process boundaries |
| Data/cost integrity | Causal availability, explicit gaps/modeled data, one cost contract, funding provenance and complete run identities |
| Economic candidate | Frozen candidate positive after all costs on development validation and fresh holdout; passes cost/latency stress; uncertainty and drawdown reported |
| Exchange operation | Bounded credentialed demo drill passed; actual production account preflight can be completed without submitting orders |

For the economic gate, adopt a conservative initial screening floor of **100 completed holdout positions over coverage spanning at least ten complete calendar days**, plus a positive lower endpoint of a preregistered 95% day-block-bootstrap interval for mean net daily return. Preserve temporal dependence and all calendar days in resampling; inspect sensitivity to block length. These are project screening criteria, not a guarantee or a universal sufficient sample size. Sparse, highly dependent, concentrated or unstable results remain INCONCLUSIVE even if a simple threshold passes. Do not keep peeking at a holdout and stopping at the first favorable interval.

Do not claim that the 2–3% daily objective is achieved unless the reported account-return distribution supports the stated claim. A qualifying positive-expectancy pilot candidate and achievement of that objective are different verdicts. If economics fails, production stays blocked while the technically complete research system remains usable.

Each completed batch returns: what changed; verification; elapsed time; artifact/checkpoint; observed economics or reason none exists; remaining blocker; finite next job. Include source/config/dataset/execution-model hashes and exact runnable commands. Report code delivery and evidence sufficiency separately. Keep the final owner summary to one page with links.

### First batch to dispatch now

1. Freeze this baseline and install the deadline wrapper with a seconds-scale self-test.
2. Workers 1/2 reproduce and fix IOC/control-loop behavior; Worker 5 preserves independent probes.
3. Worker 4 unifies cost semantics and profiles a fixed development slice; Worker 3 produces the opportunity funnel and freezes the first research round.
4. Integrate the smallest corrected vertical slice, run relevant checks and one integrated suite, then publish the results before selecting the next bounded batch.

### Primary references

- [Repository baseline](https://github.com/sahajpatel123/crypto-bot/tree/d733a61273a9a954c56fd4aeeaf745ac939d3f60).
- [Current selector](https://github.com/sahajpatel123/crypto-bot/blob/d733a61273a9a954c56fd4aeeaf745ac939d3f60/src/cryptobot/coordination/selector.py) and [research cost calculation](https://github.com/sahajpatel123/crypto-bot/blob/d733a61273a9a954c56fd4aeeaf745ac939d3f60/src/cryptobot/research/returns.py).
- [Nautilus orders](https://nautilustrader.io/docs/latest/concepts/orders/) and [backtesting](https://nautilustrader.io/docs/latest/concepts/backtesting/). Verify API details against the pinned 1.231.0 package; latest documentation may describe a newer API.
- [Binance USD-M general information](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/general-info): demo endpoints and ambiguous execution outcomes.
- [Federal Reserve calendar](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm), [BLS CPI schedule](https://www.bls.gov/schedule/news_release/cpi.htm), [BLS employment schedule](https://www.bls.gov/schedule/news_release/empsit.htm).
