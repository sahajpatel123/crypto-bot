# Crypto bot: independent review and final-day execution directive
Issued: 12 October 2026, Asia/Kolkata  
Reviewed implementation: c6c567acbfe932397d588f682574e8195528f49e  
Main at review: 3cadfca527bee0b2170651b87287a4c7cb57c9b8 (subsequent handoff commit)  
Recipient: young-polaris, coordinating all five existing workers  
Target checkpoint: 13 October 2026, 20:53 Asia/Kolkata (15:23 UTC), following the owner's latest one-day instruction.

## Decision

Continue implementation. **Real-capital readiness is NO-GO at this reviewed version; profitable trading capability is unproven.** The simulation foundation has improved, but important integrations and the economic benchmark remain unfinished. A deadline cannot establish a return guarantee or override failed financial/execution checks.

This directive continues the previous assignment. It prioritizes completion of the trading application and evidence; it does not restart architecture work or request more agents.

The owner's latest loss requirement is interpreted as **0.5–1% whole-account daily loss**, alongside the 2–3% daily net-return objective and 70% realized-gain retention policy. The controls below are engineering thresholds, not guarantees of actual loss or profit under gaps, outages or slippage.

## 1. Review evidence and boundaries

- Verified exact Git blob hashes for 358 files at c6c567a, including all implementation and tests. One 4.46MB historical rejections CSV was excluded from materialization.
- Installed the locked project environment. Reproduced **825 passing tests, no xfails, in 43.78 seconds** with external HTTP/socket connections blocked and local loopback tests allowed.
- The ordinary full-suite run hit automatic approval review because unmocked Binance paths were detected. The safer run blocked external network access; add an equivalent default test guard to the repository. Public-data integration tests belong in an explicit separate profile.
- Independently reproduced six additional defects using temporary fixtures or recorded transports, without exchange orders or credentials.
- Full owner-local Parquets, new paper/capture run directories and /tmp benchmark reports were unavailable here. The original new runs and their economics are manager-reported, not independently rerun by the CEO review.
- No GitHub implementation files were modified by this review.

### What is working or demonstrably improved

| Area | Supported conclusion |
|---|---|
| Existing regression suite | 825 tests pass in the network-blocked review environment. |
| Earlier five review findings | Regression coverage now passes for causal spread/mark conversion, deduplication, gap propagation and buffered WebSocket draining. |
| Dataset provider and benchmark preparation | Batched Parquet reading, heap merges, bounded preparation/dedup and reusable partitions are implemented. The final Session consumer remains non-streaming. |
| Missing funding representation | Derived data explicitly records absent funding instead of silently claiming sourced zero funding. |
| Risk/account plumbing | Shared rounding, margin accessor consumption, in-flight exposure and mark/funding provenance are improved. |
| Reports and audit preservation | Structured reports and archived previous evidence exist. A complete new account benchmark/report is still required. |
| Event-control module | Event storage, timezone conversion and entry-gate components exist; production source refresh and active runtime coverage are incomplete. |
| Disabled exchange adapter | A contract prototype exists with recorded-shape tests. It is not a verified current Binance execution path. |

Manager-reported observations:
- Development prefix: BTC+ETH, 200,000 events; COMBINED completes one ETH position, net approximately -0.13%, fees approximately 0.061 USDT; CASH is flat.
- New observed capture/replay: 90 seconds, 123,101 events.
- New forward paper observation: 120 seconds, 164,442 events.
- Independent worker reconciliation reports no fills in both short operational runs. A zero-fill causality check is explicitly vacuous; it does not verify entry, protection or exit under exposure.

Keep those results. They are partial evidence, not a completed 30-day profitable track record.

## 2. Fundamental gaps: what the product still cannot substantiate

