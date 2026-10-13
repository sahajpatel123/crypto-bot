# Crypto bot: independent handoff review and focused correction directive

Reviewed 13 October 2026. Repository: https://github.com/sahajpatel123/crypto-bot
Frozen revision: `cdcd10cbb40c3983b78b73b3d924a00aeb62a8c5`.

**Decision: keep real-capital trading disabled. Engineering progress is real, but execution and resumable research still have reproducible defects. Strategy expectancy is unproven; the 2–3% net daily objective is unsupported.**

Manager: work with the existing five workers. The owner communicates only with you. This is a correction to the last assignment, not a new architecture project. Keep Python, the pinned Nautilus integration, the current risk limits and the 30-minute maximum continuous runtime. Do not send the owner back to individual workers.

## What was independently checked

I inspected the actual integrated GitHub revision, reconstructed source files with matching Git blob hashes, ran the available suite, and ran additional offline probes using Python 3.12.14 and Nautilus 1.231.0. No exchange credentials, network trading or real orders were used. No production code was changed in this review.

The first suite run produced 1,014 passes, nine failures and one skip in 186.76 seconds. Eight failures came from two files missing from my audit copy, not repository defects. Fetching those exact revision files and rerunning their eight tests produced eight passes. The remaining nested-budget failure was reproduced with a separate short subprocess probe. Thus 1,022 distinct suite tests passed across these checks, one budget test failed locally, and one was skipped; I did not independently reproduce an entirely green suite. The budget result is platform-sensitive and must also be checked on the owner's Mac.

The supplied `Crypto_Bot_cdcd10c_Review_Probes.py` and its JSON results make the new findings reproducible. The complete custom probe took **8.781 seconds**. Its synthetic prices and fills demonstrate software behavior only.

Confirmed progress includes the cost-contract consolidation, rejection of nonmarketable IOC orders at arrival, responsive-control infrastructure, explicit incomplete-run reporting, and real separation between paper and credentialed demo execution. These improvements do not establish profitability. The manager's large archive/capture runs and their temporary artifacts were not rerun in this review.

## Findings that block acceptance

| Finding | Independent evidence | Consequence |
|---|---|---|
| Marketable IOC can still use future liquidity | With bid/ask 99/101, BUY limit 101.50, 50 ms submit and 50 ms fill delays: no fill at 200 ms; a quote ten seconds later at ask 90 produces a BUY at 90. | Fixing nonmarketable arrival cancellation did not finish IOC causality. Simulated opportunities, prices and exits can be distorted. |
| Checkpoint omits trading context | Before checkpoint: 135 rolling bar slots, warmed up. A newly built session restored from it has zero feeds and `warmed=False`. A changed cooldown configuration also resumes without refusal. | Chunked research can change decisions and silently change the experiment. Zero-trade balance parity is insufficient. |
| Checkpoint flat detection is incorrect | After a completed synthetic buy/sell round-trip, `open_orders()` returns two `filled` historical statuses and `_is_flat()` returns false. Separately, a ledger with 0.5 open quantity but no Session position is called flat. | Useful checkpoints can stop advancing after trading; inconsistent exposure can be checkpointed as flat. |
| Entry freshness is not scoped to the candidate | With BTC inserted first: fresh BTC/stale ETH passes `_quote_age_gate()`; stale BTC/fresh ETH fails. The method has no candidate-symbol argument and selects a reference valuation mark. | One coin's freshness can permit or block another's candidate. An exchange mark also cannot stand in for executable bid/ask freshness. |
| Nested deadline is not reliable in this environment | Repository test took about 60 seconds against its 3-second budget. A separate 1-second outer/30-second inner wrapper with an 8-second sleeping child returned after 8.068 seconds, while its report claimed 1.116 seconds. | A wrapper exit/report does not prove descendants stopped. Fix and verify on the target OS before calling the hard runtime rule satisfied. |

Relevant code: `src/cryptobot/adapters/paper_engine.py` (`_submit_now`, `feed`, `_sweep_ioc_remainders`, `open_orders`); `src/cryptobot/bench_run.py` (`_is_flat`, `_snapshot`, `_restore`, `run`); `src/cryptobot/app/session.py` (`_quote_age_gate`, `_reference_mark_full`, `_maybe_admit`); `tools/run_budget.py`.

Additional corrections to the handoff:

- **65-minute warmup is unexplained.** The default is 130 one-second bars. The clean synthetic ingestion probe becomes ready after 131 seconds. This does not prove the recorded capture should warm in exactly that time, but demands a timestamped explanation of any 65-minute delay. If only 14 of 79 minutes were eligible, use 14 minutes when estimating opportunity frequency; do not count startup as strategy observation.
- **ROUND-01 and the runtime selection disagree.** ROUND-01 excludes S2-V/S2-F, but `arms=all` includes both. The runtime list has 11 distinct S1–S4 arm IDs; “18 arms” may describe evaluation rows/directions, not 18 independent configurations. Export the exact identities and compare them mechanically against the frozen registry.
- **Public-feed paper trading needs no demo keys.** The Nautilus branch of `cli.py` does not read them. Only the `engine.kind=live` demo branch does. Remove the false dependency without bypassing the demo guard.
- **Production configuration is not production capability.** `tools/preflight.py` validates configuration, not signed Binance account state. `cli run --mode` still accepts only replay/paper and its exchange branch explicitly constructs a demo engine. Label the current preflight CONFIGURATION-ONLY, not account readiness or production GO.
- The archive's minute marks cannot validate a live policy requiring one-second valuation freshness. Preserve source timestamps; do not forward-fill and relabel observations as fresh. A zero-order result caused by incompatible data is not an economic test.

