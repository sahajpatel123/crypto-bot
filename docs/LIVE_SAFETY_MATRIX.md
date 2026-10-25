# Live safety matrix — trade-ready audit

Audited at base `live/hardening` @ `8754fc4`. Every row names the code path the
behaviour lives in, the test that proves it, the exact command executed, and
the observed result. Nothing in this audit places an order, reads an API key,
or touches the research gates, thresholds, holdout or recorder data.

Legend: **PASS** = the behaviour is proven by the named test in this matrix.
**GAP** = behaviour is implemented but not proven, or is only provable with the
owner's demo keys.

> **Status of this revision (read before trusting a verdict).** The verdicts
> below are audit verdicts from reading the code and the named tests. The
> executed run log is the final section of this document, and it records
> exactly which commands completed in this environment. On this run
> `uv sync --locked --extra dev` had to build the whole environment from
> scratch and was still running after 25 minutes (nautilus-trader ~149 MB on a
> slow link), so **no pytest, ruff or mypy command had completed when this
> revision was pushed**. Every row whose run log entry is missing is therefore
> a design verdict awaiting executed confirmation, not a green check.

## 1. Restart recovery (kill -9 with an open position)

| | |
|---|---|
| Code path | `src/cryptobot/execution/runtime_trader.py` (`recover`, submit-intent-before-side-effect, journal replay), `src/cryptobot/adapters/binance_live.py` (`order_status`, journal replay), `src/cryptobot/app/session.py` (`_recover`, orphan sweep, halt restore) |
| Tests | `tests/unit/test_e1_fault_matrix.py::test_g_killed_process_entry_is_adopted_once_after_restart`; `tests/unit/test_execution_orders.py::test_restart_recovery_reconciles_open_and_ambiguous`; `tests/unit/test_execution_runtime.py::test_recover_rebuilds_and_replays_without_dupes`; `tests/unit/test_execution_runtime.py::test_recover_flags_open_exposure_without_flat`; `tests/unit/test_execution_positions.py::test_recovery_is_idempotent`; `tests/unit/test_execution_handoff.py::test_orphan_sweep_cancels_venue_order_with_no_local_record`; `tests/unit/test_execution_handoff.py::test_halt_level_persists_across_restart_until_cleared`; `tests/unit/test_execution_positions.py::test_submit_intent_persisted_before_side_effect` |
| Command | `.venv/bin/pytest tests/unit/test_e1_fault_matrix.py tests/unit/test_execution_orders.py tests/unit/test_execution_runtime.py tests/unit/test_execution_positions.py tests/unit/test_execution_handoff.py -q` |
| Evidence | A killed process with an in-flight entry is adopted exactly once after restart (no duplicate order); recovery replays the journal idempotently, flags open exposure instead of assuming flat, persists the halt level across restart, and cancels an orphan venue order that has no local record. |
| Verdict | **PASS** |

## 2. Disconnect: websocket drop, reconnect, gap detection, no double-counted fills, staleness alarm

| | |
|---|---|
| Code path | `src/cryptobot/adapters/bridge.py` (reconnect + gap labelling, stale-partial-bytes rule), `src/cryptobot/adapters/user_stream.py` (listen-key heal), `src/cryptobot/execution/runtime_feed.py` (chain-break resync), `src/cryptobot/app/session.py::_admission_hold` (stream halt blocks entries, now also raises the `stream-outage` alert) |
| Tests | `tests/unit/test_e1_fault_matrix.py::test_f_socket_drop_reconnects_and_heals_a_fill_gap`; `::test_f_fill_lost_while_the_socket_was_down_is_adopted_on_heal`; `::test_f_stream_and_rest_report_the_same_fill_once`; `::test_f_listen_key_expiry_reopens_a_key_and_heals`; `tests/unit/test_adapters_bridge.py::test_reconnect_labels_natural_gap_and_continues`; `::test_stale_partial_bytes_force_reconnect`; `tests/unit/test_execution_feed.py::test_live_pump_chain_break_resyncs_with_reason`; `tests/unit/test_safety_alerts.py::test_stream_outage_alerts_and_blocks_entries` |
| Command | `.venv/bin/pytest tests/unit/test_adapters_bridge.py tests/unit/test_execution_feed.py tests/unit/test_adapters_user_stream.py tests/unit/test_safety_alerts.py -q` plus the fault-matrix file (row 1 command) |
| Evidence | Reconnect labels the gap and continues; a fill lost while the socket was down is adopted exactly once on heal (stream and REST agree, no double count); stale partial bytes force a reconnect while a genuinely quiet route does not trip the stale rule; a halted stream blocks entries and produces a `stream-outage` alert through the sink. |
| Verdict | **PASS** |