1. **Trading advantage.** No complete baseline, validation or untouched-test result demonstrates positive net expectancy. One losing development position neither proves a losing strategy nor supports profitable deployment. The target of 2–3% daily remains an objective, not demonstrated capability.
2. **Capital and profit protection.** Current 1% daily entry halt does not itself close open exposure. The global profit floor also gates entries; operational liquidation and remaining-loss-budget enforcement need explicit integration.
3. **News and market-condition awareness.** Event functions exist, but normal configs disable them. Source freshness is not real refresh, employment/BEA coverage is missing, and anomaly readings are not integrated.
4. **Order-flow availability.** “REST-primed” is not the same as a synchronized, continuously usable book. Future replay snapshots, failed bridge reporting and missing resynchronization affect S5 and book-dependent decisions.
5. **Real exchange lifecycle.** Current conditional-order routing is obsolete, private-stream/CLI integration is incomplete, and restart/fill identity defects can misstate actual exposure.
6. **Sustained operation.** Two-minute observations do not establish uninterrupted trading, reconnection, risk supervision, day rollover or recovery with exposure.

For every fundamental requirement, show the complete path: source → observation/state → decision → action → acknowledgment/reconciliation → persisted evidence. A function, fixture, config entry or component test alone does not close the requirement.

## 3. Technical findings and required corrections

### A. Reproduced defects

| Finding | Review reproduction | Correction and acceptance |
|---|---|---|
| Future snapshots visible at replay startup | _prime_replay_books installs every snapshot before any events. Two snapshots at 1000ms and 9000ms, then a 1500ms query, expose the later bid 200 with sync_age_ms=-7500 and quality=clean. | Interleave snapshots, diffs and availability/sync boundaries causally. Never publish negative-age data as clean. Future snapshot mutations must not affect earlier state, signals, fills or equity. |
| False live synchronization report | A buffered diff that cannot bridge snapshot ID 10 returns resync, but _prime_live_books ignores the result and reports BTCUSDT in synced. Actual book.state.synced is false. | Report actual outcome and current state separately from REST fetch success. Buffer before snapshot installation, bridge correctly and resynchronize after breaks or new-symbol discovery. |
| Event controls disabled | events_enabled=False in paper.toml, r2.toml and r3.toml. Anomaly policy has no runtime caller. | Supply an explicitly protected operational profile and wire calendar and measured anomaly decisions. Preserve explicit research-only profiles when historical calendar availability is unknown. |
| Calendar freshness renewed without fetching | Loading the same FOMC fixture on 12 and 14 October creates new fetched timestamps and fresh status, with identical cached events and no HTTP verification. | Preserve source verified/fetched timestamp across reload/restart. Implement background official-source refresh, cached outage behavior and explicit expiry. Local reading is not a successful fetch. |
| Cross-symbol fill loss | Two ORDER_TRADE_UPDATE fills with trade ID 777, one BTC and one ETH, produce only one EngineFill because _trades_booked is keyed by trade ID alone. | Use venue/account/symbol/trade identity consistently in user-stream parsing, lookup adoption, journals and ledger execution IDs; verify duplicate redelivery and distinct-symbol fills. |
| Unknown-outcome block lost on restart | A recorded 503 journals an UNKNOWN entry. Recovery retains its unknown ID but does not rebuild the reservation mapping. _unknown_for(r1) is empty and another entry with r1 is accepted. | Rebuild reservation, role, symbol, order/client identity, booked fills and terminal/unknown state before reconciliation. Block all relevant new exposure until unknown state is resolved; replay fills idempotently. |

### B. Source-inspected blockers

**Streaming stops at Session.** run_replay still calls load_events; the loader reads all JSONL lines, and replay_events sorts the whole list. Complete end-to-end streaming, including first/last timestamps, resume cursor, hashing and reports. Do not stop at provider-side batching.

**Risk timers remain feed-dependent.** run_live checks duration, risk and exits only inside event iteration. None heartbeats do not advance the native execution clock; synchronous priming/metadata calls can block. Implement an independent scheduler/watchdog, bounded communication and a single serialized state owner. Test hung socket dial, hung REST, no events and late queued submissions. Advance virtual replay time and native execution time causally.

