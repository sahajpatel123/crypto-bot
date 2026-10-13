**CORR independent review and manager execution directive — 13 October 2026**

Decision: **NO-GO for real capital.** Earlier corrections made real progress, but the integrated Session still mishandles protective orders, the new economic scorer has correctness defects, and no profitable strategy has been demonstrated. Production submission must remain disabled during this assignment.

Reviewed repository: https://github.com/sahajpatel123/crypto-bot

Reviewed HEAD: `0d40ad3b671741baad7b0ced3738b8b1549e5962`. This is a documentation-only successor to the reported `1e65267`; the reviewed implementation is therefore the handoff implementation. This is a review of code and evidence, not authorization to place production orders.

**1. What was independently verified.** The review used a separate local copy, checked 478 retrieved/copied files against their Git blob hashes before testing, and ran Python 3.12.14 with NautilusTrader 1.231.0. No exchange credentials or orders were used.

| Area | Observed result | Decision |
|---|---|---|
| IOC arrival pricing | Original BUY probe fills at 101 by the 200ms processing opportunity; the quote ten seconds later at 90 produces no fill. | Earlier future-price defect fixed in this case. |
| Checkpoint continuity | 135 bar slots and warmed state survive; orphan ledger exposure is not called flat; changed configuration is refused; terminal order history permits flatness. | Earlier checkpoint defects fixed in the reproduced cases. |
| Candidate freshness | Current permanent symbol-scoped acceptance tests pass. | Earlier first-symbol-wins defect addressed. |
| Session protection | Actual 0.332 fill compared with 0.33293226 approval; six live protective orders forgotten; repeated emergency-close requests. | Blocking integrated defect. |
| Restart acceptance | Existing tape completes only after later market moves clear leftover exits. Keeping subsequent prices inside the bracket ends INCOMPLETE_EXPOSURE despite zero ledger quantity. | Deterministic recovery does not establish a correct trading lifecycle. |
| Economic reports | Partial exit counted as a closed trade; daily net omits funding and uses UTC dates; opportunity coverage mixes clock-seconds and symbol-seconds. | Repair before using these metrics for promotion. |
| Strategy evidence | Committed ten-cell panels contain zero completed trades; all 62 generated setups fail the cost check. | Positive net expectancy remains unproven. |
| Exchange operation | Production route deliberately refuses; credentialed demo lifecycle remains unverified. | Operational launch gate remains closed. |

The full suite here completed in 194.00 seconds: 1,099 passed, eight failed, one skipped. Three failures were caused by an omitted `coord/workers.json` in this review copy; after retrieving the exact file, all three passed. A targeted rerun finished in 50.68 seconds with 18 passed and five deadline tests still failing. Those five concern descendant enumeration/termination on this Linux environment; the daemon-survival test produced its survival marker. This does not establish identical failure on the owner's macOS machine. It does mean the claimed runtime enforcement was not independently certified here. Do not change assertions to hide this platform difference.

The attached independent probes complete in about seven seconds. The full raw public captures and manager's `/tmp` run directories were not available in this review copy, so the ten economic panels were inspected, not independently regenerated.

**2. The blocking technical findings.** Reproduce these first, preserve the failing observations, then fix the actual runtime path.

- **Reservation-to-position transition:** `NautilusPaperEngine._propagate_live` books fill deltas, but the Session path never performs the corresponding first-fill reservation transition. The observed entry leaves `policy.open_position=False` and the original reservation present. Later expiry moves the reservation into unresolved state. Booked exposure still blocks new entries; this finding is not a claim that a second position was admitted.
- **Protection quantity and lost children:** `Session._ensure_protection` demands the original approved quantity after the executable quantity has been rounded/filled. It compares 0.33293226 against a 0.332 stop, records `qty-short`, and clears `pos['legs']` without confirming cancellation. Three attempts leave six live children outside that list. `_flatten` subsequently cancels only the remembered list.
- **Incomplete close/settlement:** there is no adequate Session-owned sibling cancellation/reconciliation in this reproduced lifecycle. The original restart tape logs 2,040 `protection-emergency` checkpoints. A second tape preserving the same entry but removing later stop/target crossings logs 2,916 and ends `INCOMPLETE_EXPOSURE`. Ledger cash is flat, but the order lifecycle is not settled. These are repeated emergency-action records, not 2,916 executed orders.
- **Scoring errors:** `research.scoring._link_trades` counts an entry of 0.01 followed by an exit of 0.005 as one closed trade, even though 0.005 remains open. A separate fixture with 0.94 trade P&L and −0.20 funding reports booked net 0.74 but daily/trade net 0.94. Both fills occur on 12 October in Asia/Kolkata; the panel reports 11 October. `research.funnel.analyze_run` also collapses BTC and ETH observations within one second into one eligible second. Dividing that numerator by two-symbol elapsed time does not yield valid symbol-time coverage.