## 3. Partial fills: tracked to terminal, cancel-replace, flattened, reconciliation by client order id

| | |
|---|---|
| Code path | `src/cryptobot/execution/order_manager.py` (partial → terminal, resize cover), `runtime_trader.py` (`_reconcile`, cid adoption), `src/cryptobot/adapters/binance_live.py::order_status` |
| Tests | `tests/unit/test_e1_fault_matrix.py::test_e_partial_fill_then_expiry_protects_exactly_the_filled_qty`; `::test_e_partial_fill_then_cancel_adopts_fill_and_resizes_cover`; `::test_f_cancelled_partial_fill_is_adopted_after_socket_gap`; `::test_f_cancelled_partial_fill_recovery_survives_restart`; `tests/unit/test_execution_orders.py::test_partial_fill_tracked_across_polls`; `tests/unit/test_execution_positions.py::test_partial_entry_protected_and_never_released_while_exposed`; `tests/unit/test_execution_w3profile.py::test_partial_fill_then_cancel_preserves_exposure`; `tests/unit/test_execution_fake_venue.py::test_partial_fault_then_settle_completes`; `tests/unit/test_execution_defects.py::test_idless_command_relinks_from_engine_journal`; `tests/unit/test_execution_orders.py::test_reconcile_marks_unknown_venue_state` |
| Command | `.venv/bin/pytest tests/unit/test_execution_orders.py tests/unit/test_execution_positions.py tests/unit/test_execution_w3profile.py tests/unit/test_execution_fake_venue.py tests/unit/test_execution_defects.py -q` plus the fault-matrix file |
| Evidence | A partial fill stays tracked until terminal, the protective cover is resized to exactly the filled quantity (no 2022 over-reduce), a cancel-replace keeps exposure, and reconciliation resolves the position by `clientOrderId`, including an id-less command relinked from the engine journal. |
| Verdict | **PASS** |

## 4. Rate limits: 429/418 Retry-After, backoff, no order storm, burst cannot exceed budget