**Price protection is not wired.** _maybe_admit submits MARKET despite entry-band sizing. Use the supported marketable price-protected IOC policy; make the cap and tick rounding side-aware. Cancel/expire rejected opportunities; bound late fills and partial exposure. Emergency exits retain realistic cost/latency assumptions.

**Daily/global halt actions are incomplete.** The health handler sets exit-only and halted state. It does not submit a loss/floor-triggered close. Add explicit cancellation, reduction/flattening, acknowledgment and retained unresolved exposure. Never clear a pending entry merely because cancellation was requested.

**Current Binance contract mismatch.**
- STOP_MARKET and TAKE_PROFIT_MARKET are still posted to /fapi/v1/order. Binance's official 2025-11-06 change announced migration effective 2025-12-09; legacy routes reject these types with -4120. Implement /fapi/v1/algoOrder, query/cancel/open-algo state and ALGO_UPDATE handling, including actual triggered order IDs.
- Default test host is the older testnet.binancefuture.com while current official docs specify demo-fapi.binance.com and demo-fstream.binance.com. Verify the chosen environment explicitly.
- Readiness fixtures invent marginType and dualSidePosition in account responses. Use documented account/configuration/position-mode endpoints and fields; /fapi/v2/account publishes isolated and positionSide. Do not certify behavior using invented shapes.
- Listen-key operations currently omit the API-key header. Account updates are only logged. Implement transport authentication, private-stream lifetime/reconnect, fill/account/funding consumption and reconciliation.
- The CLI only exposes replay and paper modes. Keep production disabled while completing an explicit demo mode and the application/adapter error contract.
- Preserve unknown exposure across cancel failures, transient not-found results and process crashes. A single lookup absence must not automatically prove an uncertain order never executed.
- Restrict ownership to the bot's known orders/positions. Do not alter unrelated leverage, margin settings, positions or orders.

**Funding completion is feasible to investigate now.** Monthly October archives are not the only source. The official public /fapi/v1/fundingRate history endpoint supports symbol/startTime/endTime and returns fundingTime, fundingRate and settlement markPrice. Fetch the selected BTC/ETH date range with pagination/rate-limit handling, preserve provenance, and reconcile exact settlement events. Verify actual availability before claiming success. Do not feed a realized future settlement rate into an earlier prediction. A missing-source status stays explicit if requests fail.

**Reports need actual ownership/config identity.** Preserve strategy and exit reason per position, full effective config, code/data fingerprints, coverage and execution assumptions. Separate open exposure from completed positions; reconcile funding/costs without double allocation.

## 4. Updated loss and gain controls

Implement these as a versioned candidate risk profile and compare it with the old profile. The latest owner requirement takes precedence over older 1% defaults.

| Control | Initial decision |
|---|---|
| Planned risk per new position | At most 0.125% current reconciled equity including stressed costs, further reduced by remaining daily/floor/margin budget |
| Daily operating loss stop | At 0.5% flow-adjusted decline in conservative net-liquidation value from reconciled IST day start: block entries, cancel pending entries and reduce/close bot exposure |
| Emergency incident threshold | At 1% daily decline: persist emergency state, continue verified exposure-reduction attempts, alert with balances/exposure, and require reconciled recovery before entries can resume |
| Leverage/concurrency | Retain 3x cap and one global pending/open/unresolved exposure budget |
| Daily profit target | Existing 2% net-liquidation pause; manage remaining exposure normally and measure 3% outcomes honestly |
| Global earned-profit floor | Once net realized gains reach 1% original pilot equity, ratchet floor upward to original equity + 70% peak cumulative net realized gains, flows excluded |

At INR 10,000 equivalent, 0.125% planned risk is INR 12.50; daily thresholds correspond approximately to INR 50 and INR 100. Use actual USDT equity at runtime, not a hardcoded rupee conversion.