## Exact work assignment

### Worker 1 — Correct simulated order timing

Reproduce the supplied marketable-IOC probe before changing code. Process scheduled command arrival and execution events in chronological order, against information available at their modeled times. Match available executable liquidity and cancel the remainder at that matching opportunity. Separate execution time from delayed acknowledgement delivery. A later acknowledgement must not choose a later execution price.

Remove acceptance based on “accept tick plus one tick”: two ticks have no fixed duration and can span seconds or minutes. Handle partial fills, no subsequent tick, a long data gap, BUY/SELL mirrors, a cancel/fill race and expired entry windows. Inadequate liquidity data must be declared or rejected under the experiment's predeclared model, not invented. Verify actual matching behavior in the pinned Nautilus version before selecting a fix; do not reintroduce blanket maker relabeling as a substitute.

Acceptance: the new quote ten seconds later cannot determine this IOC's execution; nonmarketable cancellation still works; partial remainder cannot revive; filled quantity, fees and protection reconcile exactly once. Retain the zero-latency-exit diagnostic label and a realistic-delay evaluation path.

### Worker 2 — Make bounded replay preserve the experiment

Fix the flat predicate across Session state, ledger exposure, engine position, pending commands, nonterminal orders, unresolved outcomes, unconsumed execution events and risk reservations. Terminal historical order records alone do not mean open exposure. Never force a resumable flat checkpoint merely because input or wall budget ended.

Preserve or deterministically reconstruct rolling bars, aggregation watermarks, trade/depth sequence state, book and flow, marks and funding state, strategy/anomaly state, cooldowns, engine cash/margin, daily references, profit floors, IDs/RNG and pending actions. Replaying a bounded causal prefix is acceptable if it cannot re-book P&L or change decisions. Restore report/store cursors transactionally so replaying an uncommitted tail cannot duplicate diagnostic or financial records.

Bind resume to source/config/strategy/cost/dataset/filter identities and reject mismatches. Mark incomplete exposure with a valid sourced price or explicitly unavailable valuation, never price zero. A truncation or unresolved end state must not become a completed economic result.

Acceptance: compare one short reference with several restarts using a deterministic scenario that actually enters, partially fills, exits, takes a loss and crosses an accounting-day boundary. Interrupt both while flat and while exposed. Require equal intents, orders/fills, fees/funding, marked equity, daily stops and profit floors, plus continued checkpoint progress after the first round-trip. Synthetic proof validates mechanics only.

### Worker 3 — Correct freshness and make data eligibility observable

Give admission explicit candidate-symbol context. Track executable quote/trade/book age separately from exchange valuation-mark age. Reject missing, future or stale required observations without substituting another symbol or refreshing an old timestamp to receipt time. Test fresh/stale BTC/ETH in both directions, a fresh mark with an old executable quote, a fresh quote with an old required mark, and malformed timestamps.

Audit dataset compatibility before expensive scoring: required channels, timestamp meaning, observed cadence, continuity, marks, snapshots, funding, filters and exact coverage. Emit an explicit UNSCORABLE result when essential evidence is missing. A coarse diagnostic research profile may be separately frozen and labeled; it must not silently weaken live rules or certify live readiness.

For the existing capture, export first event, first usable bar, first 130-bar state, first per-strategy eligibility, gate-ready time and eligible duration, all on one clock. Explain the claimed 65-minute warmup using actual artifacts. Do not add a disorder buffer or change warmup length without evidence that it is needed.

### Worker 4 — Run the frozen economic experiment on eligible data

Enforce the exact ROUND-01 allowlist in executable configuration. Compare resolved runtime arm IDs/parameter fingerprints with the registry before running. Retain failed/discarded trials and correct the misleading “18 arms” terminology. Preserve a candidate's original strategy decision when a later execution gate blocks it.

Report a funnel using unique decisions and eligible symbol-time: usable data → strategy eligible → setup → cost pass → portfolio/risk pass → submitted → filled → closed. A million repeated rejection rows must not imply a million independent opportunities. Separate no setup, startup, stale input, missing depth, below costs, minimum-size rejection and IOC cancellation.

After Workers 1–3 pass, run a small development comparison of registered single strategies and CASH before selecting a combined configuration. Use bounded historical slices with compatible data; a short wall-clock replay may cover much longer market time. Do not widen bands, reduce cost assumptions, increase leverage or add variants to force a profitable result. Negative results require a mechanism-based next hypothesis, not another infrastructure milestone.

