# DEEP-W1-D2 findings (filed precisely)

Scope rule: own W2 resume-path session fixes in Row-6 scope, else file
precisely. One fix owned (F1); four filed (F2–F5).

## F1 — FIXED: lookup-recovered exposure booked foreign, never flattened

- Trigger: entry submit raises `UnknownOutcomeError` (timeout/503) AFTER
  the venue filled it; the loop dies loudly (correct); on resume,
  `engine.recover` looks up the journaled cid and adopts the fill.
- Defect: `_fill_reservation` could not attribute the adopted cid — the
  open submit command has no `engine_client_id` (submit never returned)
  and no position shell exists (admit never ran). The fill booked
  FOREIGN (`fill-unbooked` + `unknown-fill` block), the ledger stayed
  flat, no flatten fired, and the loop reported flat while the venue
  held real exposure. Fail-open.
- Fix (this branch): engine seam `journal_reservation(cid)` (durable
  journal read, mirrors `_venue_side_of`) + capability-guarded fallback
  in `_fill_reservation`. The open command's reservation (in
  `_known_reservations`) gates attribution — foreign fills still return
  None (row 13 proves it).
- After fix: adopted fill books, resume flattens the orphan, flat, no
  entry re-submit. The submit command stays `unknown` and entries stay
  blocked (fail-closed; see F4 for the missing operator clear).
- Pinned by: `test_row04_ambiguous_submit` (phase B), which fails
  without the fix (no booking, no flatten, false flat).

## F2 — FILED: `health:stale-mark` is a one-way latch (no release path)

- Observed: `_halt_entries("health:stale-mark")` latches permanently;
  nothing releases it when marks go fresh again (`_release_all_exit_only`
  only runs on emergency-recovered / day-reconciled). Any second admit
  in the same run is then refused at submit (`execution:submit-rejected:
  ValueError`, engine exit-only mirror).
- Matrix artifact that exposes it: the rig's 12-event warmup burst
  occupies 12 control ticks (1 event/tick), so queued trickle events
  arrive 2–3s stale and trip the 1s `max_mark_age_ms` bound ~t=3 in
  EVERY matrix run. Single-admit rows never notice (admit precedes the
  trip; exits/supervision proceed under exit-only).
- Production relevance: a real venue burst would trip this identically
  (faithful fail-closed), and it would stick for the run. Whether the
  latch should be level-triggered (release when fresh) or operator-
  cleared is a safety-semantics decision — not taken here.
- Coping (documented in code): multi-admit row 5 widens the bound
  (`max_mark_age_ms=30000` + `cooldown_s=3`); the mechanics under test
  never stall marks anywhere near it, so the check stays live.
- Repro: any matrix row with a second admit and default bounds
  (row 5 pre-override: gate-3 shot refused; spy on
  `policy.check_health` shows trips from t≈3).

## F3 — FILED: exit-tick closes never book (threaded shutdown-drain gap)

- Observed: fills pushed to the user-stream socket on the exit tick
  (operator-stop flatten, duration-end flatten) are never booked: the
  run loop breaks before the next owner drain, the shutdown sweep calls
  `_drain_engine` (engine queue) but never `drain_owner` (socket
  handoff), and `UserStreamAttachment.close()` stops the pump without
  draining handoff.
- Safety: the venue HOLDS the close (reduce-only submit succeeded), so
  exposure is flat at the venue; only the ledger/report lags (stale
  open). Resume adopts the close fill via lookup (rows 4/11 prove it).
- Candidate fix (not taken — shutdown-path change, needs manager
  review): bounded `drain_owner` sweep after the loop breaks, before
  `close_streams`.
- Pinned behavior: `test_row11_operator_stop` phase A asserts the
  honest open (close submitted, fill stranded, flag sticky); phase B
  asserts resume adopts the close to flat with no re-submit.

## F4 — FILED: `unknown` submit commands have no operator clear path

- Observed: after an ambiguous submit + resume, the entry command sits
  at status `unknown` forever (no engine id is ever recorded), and
  `_admission_hold` blocks entries (`reconcile:unknown-commands`,
  `resume-blocked` checkpoint). Safe direction, but the run can never
  admit again and no operator action clears it (`clear_stop` covers
  stops, not unknowns).
- Needs: an operator resolve/void action for proven-unknown commands
  (W2/CLI scope).

## F5 — OBSERVED: exits proceed under every halt (no finding)

- Rows 5/7/10/12 show supervision, time exits, stop actions, and
  flatten retries submitting normally while entry halts stand
  (stream gap, booking block, health mark, emergency). No inversion
  found: halts gate entries only.