The W2 handoff already disclosed the Session defects. Classifying them as followups, then treating zero-trade panels as evidence that they were absent, was the acceptance mistake. Zero fills never exercise entry protection or exit cleanup. The existing restart regression proves repeatability, including repeatability of the faulty behavior.

**3. The fundamental problem.** The current evidence establishes neither a working profitable trade nor a positive expected return after costs. The ten panels show 62 cost-rejected setups, no submitted economic entries, and zero P&L. That is a valid negative finding about this configuration and these samples. It neither proves the entire strategy family worthless nor supports live funding.

The Phase-B proposal that projected reward margins near the cost threshold establish a profitable margin band is invalid. A target's distance from entry is not its probability-weighted expected payoff. Research must measure subsequent executable outcomes, losses, costs, and unfilled orders. Changing the threshold merely to obtain fills would not establish an edge.

The reported 17.3% and 7.8% eligibility fractions need recalculation because of the denominator mismatch. Separately, W3's raw-data explanation of the 65-minute wait is useful: mechanical warmup takes roughly 131 seconds, while requiring 120 consecutive trade-containing seconds delays strategy eligibility. Determine whether empty seconds are healthy inactivity or missing data; do not silently manufacture trade bars or loosen freshness checks.

The daily 2–3% account-return objective remains an aspiration. It is not a minimum return the code can enforce. The loss controls below are action thresholds and planned-risk budgets; gaps, slippage, or venue failure can exceed them. Additional agents can shorten implementation work but cannot create unobserved market evidence.

**4. Manager operating rules.** Keep the current Python/Nautilus architecture. Use the five existing workers. Assign one owner per writable file; integrate a working vertical slice before widening the strategy matrix. No language rewrite, LLM trading brain, new strategy catalogue, or unrelated infrastructure work in this assignment.

Every job, including setup, children, retries and cleanup, must finish within 30 minutes of wall time. Use at most 1,500 seconds of work and reserve the remainder for termination/cleanup. Do not set a 1,800-second work timeout and then add cleanup. A cutoff is INCOMPLETE, never success. No automatic relaunch of stopped monitoring, and no rolling short sessions disguising a continuous long soak. Finite historical shards may resume from verified checkpoints as separately bounded jobs; preserve chronology and do not score an incomplete shard as a complete experiment. Parallelize independent coding; initially serialize expensive replays because four-way contention previously exhausted budgets.

Retain the agreed safety profile in the designated pilot configuration: one global pending/open/unresolved exposure; leverage at most 3; planned per-trade risk at most 0.125% of current equity including stressed costs and the remaining daily/floor/margin constraints; 0.5% daily operating stop and 1% emergency escalation; 70% profit-retention floor after 1% arming; 2% daily profit pause. Use the ₹10,000 one-time-capital assumption, with actual USDT equity and fees obtained through the correct account boundary. Preserve flow adjustments and restart state. Do not add martingale, recovery quotas, leverage escalation, or a new permanent capital-stop policy. Retain scheduled-event, abnormal-market and stale-data entry blocks, while allowing required exits.

| Owner | Concrete assignment | Required result |
|---|---|---|
| Manager | Integration, production boundary, acceptance decisions and file ownership. Keep `Session` edits serialized under W1 until its lifecycle fix is integrated. | One frozen implementation/config revision with an honest lifecycle, economic and exchange verdict. |
| W1 — execution | Fix the Session reservation/fill/protection/exit lifecycle and its connection to the existing engine/risk contracts. | Normal stop, target and timed exit settle every child and release exposure without a helpful future price move. |
| W2 — measurement | Repair scoring, funding/day attribution, episode closure, state-based orphan detection and symbol-time accounting. Propose required Session logging changes to its owner. | Ledger, fills, daily accounting, exposure state and report reconcile on partial and funded cases. |
| W3 — data/runtime | Audit gap semantics and actual per-symbol eligibility; reproduce the five deadline failures on the intended OS and fix genuine containment gaps. | A bounded, usable research input with exact eligible intervals; verified process-tree shutdown or a BLOCKED result. |
| W4 — strategy research | Diagnose S1/S3 cost-rejected opportunities using corrected measurements and frozen hypotheses. | Measured executable net outcomes and a candidate decision; no threshold change justified only by fill count. |
| W5 — independent verification | Reproduce these findings before fixes; challenge final integrated lifecycle, metrics and exchange readiness. Own no production behavior under review. | Independent before/after evidence, including bad-input failures and a clear release veto for remaining defects. |