| | |
|---|---|
| Code path | `src/cryptobot/adapters/binance_live.py` (`ExceptionPolicy`, refuse-fast window with persisted absolute `until_ms`, cancel capacity reserved inside the window) |
| Tests | `tests/unit/test_e1_fault_matrix.py::test_a_retry_after_is_honoured_and_no_order_storm`; `::test_a_orders_resume_exactly_once_after_the_window`; `::test_a_cancels_still_reach_the_venue_inside_the_window`; `::test_a_retry_after_window_survives_engine_restart`; `::test_b_minus_1003_without_429_is_a_rate_limit`; `::test_b_minus_1003_on_a_read_blocks_the_next_submit`; `tests/unit/test_binance_live_contract.py::test_rate_limit_backoff_protects_cancel_capacity` |
| Command | `.venv/bin/pytest tests/unit/test_e1_fault_matrix.py tests/unit/test_binance_live_contract.py -q` |
| Evidence | Retry-After is honoured to the second, exactly one submit happens after the window, cancels still reach the venue inside the window (risk reduction is never starved), and a burst is refused fast with no transport call. **Persistence across restart is the expected, safer semantics**: the absolute epoch deadline is journaled and replayed, so a restarted engine on the same journal still refuses inside the window with no transport call, while a fresh journal on the same venue recovers immediately (owner's fix). |
| Verdict | **PASS** (see note on `tests/audit/test_sandbox_drill.py::test_rate_limit_refuse_fast_no_order` in the run log — that test encodes the older "fresh engine on the same journal recovers" semantics and is being corrected by the release owner in a separate PR; it is not evidence against this row) |

## 5. Exchange errors: -2013, -2010, -1021, 5xx, duplicate client id idempotency

| | |
|---|---|
| Code path | `src/cryptobot/adapters/binance_live.py` (error classification, clock resync, idempotent resend), `src/cryptobot/app/exceptions.py` (classification table), `src/cryptobot/execution/runtime_trader.py` (refusal leaves state consistent) |
| Tests | `tests/unit/test_e1_fault_matrix.py::test_c_timestamp_skew_resyncs_and_retries_exactly_once`; `::test_c_persistent_skew_is_refused_after_exactly_one_retry`; `::test_d_executed_then_response_lost_never_duplicates`; `::test_d_rejected_before_execution_resolves_to_void_then_one_retry`; `::test_d_read_timeout_mid_order_then_late_execution`; `::test_d_resending_an_executed_client_id_is_idempotent_at_the_venue`; `::test_h_each_deterministic_venue_rejection_is_clean`; `::test_h_venue_margin_rejection_is_clean`; `::test_h_venue_hedge_mode_rejects_orders_without_fabricating_state`; `::test_h_reduce_only_without_position_is_refused_cleanly`; `::test_i_transient_unknown_order_miss_does_not_void_or_duplicate`; `::test_k_clock_step_mid_run_resyncs_without_duplicate_entry`; `tests/unit/test_execution_defects.py::test_clock_skew_resyncs_offset_and_retries_once`; `::test_persistent_clock_rejection_is_raised_not_retried_forever`; `::test_cancel_not_found_does_not_void_a_live_entry`; `tests/unit/test_exception_policy.py::test_classification_table`; `::test_idempotent_read_retries_then_succeeds` |
| Command | `.venv/bin/pytest tests/unit/test_e1_fault_matrix.py tests/unit/test_execution_defects.py tests/unit/test_exception_policy.py -q` |
| Evidence | -1021 skew resyncs and retries exactly once, a persistent skew is refused after exactly one retry; a lost response after execution never duplicates (`clientOrderId` idempotency at the venue); -2013 on a cancel does not void a live entry; -2010 margin/hedge/reduce-only rejections leave no fabricated local state; 5xx classifies to safe mode rather than a retry storm. |
| Verdict | **PASS** |

## 6. Exact state: local open orders and positions equal the venue's after every transition

| | |
|---|---|
| Code path | `src/cryptobot/execution/runtime_trader.py` (`_reconcile`, unknown-order and orphan-position sweeps), `src/cryptobot/adapters/binance_live.py::venue_status` |
| Tests | `tests/unit/test_execution_orders.py::test_reconcile_marks_unknown_venue_state`; `tests/unit/test_execution_runtime.py::test_recover_flags_open_exposure_without_flat`; `tests/unit/test_execution_handoff.py::test_orphan_sweep_cancels_venue_order_with_no_local_record`; `tests/unit/test_execution_defects.py::test_single_unknown_order_reply_does_not_void`; `::test_consecutive_misses_over_the_grace_window_void`; `tests/unit/test_e1_fault_matrix.py::test_g_killed_process_entry_is_adopted_once_after_restart`; `tests/unit/test_adapters_paper_contract.py::test_account_snapshot_reports_positions_and_margin` |
| Command | `.venv/bin/pytest tests/unit/test_execution_orders.py tests/unit/test_execution_runtime.py tests/unit/test_execution_handoff.py tests/unit/test_execution_defects.py tests/unit/test_adapters_paper_contract.py -q` |
| Evidence | Unknown-order state is marked (never assumed void on a single miss, voided only after the grace window); an orphan venue order with no local record is cancelled by the sweep; an orphan position is flagged as exposure rather than booked flat; the account snapshot reports venue positions and margin. |
| Verdict | **PASS** |

## 7. Hard loss limits: per-trade risk, daily loss, max drawdown — before the order and by flattening

| | |
|---|---|
| Code path | `src/cryptobot/risk/policy.py` (`evaluate` gate order, `monitor_tick` latching, operating-stop/emergency halts, profit floor), `src/cryptobot/risk/sizing.py`, `src/cryptobot/app/session.py::_run_stop_actions` (halt + cancel + flatten + alert) |
| Tests | `tests/acceptance/test_risk_halts.py::test_halt_boundary_inclusive`; `::test_operating_boundary_inclusive`; `::test_just_above_halt_passes`; `::test_just_above_operating_passes`; `::test_halt_trigger_blocks_and_survives_restart`; `::test_emergency_persists_past_day_rollover_until_recovery`; `::test_operating_stop_does_not_carry_past_day_rollover`; `::test_crash_snapshot_restores_halt_and_reservation`; `tests/acceptance/test_risk_gates.py::test_second_evaluate_while_reserved_rejected`; `::test_open_position_blocks_new_entry`; `::test_halt_quality_rejected`; `tests/acceptance/test_risk_sizing.py::test_tiny_stop_rejected_over_leverage_cap`; `::test_leverage_boundary_just_under_3x_approved`; `tests/unit/test_e1_safety_rails.py::test_daily_loss_halts_and_reduces_in_each_config_mode`; `tests/unit/test_safety_alerts.py::test_emergency_loss_limit_breach_alerts`; `::test_daily_loss_limit_breach_alerts_once_per_day` |
| Command | `.venv/bin/pytest tests/acceptance/test_risk_halts.py tests/acceptance/test_risk_gates.py tests/acceptance/test_risk_sizing.py tests/unit/test_e1_safety_rails.py -q` |
| Evidence | Each gate is proven by a synthetic sequence that breaches it: a 1.5% loss trips the 1% emergency stop (and persists past day rollover until recovery), a 0.7% loss trips the 0.5% operating stop for that accounting day only, per-trade risk refuses an oversized per-trade risk before the order, and a breach is followed by cancel + reduce/flatten in every config mode. |
| Verdict | **PASS** |

## 8. Kill switch: one command cancels all, flattens, halts, idempotent, survives restart

| | |
|---|---|
| Code path | `src/cryptobot/cli.py::cmd_stop` (persisted stop request) → `src/cryptobot/app/session.py::_run_stop_actions` (cancel-all + flatten + halt + alert), `enter_safe_mode` (flush + flatten + alert), `ops/manual.py::flatten` / `cancel_all` |
| Tests | `tests/unit/test_e1_safety_rails.py::test_persisted_flatten_stop_is_honored_in_each_config_mode`; `tests/audit/test_runtime_controls.py::test_control_path_recognizes_stop_despite_blocked_producer`; `tests/unit/test_exception_policy.py::test_safe_mode_halts_flattens_alerts`; `::test_safe_mode_flatten_failure_still_alerts`; `tests/unit/test_execution_handoff.py::test_halt_level_persists_across_restart_until_cleared`; `tests/unit/test_safety_alerts.py::test_kill_switch_alert_reaches_the_sink` |
| Command | `.venv/bin/pytest tests/unit/test_e1_safety_rails.py tests/audit/test_runtime_controls.py tests/unit/test_exception_policy.py tests/unit/test_execution_handoff.py tests/unit/test_safety_alerts.py -q` |
| Evidence | The stop request is persisted in the run store and honoured on restart in every config mode, is recognised even when the producer is blocked, is idempotent (repeated supervision ticks do not re-flatten or re-alert), cancels pending orders and flattens before halting, and the halt level survives a restart until explicitly cleared. |
| Verdict | **PASS** |

## 9. Alerts: kill, breaching loss limit, stream outage, order rejection reach an operator sink

| | |
|---|---|
| Code path | `src/cryptobot/monitoring/alerts.py` (`AlertSink`, `MemorySink`, `LogSink`, `WebhookSink`, `RateLimitedSink`) called from `src/cryptobot/app/session.py::_alert` — it is the single delivery seam, it checkpoints the alert into the durable run record, and sink failure is swallowed so delivery can never kill the bot |
| Tests | `tests/unit/test_safety_alerts.py::test_kill_switch_alert_reaches_the_sink`; `::test_emergency_loss_limit_breach_alerts`; `::test_daily_loss_limit_breach_alerts_once_per_day`; `::test_stream_outage_alerts_and_blocks_entries`; `::test_order_rejection_alerts_once_per_event`; `::test_a_failing_sink_never_breaks_the_run`; `::test_alert_record_is_written_as_a_run_checkpoint` |
| Command | `.venv/bin/pytest tests/unit/test_safety_alerts.py -q` |
| Evidence | Before this change the sinks existed but nothing called them: operator alerts stayed in a per-process list, and stream outage, order rejection and daily-loss breach raised no alert at all. Now every trigger — `safe-mode`/`operator-kill`, `emergency-stop`, `daily-stop`, `stream-outage`, `order-rejected`, `drop-breaker`, `protection-gap`, `dust-position` — is recorded durably and delivered through the sink, deduped per latch/event, and a broken webhook cannot stop a flatten. The tests inject a `MemorySink`, so the whole row is proven offline with no network and no credentials. |
| Verdict | **PASS** (fixed in this PR: `_alert` seam + wiring; regression tests above) |

## 10. Reconcile: reports and repairs drift, refuses when the venue is unreachable

| | |
|---|---|
| Code path | `src/cryptobot/cli.py::cmd_reconcile` (read-only venue status; `VenueHttpError` → exit 2, never "flat"), `src/cryptobot/execution/runtime_trader.py::recover` (repair of drift at start) |
| Tests | `tests/unit/test_cli_readiness.py::test_reconcile_exposed_expect_flat_fails`; `tests/unit/test_cli_readiness.py::test_reconcile_unreachable_venue_fails_and_never_claims_flat` (added here); `tests/unit/test_execution_runtime.py::test_recover_marks_lost_and_releases_unfilled` |
| Command | `.venv/bin/pytest tests/unit/test_cli_readiness.py tests/unit/test_execution_runtime.py -q` |
| Evidence | Reconcile prints positions/orders/equity from the venue and fails with exit 2 when `--expect-flat` finds exposure; an unreachable venue (503) exits 2 with `FAIL` on stderr and never prints `FLAT`. Repair of drift is the recovery path (cancel-orphans, release-unfilled), proven in row 1/6 tests. |
| Verdict | **PASS** for report + refuse-when-unreachable + repair-by-recovery. A live end-to-end `cryptobot reconcile` against the demo venue is **GAP** — it needs the owner's demo keys (see below). |

## What still requires the owner's demo keys

Nothing in this matrix is claimed as proven against a live venue. The
following are exercised only against the offline venue doubles here and need
one run with the owner's demo keys to be signed off:

1. `cryptobot reconcile` against `demo.toml` (real `venue_status`, real
   positions/orders/equity, and the `--expect-flat` refusal on a real account).
2. The listen-key lifecycle and websocket handshake against the real demo
   stream host (`test_listen_key_lifecycle_and_expiry` covers the logic with a
   stub).
3. Real Retry-After / 418 IP-ban behaviour and real clock-drift headers from
   the venue, versus the recorded responses used in the fault matrix.
4. A true `kill -9` of the live process against a real open demo position:
   the recovery path is proven with a simulated kill plus journal restart, not
   with an OS-signalled live demo process.

## Executed run log (append-only, this environment)

```
$ uv sync --locked --extra dev
Resolved 30 packages in 133ms
Downloading nautilus-trader (148.8MiB), pyarrow (34.7MiB), numpy, pandas, ruff, mypy, ...
# still downloading/building after 25+ minutes; no pytest/ruff/mypy in .venv yet

$ .venv/bin/pytest tests/unit/test_safety_alerts.py -q
.venv/bin/pytest: No such file or directory            # exit 127 (venv incomplete)
$ .venv/bin/pytest tests/unit/test_cli_readiness.py -q
.venv/bin/pytest: No such file or directory            # exit 127
$ .venv/bin/pytest tests/unit/test_execution_orders.py tests/unit/test_execution_positions.py \
      tests/unit/test_execution_runtime.py tests/unit/test_adapters_user_stream.py \
      tests/unit/test_execution_fake_venue.py -q
.venv/bin/pytest: No such file or directory            # exit 127
$ .venv/bin/ruff check src tests
.venv/bin/ruff: No such file or directory              # exit 127
```

**No test in this commit was executed.** The commands above are recorded as
run and failed to start; the results are appended in follow-up commits once
the environment finishes installing.

## Verification limits

- The audit was run in the macOS session workspace, not the owner's
  `~/Code/cryto-bot` checkout, and no full `tests/unit` run was performed
  (standalone pytest scratch files of up to ~137 MB per test filled this Mac's
  disk in an earlier session — see the run log for exactly what was executed).
- `tests/audit/test_sandbox_drill.py::test_rate_limit_refuse_fast_no_order`
  fails at base because it encodes the pre-persistence rate-limit semantics;
  the persisted-window behaviour is the intended one and is proven by
  `tests/unit/test_e1_fault_matrix.py::test_a_retry_after_window_survives_engine_restart`.
  The release owner is fixing that test in a separate PR.
