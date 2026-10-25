# C2-FWD booking and scoring audit

Status: synthetic-fixture audit of the implementation originally on `live/hardening` at `8f0f106`, followed by code and policy clarifications in the R1 follow-up. No real forward ledger or holdout dataset was opened or scored. Fixtures are generated in memory or under pytest temporary storage. The frozen preregistration files were not edited.

## Disposition

### Booking integrity

1. **Signal lookahead and missing candles — fixed.** Signal eligibility uses only mark closes through the decision close. A newly listed symbol remains in the volume-ranked universe but cannot enter the signal until it has the required 36 daily closes spanning 35 completed intervals. Missing or invalid candles on/after its onboarding date refuse the row; expected pre-listing history is not treated as a data gap. Confirmed retirement is distinguished from an unresolved status or unexplained missing candle; terminal marking and the forced-exit cost are recorded explicitly.
2. **Point-in-time membership, volume and backfill — fail closed.** Weekly membership is selected from the saved contemporaneous exchange snapshot. Ranking requires complete volume candles from the symbol's onboard date through the decision day (with pre-listing calendar days contributing structural zero). Incomplete/stale snapshots and volume histories refuse booking. Backfills without the needed contemporaneous membership snapshot are refused; historical membership that was never recorded cannot be reconstructed from today's exchange metadata.
3. **Exactly-once writes — fixed.** Recording serializes writers, treats the ledger as authoritative after an append/state crash, validates consecutive unique days, atomically replaces ledger/state, and quarantines an incomplete final JSONL fragment before continuing.
4. **Funding — fixed.** Every expected settlement for each exposed symbol is required. The recorder uses that symbol's validated funding interval rather than assuming an 8-hour schedule; a missing event is not converted to zero. Funding is signed by position and applied once per exposed notional.
5. **UTC booking boundary — fixed.** Recording refuses before 00:05 UTC, on a nonmatching UTC date, and when exchange server time is stale or out of day. Unfinished candles are not used.

### Scoring integrity

6. **Ledger continuity and look gates — fixed.** Rows must be valid and consecutive; a look runs only at exactly 365/730/1095 rows, in sequence, and only once. Reports bind to the look index, exact row count, ledger-prefix hash and scoring parameters; a later look recomputes the prior primary verdict before proceeding.
7. **Numerical edge and stopping — fixed.** The p=1 case is represented safely in JSON. A terminal primary verdict prevents later looks; the secondary C2-VM test is exposed only after a primary pass. Look reports are atomically written. Frozen O'Brien-Fleming constants and the preregistered estimator are unchanged; bootstrap rounds and seed are recorded.

## Listing-age policy

The frozen preregistration defines the weekly universe as all TRADING USD-M USDT perpetuals ranked by trailing 30-day quote volume; it does not state a listing-age exclusion. D-062 therefore removes the implementation's extra 35-day cutoff rather than changing the study universe. Pre-listing days in a trailing volume window contribute zero because the instrument did not yet exist; every daily volume candle from onboarding onward must be complete. A young instrument remains a top-30 candidate if its measured volume ranks there, but is signal-ineligible until 36 mark closes exist. This resolves the implementation policy without amending the frozen preregistration.

## Independent-review corrections

The final review identified two remaining code issues: a 35-day listing-age filter that changed the preregistered candidate universe, and a funding wrapper that hardcoded 8-hour settlements even though the fetcher accepts other day-dividing intervals. Regression tests for both plus onboarding-aware volume history were run against the pre-fix code and failed (**3 failed**); after the fixes they pass (**3 passed**). The full focused set `tests/unit/test_forward_c2.py tests/unit/test_forward_c2_audit.py tests/unit/test_c_family_score_rounds.py` passes (**40 passed**).

The earlier audit text claimed 14 deliberate guard-deletion mutations were killed, but no corresponding mutation harness or per-mutation evidence was checked in. That claim is withdrawn; the tests are regression tests, and the three review corrections above have explicit before/after results. `ruff check src tests` and `git diff --check` are the repository checks for this follow-up; CI supplies the full suite.

## Remaining limits

No live exchange response, Mac launchd invocation, production forward ledger, credential, order path, or holdout return file was accessed. Historical membership snapshots never captured during an outage cannot be recreated; the recorder refuses to fabricate them. The gate remains **NO-GO** pending eligible forward evidence and owner review.