Before each entry, reserve loss-to-invalidation plus fees/adverse execution against:
1. The per-position limit.
2. Remaining daily operating-loss budget.
3. Cushion above the global earned-profit floor.
4. Available margin and instrument minimums.

Use the smallest feasible budget. If minimum venue size cannot fit it, skip the trade. Do not increase leverage or risk to satisfy minimum size or recover losses.

Measure losses and gains after commissions, applicable funding and estimated executable close costs. Never compare only realized P&L while ignoring an open loss. A daily loss halt/global floor breach must cause an action, not just a status label.

The floor ratchets across days/restarts; daily rollover cannot erase it. Model close costs before using its cushion. Gaps, outages or slippage can overshoot thresholds: record the actual breach and reason instead of displaying a guaranteed cap.

These are daily controls. The owner has not selected a permanent cumulative capital cutoff; do not silently invent one or attribute one to them. Report lifetime drawdown and retained gains explicitly.

Required tests include:
- Open loss crosses 0.5% with zero new strategy signals.
- Trade request would exceed remaining daily budget.
- Profit floor breach during silence, after midnight and after restart.
- Partial fill and cancellation race near a halt.
- Stop rejection/late acknowledgment and unknown order outcome.
- Daily drawdown overshoots in a stressed gap: emergency action and honest reporting.
- Nonfinite/unknown margin or stale valuation blocks entries.
- No martingale, profit quota or automatic risk expansion after loss.

## 5. Five workers, concrete deliverables

Keep the existing six CLI sessions. All five workers are currently idle; activate them with real acknowledgments immediately.

| Owner | Next assignment | Required output |
|---|---|---|
| W1 whisper-redshift | Finish streaming Session replay and execute economic benchmarks | Method-scoped replay patch, full combined-account result, then strategy comparisons/limited research |
| W2 cloud-vega | Fix snapshot causality/synchronization, data clocks and funding backfill | Before/after probes, usable-book coverage, verified BTC/ETH settlement inputs and streaming provider parity |
| W3 cool-amalthea | Enforce daily/floor actions and repair the Binance contract/restart identities | New risk profile, halt/close tests, current API contract, demo lifecycle readiness |
| W4 white-aldebaran | Activate event/anomaly protection and real source freshness | Protected paper profile, official refresh, measured anomaly inputs/actions and replayable evidence |
| W5 crystal-parallax | Independently verify findings, reports and operational supervision | Network-blocked tests, metric reconciliation, sustained-run status and resource profile |
| Manager young-polaris | Shared wiring, serialized integration, independent risk review and scheduling | Runnable integrated commits and one outcome board with exact blockers |

Avoid simultaneous ownership of app/session.py: assign method-scoped patches in isolated branches, with manager serializing integration. W1's streaming patch is the first shared-file integration; risk/event method patches follow through the same queue. The manager must not remain the sole implementer of every blocking Session change.

Worker 3's risk changes require manager/W5 independent review. Worker 5's metric changes require another reviewer. Preserve the existing shared contracts; change them only where a concrete integration requires it.

## 6. One-day execution sequence

Target the checkpoint above. Keep long runs persistent and resource-bounded; no arbitrary session-number target.

**First 0–3 hours**
- Reproduce the new snapshot and adapter defects.
- Integrate streaming replay; prove deterministic parity on a short observed dataset and measure one full day.
- Freeze the new risk profile and corrections before economic scoring.
- Begin current-contract repair, calendar refresh and independent scheduler work in parallel.
- Fetch and verify October BTC/ETH funding through the public history API if available.

**Hours 3–8**
- Complete independent-clock, snapshot, entry-bound and daily/floor action checks.
- Start a continuously supervised paper run with protected configs as soon as its execution gate passes. Record its actual elapsed observation.
- Run the complete 30-day COMBINED account baseline and cash comparison first. Do not use max-events for a claimed full-window result.
- Maintain progress/coverage checkpoints and report measured ETA early.