Deliver closed-trade count, eligible hours/days, fill rate, net expectancy with uncertainty, gross/net P&L, fees/funding/slippage, drawdown, worst trade/day, exposure, holding times and net daily returns including zero-trade days. Separate estimates from booked costs and avoid deducting spread twice when execution prices already include it. Report sensitivity to adverse costs and latency.

### Worker 5 — Independent acceptance and runtime enforcement

Own the new review probes and reproduce failures before fixes. Independently review Workers 1–3; pending reviews are substantive verification, not attestation-only paperwork. Validate the research allowlist and cost reconciliation.

Repair or demonstrate the nested-budget behavior on the actual Mac and the intended deployment OS. Test nested sessions, reparenting, a child ignoring SIGTERM, inherited output pipes and shutdown races. Prove all owned descendants stop, rather than trusting the wrapper's elapsed field. Use seconds-scale children, retain process identity safely, and do not kill unrelated processes.

Acceptance is an integrated revision passing adversarial end-to-end cases, with commands and evidence retained. Do not remove a failing test, loosen it merely to pass, or use an all-flat replay as proof of trading continuity.

### Manager — Integration and the exchange boundary

Freeze the reviewed baseline; reserve separate file ownership and integrate overlapping Session edits deliberately. Review Worker 1 execution and Worker 2 checkpoint semantics yourself. Replace `TBD` with the tested SHA, preserve source config and dataset hashes, and store the small evidence package under `reports/`, not only `/tmp`.

Correct the paper/demo distinction immediately. Package a credential-free public-data paper command and a separate credentialed demo command, both bounded. Implement a read-only production readiness command that verifies account identity, venue balances/positions/orders, actual fees, available margin, symbol filters, leverage/margin/position modes and permissions when local credentials are available. Missing credentials should block only those signed checks. Secrets stay in the owner's local environment and out of messages, repository and reports.

Document and implement any still-missing production adapter/CLI routing behind default-off guards, with exact host separation and a usable account reconciliation path. A configuration-only preflight must never stand in for that work. Production submissions remain disabled during this assignment. Credentialed demo verifies exchange mechanics; simulated/demo profits do not validate a real-money edge.

## Runtime, economics and final decision

Every continuous job must end inside 30 minutes, including setup, child processes and cleanup. Default to at most 25 minutes of work with the remainder reserved for shutdown; prefer seconds-scale probes and 5–10-minute diagnostics. Each job declares one purpose, output, deadline and stopping condition. No automatic rolling relaunch, repeated 29-minute monitoring loop or revival of owner-stopped work. Review results before starting the next finite job. For paper/demo, stop new entries early enough to close permitted exposure and reconcile before the deadline.

The previous 100-closed-position/10-complete-day threshold is a conservative promotion floor, not a reason to postpone debugging or exploratory development. It is not a guarantee, and clips from ten dates are not ten fully observed days. Genuine prospective time cannot be manufactured with more agents. Uninspected historical data is usable only with a defensible chronological experiment; already inspected test outcomes are now development knowledge for changes informed by them. At a true rate near one trade/day, 100 positions would ordinarily need far more than ten days. First measure the corrected eligible opportunity rate.

Maintain one pending/open/unresolved position, leverage ≤3x, planned per-trade loss ≤0.125% of equity including stressed costs, further limited by daily/floor/margin budgets. Keep the 0.5% operating-stop action, 1% emergency incident action, 70% profit-floor retention after arming and 2% profit pause. Stops trigger actions; gaps and execution failures can exceed their thresholds. No recovery sizing, martingale or forced daily profit quota. ₹10,000 remains the one-time capital assumption.

The next handoff must answer, in plain language:

1. Are the reproduced execution, checkpoint, freshness and deadline defects fixed on the integrated SHA?
2. Can each mode run through its intended path, and which signed venue checks remain blocked?
3. Is at least one strategy demonstrably profitable after realistic costs on eligible untouched evaluation data, with adequate uncertainty analysis?

Until the third answer has supporting evidence, the correct status is **research/paper only**. The first two answers are useful progress, but cannot guarantee the third or the 2–3% daily objective. No additional agents, language rewrite or LLM purchase is justified by the current findings.

## References and attachments

- Reviewed source: https://github.com/sahajpatel123/crypto-bot/tree/cdcd10cbb40c3983b78b73b3d924a00aeb62a8c5
- Nautilus defines IOC as immediate execution with the remainder canceled: https://nautilustrader.io/docs/latest/concepts/orders/ . API-specific probes above use pinned 1.231.0, not an assumption of current-version implementation parity.
- Binance documents one-second or three-second mark streams: https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/market#mark-price-stream . Feed cadence must be distinguished from quote freshness and local delivery latency.
- Reproduce offline: from the checked-out repo, with its installed dependencies, run `PYTHONPATH=src python /path/to/Crypto_Bot_cdcd10c_Review_Probes.py`. Keep the external runtime cap. The JSON describes observed behavior; it is not an all-green gate and must be converted into independently reviewed regression tests by the manager.
