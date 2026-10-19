# F2 stale-mark latch — fix specification (input to W1; no code here)

Owner for implementation: W1 (D2 lifecycle ownership, per deep board).
This file is a **specification only**. No `src/` changes are made by it,
and none should be inferred from it without W1 design + review.

## 1. Defect (mechanism, fully evidenced on main-line code)

Transient freshness blocks latch into persistent exit-only with no
per-tick recovery:

1. `risk/policy.py:218-222` — `monitor_tick` with an account returns
   `HealthStatus(False, (mark_block,))` immediately when
   `_check_mark_age` (`policy.py:490-499`) yields `health:stale-mark`
   or `health:mark-age-unknown`.
2. `check_health` (`policy.py:178-180`) is `monitor_tick` with account,
   so it carries the same block.
3. `app/session.py:2757-2760` (replay bar-close) and `:3546-3549`
   (live supervision) call `_halt_entries(";".join(reasons))` whenever
   health/tick is not ok — including for transient freshness reasons.
4. Release paths: `_release_exit_only(reason)` (`session.py:1494`) has
   **zero production callers** (only
   `tests/unit/test_rev2_stream_ownership.py:644` drives it);
   `_release_all_exit_only` runs only at emergency-recovered
   (`session.py:2838`) and day-reconciled (`session.py:3051`).

Observed effect (deep board, round-1 mechanism section): on quiet
window opens the mark age exceeds the bound ~t+5s, exit-only latches,
and never releases — S1-val logged 6084 gate trips and all 5 submits
`status=failed` (`execution:submit-rejected` under exit-only). X1 cells
with zero intents are unaffected (UNTESTED, not blocked); any future
family that admits intents hits this wall.

Note what is NOT broken: only `halt:`-prefixed risk reasons latch via
the admission path (`session.py:919-921`); `health:*` admission rejects
correctly do not latch there. The latch enters through the supervision
paths (items 3–4). Fail-closed-while-stale is correct and must stay.

## 2. Required behavior

Level-triggered exit-only for transient health reasons:

- **R1.** Transient session reasons (freshness family: `health:stale-mark`,
  `health:mark-age-unknown`, `gate:stale-quote`, `gate:stale-mark`,
  `gate:*-age-unknown`, `stream:*` stall class) are **re-evaluated every
  supervision tick**: release the reason when its condition clears, then
  re-assert exactly the reasons that still hold.
- **R2.** Persistent reasons keep latch semantics: `halt:*`, `pause:*`,
  `funding-mismatch`, `reconcile:unknown-*`, operator stops. Recovery
  only through existing recovery points (reconcile/emergency flow).
- **R3.** Fail-closed preserved: while any reason holds, entries stay
  blocked; exits and exposure reduction proceed (exit-only, not freeze).
- **R4.** No new silence: every engage AND release writes the existing
  `risk.jsonl` / checkpoint trail with `from_state`/`to_state`/reason,
  so latch history is auditable (engaged_at, released_at, cause).
- **R5.** Restart safety: transient reasons never persist as latched
  across restart; recovery re-derives them from live observations
  (consistent with `_release_all_exit_only`'s documented
  "level-evaluated reasons re-assert on their next tick if still true",
  `session.py:1504-1505` — this fix implements the release half of
  that contract).

## 3. Acceptance (W1 to encode as tests)

- **A1.** Replay the S1-val window shape (quiet open, marks flowing
  later): submits after freshness recovery are no longer refused under
  exit-only; the `health:stale-mark` reason shows engage → release in
  the trail.
- **A2.** Stale seconds still produce **zero fills**: entries attempted
  while stale are blocked with reason (blocked, not filled — fail-closed
  proof, not just latch proof).
- **A3.** Persistent reasons unaffected: `halt:emergency`,
  `pause:daily-target`, `funding-mismatch` still latch until their
  recovery points (existing tests keep passing unmodified in behavior).
- **A4.** Lifecycle matrix gains rows: transient-trip-and-recover,
  flap (trip/release/trip), restart-with-transient-reason (re-derived,
  not restored-latached).
- **A5.** Full suite green; no change to bounds (`quote_max_age_s`,
  `max_mark_age_ms` values untouched), no risk-math change, no live-path
  behavior change beyond the specified release semantics.

## 4. Non-goals

- No bound tuning (freshness thresholds are policy, frozen).
- No risk-sizing/ledger changes.
- No live-adapter work (Z2-live stays a separate track: testnet
  re-record, slippage model, tiered margin).
- No strategy changes (Z3 untouched).

## 5. Handoff

W1: design the implementation (suggested shape: partition session
reasons into transient vs persistent sets; supervision tick performs
release-then-assert for the transient set only), encode A1–A5, run the
matrix + full suite. Manager/W5 review before integration, per the
standing risk-code rule.