**5. First delivery: one correct trade lifecycle.** This takes priority over more strategy backtests. W1 must establish these invariants through Session, not just direct engine or RuntimeTrader unit tests:

1. Snap quantity to the actual venue step before approving/submitting, and recheck risk, margin and minimums after rounding. The approved request, executable request and fill ledger must have explicit, consistent meanings.
2. Convert the first nonzero entry fill to exposure exactly once. Duplicate or late fills must not double-book or free risk. IOC terminal cancellation retires its unfilled remainder; unknown outcomes retain the appropriate block.
3. Protect confirmed net exposure, account explicitly for entry quantity that can still fill, and resize coverage on additional fills. Do not require an already-cancelled remainder to remain protected. Do not fix quantity mismatch by weakening numerical tolerances or ignoring actual exposure.
4. Keep every child order tracked until its terminal state is confirmed. Replace/cancel protection without dropping IDs. A stop, target, timed exit or emergency close must settle siblings. Reduce-only exits must never open or reverse a position.
5. Make flattening idempotent with a tracked in-flight close; reconcile uncertain submissions before retrying. Stop repeated empty emergency loops. Release only after ledger, engine/venue positions, pending commands, child orders and risk state agree.
6. Prove the above with deterministic full and partial fills, cancelled remainder, delayed/duplicate reports, failed cancellation, a sibling race, stop/target/time exits and an interrupted restart. Keep prices inside the bracket in the orphan-cleanup case. State transition correctness must be asserted, not just equal final P&L between two runs.

Start with the supplied seven-second reproduction and existing fixtures. Each diagnostic or test job should take seconds to a few minutes. Reuse the standing regressions; add only tests that discriminate the failures above. No economic claim may rely on the old emergency-exit behavior.

**6. Second delivery: trustworthy measurements and an opportunity experiment.** W2/W3 can work while W1 repairs execution; economic replay acceptance waits for the integrated lifecycle fix.

W2 must distinguish open, partially closed and fully closed episodes. Include signed funding in consistent trade/account/daily views, define marked versus realized daily return explicitly, use Asia/Kolkata boundaries, preserve zero-trade days, and reconcile daily totals with account changes and cash flows. A missing or incomplete ledger must not turn into a valid flat result. Count `(strategy, symbol, second)` eligibility with instrument attribution; keep row counts separate. Read actual reservations, order states and protection checkpoints for orphan/quantity defects instead of searching only engine-journal wording. Treat the simple per-trade normal confidence interval as descriptive, not an independent-day promotion gate.

W3 must separate healthy no-trade intervals, missing trade IDs, disconnected transport, stale executable quotes, stale exchange marks and unsynced depth. Do not merge them into one generic gap reason. If a different bar representation is justified, label it as a changed data/strategy definition and validate it separately. Do not forward-fill missing observations as real trades. Keep raw provenance and causal timestamps. Mechanical warmup and market eligibility need separate clocks and counts.

W4 should first export every existing S1/S3 candidate's side, symbol, timestamp, entry band, stop/target, holding limit, projected reward and itemized estimated costs. Separate real account fees, spread, latency/slippage assumptions and signed funding; retain conservative unknowns. Estimated costs must not be booked twice when spread/slippage is already in execution prices.

Use development data to measure each candidate's executable outcomes over the intended 30–300 seconds. Respect the arrival book, IOC band, available liquidity, exit ordering and costs. Keep rejects and unfilled attempts in the opportunity analysis; call simulations of rejected candidates counterfactual diagnostics, never actual strategy trades. Mark insufficient-path cases unscorable instead of picking favorable intrabar ordering.

