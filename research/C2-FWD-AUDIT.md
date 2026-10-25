# C2-FWD booking and scoring audit

Status: independent synthetic-fixture audit of the implementation on `live/hardening` at `8f0f106`. No real forward ledger or holdout dataset was opened or scored. The fixtures in `tests/unit/test_forward_c2_audit.py` are generated in memory/on pytest temporary storage. Frozen preregistration files were not changed.

## Findings

### (i) Can corrupt forward records — fix before another booking

1. **Partial/stale mark data can become a valid-looking zero row; signal eligibility also looks ahead.** `book_day()` relies on `c_family._eligible()`, which requires the next day's close to choose the current signal universe. That uses data unavailable at decision time and excludes a symbol if it delists or has a missing candle tomorrow. If a response omits enough closes, eligibility becomes empty and the recorder still returns/appends a zero-weight row instead of refusing the partial response. Separate signal eligibility (data through the decision close) from post-decision return marking, validate fresh candle coverage, and fail closed when the response is incomplete. A missing next close needs an explicit delisting/halt policy; zero return is not evidence of the actual last tradable price.

2. **Universe fetch failures are silently converted into a smaller universe.** `_universe()` catches every exception from `quote_volume_30d()` and continues. One transient timeout/rate limit can omit a candidate from the Monday ranking for the whole week; if every lookup fails, it returns an empty universe and can still produce a row. Fail the booking on lookup errors or incomplete 30-day volume windows; do not cache a partial ranking.

3. **Append/state crash window breaks exactly-once booking.** `record()` appends a row before atomically replacing `state.json`. A crash between those operations leaves the ledger ahead of state; the next run can append the same day again. A short write can leave a malformed tail that poisons later reads/appends. There is no writer lock. Reconcile state from the complete ledger tail, validate consecutive unique dates before score/append, serialize writers, and repair/quarantine a torn final line before appending.

4. **Missing funding is silently assumed to be zero.** `book_day()` calls `funding[s].get(nxt, 0.0)`, so an empty/partial funding response overstates net returns without refusing the row. The sign in the existing formula is otherwise correct (positive funding is paid by longs, received by shorts); rates are summed by UTC day and applied once per held notional.

5. **Current exchange metadata cannot reconstruct historical point-in-time membership after an outage.** Monday selection uses the *current* `exchangeInfo` TRADING symbols even while backfilling an older `t_day`; delisted contracts have disappeared from that list. The code has no dated symbol/volume snapshot, so a catch-up can silently exclude historical constituents and is not the preregistered point-in-time universe. The current public endpoint does not supply historical `exchangeInfo`. Store contemporaneous snapshots for future dates and refuse, rather than invent, a missed day's ranking when its snapshot is unavailable; recovering already-missed membership needs a separately approved public historical source or an explicit preregistration amendment. The real symbol history was not fetched for this audit.

6. **Listing-age/volume-window policy is under-specified in implementation.** `quote_volume_30d()` sums whatever klines arrive, without requiring a complete 30-day window; `_eligible()` later requires 35 days of marks, so young listings can consume top-30 slots without being tradeable. The preregistration does not specify a separate listing-age exclusion. Clarify this before scoring; do not silently add a new historical filter after the study starts.

### (ii) Scoring-only — fix before the first look

7. **Row count is the only integrity gate.** `score_look()` slices the first 365/730/1095 rows and checks length, but does not reject duplicates, gaps, invalid dates, or missing/non-finite return fields. A corrupted ledger can therefore be scored as if it contained consecutive daily observations.

8. **A valid all-negative bootstrap can crash.** `c_family.score()` uses add-one smoothing, so `p_value == 1` is possible; `NormalDist().inv_cdf(1 - p_value)` then raises because the argument is zero. A synthetic negative ledger reproduced this `StatisticsError`.

9. **The 2,000-resample p-value is too coarse near the first bound.** Its minimum is `1/2001`; at the first OBF bound 2.973, the crossing threshold is about p=0.00148, so only 0 or 1 non-positive bootstrap means can cross. At a true tail probability near that threshold, 2,000 Monte Carlo draws make the decision highly seed/round-count sensitive. Keep a fixed seed and preregistered week-block estimator, but increase and record the bootstrap round count before the first look.

10. **The implementation does not fully enforce the stopping/secondary-gate language.** A `FORWARD-PASS` at an early look does not prevent later looks. The amendment says C2-VM is tested at the same boundary only after C2 passes, but the code instead publishes VM descriptive statistics at every look and never computes its gated boundary test. Do not expose secondary statistics before primary passage; implement the stated fixed-sequence test or clarify its exact pass rule in a future amendment before looking.

11. **Look report writes are not atomic.** A process crash during `write_text()` can leave a partial report that blocks the once-only rerun. Use an exclusive atomic report creation so a look is either fully written or absent.

### (iii) Documentation / preregistration clarification

12. **Gross field label is ambiguous.** The row's `gross_bps` value is `price return - funding`; it is net of funding, although it is later reported as gross. Net and adverse cost calculations use funding once and cost once per unit of leg notional; the field name/report should be clarified without rewriting the frozen preregistration or silently changing historical row semantics.

13. **OBF constants are valid but not the exact numerical solution.** Independent Gaussian-increment integration of the amendment's equally spaced, one-sided Brownian crossing rule gives approximately `(2.962, 2.094, 1.710)`; the frozen `(2.973, 2.102, 1.717)` spends approximately 0.0491 familywise alpha and is slightly conservative. The implementation applies the frozen values exactly. Do not change them post-preregistration.

## Scope and verification boundary

The daily command is explicitly `record`; statistical scoring requires the separate `score --look K` command and a due row count, so the ordinary record path does not invoke scoring. Synthetic tests exercise only this code path. No public market endpoint, private endpoint, Mac worktree, real C2-FWD ledger, API credential, order path, or holdout return file was accessed. The future point-in-time universe reconstruction and the actual production launchd invocation remain unverified.