**Hours 8–18**
- Execute single-strategy development/validation comparisons and a small preregistered improvement batch only if baseline supports a specific hypothesis.
- Score the final test period once for the frozen candidates. Track data-window exposure across output directories.
- Run predeclared adverse spread/delay/cost profiles.
- Verify demo order → partial/full fill → protective conditional order → exit → sibling cancellation → reconciled flat exposure.
- Inject faults separately from untouched performance observations.

**Hours 18–24**
- Independently reconcile actual fills, funding, positions and account curve.
- Deliver full reports and exact current-run status.
- Publish separate software, economics and operations decisions with a concrete proposed pilot package only if evidence supports one.

The first combined benchmark is about 70.6 million manifest rows for BTC+ETH. Do not require all 21 comparisons to finish before exposing the first full account result. Use bounded reusable inputs and measured concurrency; preserve event execution semantics. If runtime exceeds the deadline, deliver exact completed coverage and remaining ETA, never a prefix labeled 30 days.

No parameter optimization on the final test, no increased risk to obtain 2–3%, no forced trades to make paper activity look successful, and no production orders merely because the clock expired.

## 7. Economic and operational acceptance

A credible report must show whole-account net result, maximum drawdown including open exposure, completed position count, net expectancy/uncertainty, costs, daily results including no-trade days, actual strategy ownership, exit reasons, coverage, rejections, latency tails and stress sensitivity.

Separate:
- Software correctness.
- Strategy economics.
- Demo exchange mechanics.
- Forward paper observation.
- Any eventual bounded production pilot.

A positive single trade or development prefix cannot support profitability claims. An eight-day final sample is still a short sample; report uncertainty and dependence across trades/regimes. A no-trade run is valid, but it is not positive-return evidence.

A real-capital proposal requires corrected causal/exposure defects, completed meaningful unseen-data evidence, understood cost/drawdown behavior, current venue lifecycle verification and monitored recovery. Even then 2–3% daily is unguaranteed.

Classification at the checkpoint:
- NO-GO: material defects or negative credible economics.
- INSUFFICIENT EVIDENCE: functioning system without adequate data/observations/execution validation.
- READY FOR BOUNDED PILOT REVIEW: evidence supports that exact limited proposal.

Production activation remains a separate explicit decision on a concrete package. Demo credentials may be requested once the current endpoint configuration and test script are ready. Store them locally through an appropriate secret mechanism; never ask for secrets in chat. A demo uses simulated funds and is sufficient for the next API-mechanics drill.

## 8. Final handoff requirements

Return:
1. Integrated SHA, clean normal installation, tested backtest/report/paper/demo/status/stop commands.
2. Before/after proof for every high-priority finding.
3. Current five-worker status and any exact owner dependency.
4. Full-window coverage, immutable data/config/code identities and all assumptions.
5. Actual summary/trades/equity/daily/rejections/HTML outputs in durable project-owned paths.
6. Net result, drawdown, daily/floor breach behavior, costs, position count and strategies retained/retired.
7. Actual paper elapsed/healthy time, PID/run ID, heartbeat, recovery evidence and next action.
8. Separate readiness decisions. No routine technical task should be pushed back to the owner.

Preserve prior evidence. Mark materially changed economic results superseded; do not erase them. Run targeted checks during implementation and the full network-blocked suite at integration checkpoints. Public API tests must be explicitly separated and never submit production orders.

## Official sources checked for this review

- Conditional-order migration and -4120 rejection: https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/change-log (2025-11-06 entry).
- Current order/conditional APIs: https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade
- Account/position-mode response contracts: https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/account
- Public funding-rate history: https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data
- Demo environment and uncertain execution responses: https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/general-info

Verify current official semantics and actual demo responses during implementation. Hand-built recorded-shape fixtures are contract hypotheses until that verification occurs.
