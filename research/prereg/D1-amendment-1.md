# D1 — amendment 1 (frozen before evaluation)

This amendment supplements the frozen `research/prereg/D1-oi-flush-reversal.md` before any D1 return, forward price change, P&L, event count, or power estimate is computed. The original document remains unchanged. Only the items below are amended; every other signal, grid, cost, statistic, and gate in D1 remains as frozen. This amendment is part of the D1 preregistration and must be hashed alongside the original document in any output.

## 1. Program-level trial count

For DSR, count one trial per preregistered grid cell, plus one for each separate scored evaluation window or separately preregistered look that could have informed a decision, even when a rule is reused. Count every registered cell whether or not it was run. Count invalid/voided scored runs because their results were observed. Repeated windows are not collapsed into one configuration.

The count-only crosswalk below reconciles the current preregistration and verdict records. Evaluation windows and decision influence are stated where known; no raw return data or holdout files were read or recomputed for this audit.

| Source / unit | Count | Window and whether it informed a decision |
|---|---:|---|
| H1–H6 preregistered grids: `H1-maker-ofi-scalp.md`, `H2-trend-vol-regime.md`, `H3-funding-skew-tilt.md`, `H4-cross-venue-lead-lag.md`, `H5-liquidation-cascade-fade.md`, `H6-vol-shock-regime-filter.md` | 153 | All registered cells, including unrun cells; scored outcomes where reported informed the recorded DEV verdicts. |
| B1–B7 preregistered grids | 59 | All registered cells; scored outcomes where reported informed the recorded DEV verdicts. |
| Earlier fixed-rule H2/H3 evaluations in `RESEARCH_VERDICTS.md` | 3 | H2 `benchmark_30d`, its 2026-10-12..19 extension, and H3 `benchmark_30d`; 8-symbol rules/universe differ from the later H2/H3 preregistered grids. Results informed subsequent H4/H5 motivation. |
| H2-HIST primary and secondary universe evaluations | 2 | 2022-01..2026-08; 8-symbol and 28-symbol universes, both reported separately and used in the H2 kill/selection-dependence conclusion. |
| H4 vol-ranked fixed hypothesis | 1 | Separate registered hypothesis; counted whether scored or not. |
| H5 alternate maker-OFI fixed hypothesis | 1 | Separate registered hypothesis; counted whether scored or not. |
| H1 book-capture evaluation | 1 | Separate BTC/ETH capture window; its underpowered result informed the later alt-universe H5 study. |
| H5 alternate-OFI capture evaluation | 1 | Separate 2026-10 capture window; its zero-signal result informed the signal-starvation conclusion. |
| Family C daily DEV configurations (C1–C4) | 4 | 2022-01..2024-12; outcomes informed the recorded Family C decisions. |
| C1-B4b DEV-sanity cells plus forward confirmation window | 5 | Four DEV-sanity cells plus the separately preregistered forward window. The forward result is not yet available; `B4b-forward-basis.md` is the same forward cell and is counted once. |
| C2-forward original and amended looks | 4 | The superseded 180-day look plus the amended 365/730/1,095-day looks. Preregistered but no forward result exists. |
| C2 one-shot holdout and replication | 2 | Holdout 2025-01..2026-08 and replication 2020–21; both informed the decision to close Family C. |
| Voided B4 25%-leg screen | 1 | The observed but later voided screen in `research/verdicts_b/B4.json`; counted because its result was seen before correction D-042. |
| Pre-prereg trials: pilot S, X1, H-R2, EXP-001 and EXP-002 | 189 | S 14, X1 24, H-R2 one fixed configuration, EXP-001 90 and EXP-002 60. These are the prior recorded evaluations. |
| D1 taker grid | 8 | All frozen cells. |
| D1 diagnostic maker grid | 8 | All frozen cells, counted whether run or not. |
| **Program-level N** | **442** | |

Arithmetic: `153+59+3+2+1+1+1+1+4+5+4+2+1+189+8+8 = 442`.

In the D1 DSR formula, replace the original `N=428` with **N=442**. This reconciled count is deliberately conservative: repeated scored windows, sequential looks, and the voided screen are not collapsed or discarded.

## 2. Strict DEV exit boundary

The DEV cutoff remains `C = 2024-01-01 00:00 UTC`. All bar timestamps mean bar-start timestamps. An entry is forbidden if its entry time or scheduled exit time is greater than or equal to C. Every actual exit and funding-settlement timestamp must be strictly less than C; no post-cutoff row may be opened.

If a scheduled exit bar is unavailable, use the open of the first later available 1m bar whose timestamp is still `< C`. If no such bar exists before the symbol's data ends or before C, close at the open of the last available DEV 1m bar (whose timestamp is `< C`), charge full costs, and flag `forced_exit_data_end`. Never use the final DEV bar's boundary close, which can be exactly C. A synthetic PR #2 test must assert this boundary rule (`test_no_exit_at_or_after_dev_cutoff`).

## 3. Position eligibility with delayed signals

The existing latency is unchanged: a metrics row at T becomes usable at T+5m and the taker entry is scheduled at the open of the 1m bar starting T+6m. Apply the one-position-per-symbol rule at this scheduled entry time, not at signal time T. Ignore a signal if the symbol has a position open then or another entry for that symbol/cell is already scheduled for that time. A taker entry has no pending state. In the diagnostic maker variant, a live unfilled order blocks new signals until it fills or the 5-minute TTL expires; a filled position blocks through its exit. Each grid cell is evaluated independently.

Synthetic PR #2 tests must cover the latency and overlap semantics (`test_entry_bar_is_t_plus_6_after_metrics_availability_lag`, `test_pending_signal_overlap_is_checked_at_entry`).

## 4. Explicit sealed-file exclusion

`research/DATA_LEDGER.md` identifies the monthly 1h `BTCUSDT_231229` archive for 2024-01 as HOLDOUT and records that it was decoded during unrelated debugging. It is not a D1 input: the D1 pipeline must not open or decode it, and it is excluded from every D1 score and selection. Its underscore also makes it ineligible under the frozen candidate-symbol rule. No D1 file dated 2024-01-01 or later may be opened or decoded.

## 5. Mutation-proof implementation checks for PR #2

The synthetic test suite must include and mutation-check the following guards before any evaluation: `test_metrics_shift_lookahead_is_detected` (shift metrics one 5-minute row to introduce lookahead), `test_entry_bar_is_t_plus_6_after_metrics_availability_lag` (change the entry offset), `test_monthly_universe_uses_prior_dev_quote_volume_and_delisted_candidates` (use future/lifetime volume or remove a delisted fixture), and `test_immediate_kill_when_no_cell_covers_cost` (remove the immediate-kill gate). The test named by each guard must fail under its corresponding mutation. Also test the cutoff and overlap rules above on synthetic inputs.
