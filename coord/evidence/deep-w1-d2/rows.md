# DEEP-W1-D2 lifecycle matrix — per-row evidence

Harness: `tests/unit/test_lifecycle_matrix.py` — every row drives the
NORMAL `Session.run_live` loop (default threading, pinned
`control_tick_s=0.25` / `feed_queue_max=1000`), a real
`RunStore(tmp_path)`, and a live demo `BinanceLiveEngine` on a scripted
offline transport (strict order-flow scripts + canned polls + venue-
truth tape echo). Only strategy intent is stubbed.

Result: 14 passed (13 rows + 06b) in ~189s, 3 consecutive full-file runs
(stability section below).

| Row | Test | Scenario | Key proof |
|-----|------|----------|-----------|
| 01 | test_row01_happy_path | admit→fill→protect→time-exit→flat | exact submits [LIMIT, MARKET]; flat; verified; legs cancelled; clean |
| 02 | test_row02_duplicate_stream_events | each fill redelivered twice | fills.jsonl exactly 2 rows; exec-id dedup; flat; clean |
| 03 | test_row03_delayed_ack | entry fill 3s after submit | ≥2.5s gap stamped; no dup submit; flat; clean |
| 04 | test_row04_ambiguous_submit | 503 submit→loud death→resume adopt | UnknownOutcomeError out; key closed; no admit/shell; resume books+flattens; never re-submits; entries blocked (F1 fix) |
| 05 | test_row05_disconnect | socket death mid-run, redial | stream: rejects in dead window; same-key redial; post-heal admit; 2× flat (cooldown 3s + mark 30s documented) |
| 06 | test_row06_restart_with_exposure | crash, resume, stream fill | post-restart fill books; protects; flat; shell-restored |
| 06b | test_row06b_booked_exposure_flatten | crash with booked exposure | retry close reservation-attributed; flat |
| 07 | test_row07_booking_failure | malformed close fee (-1) | booking-rejected + block; poisoned cid absent from fills; time-exit re-fires; second close books; flat |
| 08 | test_row08_queue_pressure | 20000-event burst | drops >1000 counted; keeps ticking; zero submits (READ_TAIL positional) |
| 09 | test_row09_stale_data | 60s-stale marks | admitted 0; stale reject; zero submits; clean end |
| 10 | test_row10_halt_independence | socket death with position open | close submitted DURING outage (stamped before heal swap); reconnect lookup adopts; flat |
| 11 | test_row11_operator_stop | flatten-stop via own store handle | early exit (≪20s); sticky flag; close submitted, fill stranded (honest open); clear_stop+resume adopts; no re-submit; full duration (F3) |
| 12 | test_row12_emergency_flatten | poked emergency latch (doc'd white-box) | stop-action flatten; operator-alert; flat; latch cleared on reconciled flat |
| 13 | test_row13_foreign_positions | fill for never-submitted id | fill-unbooked + block; nothing booked; zero submits; gated shot rejected booking:unknown-fill |

## Stability

Three consecutive full-file runs, same checkout, no retries:

- run 1: 14 passed in 188.96s
- run 2: 14 passed in 188.13s
- run 3: 14 passed in 189.20s

## Suite

- `tests/unit`: 1071 passed, 1 skipped in 469s (incl. 14 matrix).
- Rest (`tests --ignore=tests/unit`): 261 passed in 100s.
- Both under `tools/run_budget.py --budget-s 1500` (see done.json
  commands + report artifacts). Note: this branch predates the D1
  preflight merge, so its `run_budget.py` CLI has no
  `--allow-best-effort` flag; the filed commands match this branch.

## Source changes on this branch

- `src/cryptobot/app/session.py`: position.json shell
  (`_save_position_shell`/`_restore_position_shell`, persisted on
  admit/ensure/flatten/beat, restored in `_resume_live` before
  flatten); orphan-close nonzero-booked fallback; submit-command
  durable fallback + journal-reservation fallback in
  `_fill_reservation` (F1).
- `src/cryptobot/adapters/binance_live.py`: `journal_reservation`
  seam (F1).
- `src/cryptobot/app/store.py`: `clear_stop` operator action.
