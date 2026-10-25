# D1 — amendment 2: trial-count correction (frozen before evaluation)

This amendment supplements the frozen D1 specification and amendment 1 before any D1 return, forward price change, P&L, event count, or power estimate is computed. It supersedes amendment 1's claim that `N=442` is complete. It does not change D1's signal, grid, universe, execution, cost model, statistics, or gates. The original specification and amendment 1 remain unchanged; bind this amendment alongside both in any later D1 output.

## Program-level trial count: lower bound only

The exact program-level trial count is not yet defensible from the current crosswalk. Do not use 442 as an exact DSR penalty, and do not compute or report D1 DSR until a later pre-evaluation amendment freezes an exact, reproducible count. The defensible minimum from the existing amendment-1 inventory plus the omitted H3/H6 filter applications is **N >= 470**:

| Crosswalk component | Count | Reconciliation |
|---|---:|---|
| Amendment-1 inventory | 442 | Retained as the prior enumerated inventory, not asserted complete. |
| H3 applied as a filter on H2 | +1 | H3 §31 says this distinct filter trial counts once; it is absent from the 442-row arithmetic. |
| H6 applied to H2 and H3 | +27 | H6 §31 has 27 filter parameter cells and says each filtered cell counts. The 442 inventory includes those 27 parameter cells only once; the two base-hypothesis applications are 54 distinct filtered configurations, so add the missing 27. |
| **Audited lower bound** | **>=470** | `442 + 1 + (2 * 27 - 27)`. This is a floor, not the final N. |

This floor relies on the amendment-1 inventory as an already enumerated minimum. It does not imply that every underlying record or legacy count in that inventory has been independently reconciled to a unique trial identity.

## Unresolved crosswalk items; do not treat the floor as complete

The counting key must distinguish a rule-selection opportunity by its hypothesis/base rule, filter, parameter cell, universe/execution setting, and evaluation split or confirmation-window choice. Identical keys are deduplicated; different preregistered splits, settings, or confirmation-window choices that could inform selection are counted separately. The existing amendment-1 table does not provide the required cell-by-cell keys for these items, so they are not assigned speculative totals here:

- **H1–H6 walk-forward selections:** their preregistrations specify fold-based promotion tests; H1–H5 use three-fold criteria, and H6 evaluates filtered variants against H2 and H3 over folds. Reconcile every grid/filter cell against each distinct DEV split/setting and deduplicate only identical keys. The H3/H6 missing applications above are included in the floor; any additional split-level variants are not.
- **B1–B7 walk-forward selections:** B1 specifies three anchored OOS splits (train through 2020/test 2021; through 2021/test 2022; through 2022/test 2023); B2–B7 refer to that schedule. Reconcile each registered cell against each split/setting, rather than counting only a pooled result or a grid total.
- **Confirmation-window choices:** the H1–H6 and B1–B7 preregistrations specify one-shot confirmation choices. Reconcile each distinct strategy/filter configuration and its registered confirmation window/setting. Amendment 1 does not map all such choices to unique trial keys. No confirmation data was accessed for this amendment.
- **Earlier selection records:** the legacy DEV verdict and decision records named in amendment 1 do not, in that crosswalk, identify every changed rule/filter/universe/split key. Their already-listed entries remain in the floor; any additional documented selection variants must be appended without duplicating an identical key.

A later exact-count amendment must publish the full row-level key crosswalk, the source record for every key, a deterministic deduplication rule, and a checked arithmetic sum. It must be committed before any D1 return, event count, or power estimate is computed. Until then the DSR gate is **not evaluable**, the preregistration remains draft, and no evaluator may substitute 470 (or 442) as if it were exact.

## Evidence boundary

This correction used only preregistration text and the already-recorded amendment-1 arithmetic; it computed no strategy returns, forward price changes, event counts, power estimates, or P&L, and accessed no dataset contents. The D1 holdout restriction is unchanged: no file dated 2024-01-01 or later may be opened or decoded, and D1 stops after DEV.
