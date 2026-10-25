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

## Split/setting crosswalk and unresolved total

The identity key for a count is `(hypothesis/base rule, filter, parameter cell, universe/execution setting, evaluation split or confirmation-window choice)`. Identical full keys count once; different preregistered split or confirmation-window choices count separately when they could inform selection. The source preregistrations expose cell counts and fold/confirmation requirements, but the H-family documents do not pin every fold boundary and amendment 1 does not map historical run records to all of these keys. The table records the available registered rule and distinguishes a fold-count requirement from dated split boundaries; it is not a complete realized run crosswalk:

| Source | Grid cells | DEV fold/split rule | Confirmation choice |
|---|---:|---|---|
| H1 maker OFI | 27 | 3 anchored folds; boundaries not dated | One-shot, exactly once |
| H2 trend/vol | 27 | 3 anchored folds; boundaries not dated | One-shot, exactly once |
| H3 funding skew | 27 | 3-fold gate; boundaries not dated; plus the H3-on-H2 filter trial (counted once by H3 §31) | One-shot, exactly once |
| H4 cross-venue | 18 | 3-fold gate; boundaries not dated | One-shot, exactly once |
| H5 liquidation cascade | 27 | 3-fold gate; boundaries not dated | One-shot, exactly once |
| H6 volatility filter | 27 parameters; 54 filtered configurations (27 each on H2 and H3) | 3-fold gate across both bases; boundaries not dated | One-shot, exactly once |
| B1 vol-scaled trend | 12 | Train through 2020/test 2021; through 2021/test 2022; through 2022/test 2023 | One-shot confirmation screen |
| B2 x-sec momentum | 6 | Same three B1 splits | One-shot confirmation screen |
| B3 funding carry | 8 | Same three B1 splits | One-shot confirmation screen |
| B4 basis | 9 | Same three B1 splits | One-shot confirmation screen |
| B5 extreme move | 8 | Same three B1 splits | One-shot confirmation screen |
| B6 OI divergence | 8 | Same three B1 splits | One-shot confirmation screen |
| B7 low vol | 8 | Same three B1 splits | One-shot confirmation screen |

The 442 inventory counts H1–H6 and B1–B7 grid cells once; it does not enumerate every cell-by-fold key or every one-shot confirmation key above. The 470 floor adds only the two proven H3/H6 omissions described earlier; it does **not** add unverified fold/window expansions. Earlier selection records named in amendment 1 also lack a complete row-level mapping from each observed rule/filter/universe/split to a unique key. These are explicit gaps, not zero-count assumptions. No confirmation data or holdout contents were accessed for this amendment.

A later exact-count amendment must publish the row-level keys for the registered and actually tried variants, the source record for each key, a deterministic deduplication pass, and a checked arithmetic sum. It must be committed before any D1 return, event count, or power estimate is computed. Until then the DSR gate is **not evaluable**, the preregistration remains draft, and no evaluator may substitute 470 (or 442) as if it were exact.

## Evidence boundary

This correction used only preregistration text and the already-recorded amendment-1 arithmetic; it computed no strategy returns, forward price changes, event counts, power estimates, or P&L, and accessed no dataset contents. The D1 holdout restriction is unchanged: no file dated 2024-01-01 or later may be opened or decoded, and D1 stops after DEV.