Register at most two concrete research hypotheses and a small fixed variant set before running comparisons. Select one candidate using development/validation only; compare with CASH and the unchanged baseline. Record all attempts and selection bias. Existing captures and previously inspected test periods are development knowledge. Reserve genuinely untouched, causally suitable data for one locked evaluation. Do not relabel a used period as fresh or use a one-minute mark archive as one-second execution evidence.

Report per candidate: complete eligible market/symbol time; unique setups; cost/risk pass counts; submissions, fills and closed episodes; gross and net expectancy; fees and funding; fill rate; adverse execution; holding times; daily marked and realized returns; drawdown; worst trade/day; concentration by symbol/regime; and uncertainty reflecting serial dependence. Include adverse cost/latency sensitivity. Keep the existing promotion floor of 100 closed out-of-sample positions across at least ten complete days, with its day-block uncertainty check, as a minimum screening condition—not a profitability guarantee. If qualifying data is absent, report DATA BLOCKED; do not simulate its existence or start prohibited long collection.

An experiment without a viable candidate ends with a rejected hypothesis and the measured reason. It does not end with live activation or a relaxed gate to meet the deadline.

**7. Third delivery: exchange mechanics, without claiming an edge.** Once the lifecycle fix passes, manager/W5 should prepare and, where credentials are securely available, execute one bounded demo drill. Keep keys local, outside messages, version control and logs. Public-data capture and local paper simulation do not require account credentials; do not block those on demo keys.

The drill must verify the selected account/position mode, venue filters, fee/margin inputs, protected entry, partial-fill handling where obtainable, acknowledged stop, exit/sibling cleanup, reconnect/recovery, duplicate reports and final balance/position reconciliation. Separate real demo observations from injected fault simulations. No-fill demo entry is an execution outcome, not proof of a round-trip. With no demo credentials, supply the runnable command and exact secure variable names and report BLOCKED.

Prepare any missing production adapter/CLI wiring behind its disabled boundary with mock and demo coverage. Do not equate changing `allow_live_submission` with readiness. A later owner-controlled real-capital pilot requires all technical and economic gates to pass and a separate concrete launch decision. No production orders, transfers, withdrawals, or modifications to unrelated positions are part of this assignment.

Binance documents that some 503 responses leave execution status unknown and require checking order/WebSocket status before retries. Implement and test that distinction, rather than retrying an assumed failed entry. Nautilus documents immediate execution/cancellation of IOC remainders and warns that order instruction support depends on the venue/adapter.

**8. Handoff format and completion.** Commit one concise report with the integrated SHA, configuration/data identities, before/after observations, bounded commands and three separate verdicts: lifecycle correctness, economic evidence, exchange operation. Preserve complete evidence in the repository or a durable indexed artifact location; `/tmp` alone is insufficient. Repair the literally truncated `reports/CORR_HANDOFF.md` and the obsolete aggregate reviewer command, which now raises a missing-symbol `TypeError`; do not present that original command as verified on this HEAD.

Accept completed work when the reproduced defects are fixed and the reports tell the truth. A no-go economic result can be a completed research assignment. Calling the bot ready for profitable real-capital trading requires evidence beyond completing this assignment. Do not promise a replacement launch date before these gates are met.

**Reproduction files supplied with this directive.** `Crypto_Bot_CORR_Independent_Probes.py` is an offline observer plus synthetic fixtures; `Crypto_Bot_CORR_Independent_Results.json` contains the captured results and verification limits. Run the probe from the repository root using the pinned project environment, inside `tools/run_budget.py` with a 300-second budget. Network calls are deliberately forbidden by the probe. Integrate its discriminating cases into the appropriate existing tests rather than making this review script a permanent application dependency.

**Source trail.** Repository paths at the reviewed SHA: `coord/outbox/W2-CORR.json`, `coord/outbox/W3-CORR.json`, `reports/CORR-PHASEB.md`, `reports/corr-evidence/phaseb/`, `docs/exchange-modes.md`, `src/cryptobot/app/session.py`, `src/cryptobot/risk/policy.py`, `src/cryptobot/research/scoring.py`, `src/cryptobot/research/funnel.py`, and `tests/unit/test_bench_restart_equivalence.py`.

Official mechanics references, checked 13 October 2026:

- https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/general-info
- https://nautilustrader.io/docs/latest/concepts/orders/
