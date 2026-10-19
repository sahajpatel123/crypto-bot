# SPLIT PREREGISTRATION — Family B long-history data (E2.1)

Committed BEFORE any statistical look at the lake data. Only inventory
metadata (file counts, date ranges, byte sizes, filenames from
DATA_INVENTORY.md) was used to choose the cutoff. No returns, volume
statistics, backtests, or plots have been computed on any lake data.

## Cutoff

`C = 2024-01-01T00:00:00Z` (calendar choice, not data-fitted).

| Split | Range (UTC) | Length | Use |
|---|---|---|---|
| DEV | [2019-09-01, 2024-01-01) | 52 months (~4.3 y) | all Family B development, walk-forward OOS, tuning |
| HOLDOUT | [2024-01-01, 2026-10-17] | ~33.5 months (~2.8 y) | exactly-once screen per hypothesis via `verdict` |
| FORWARD | (2026-10-17, ...] | grows | recorder + later downloads; FORWARD_PAPER stage |

- DEV ≥ 3 years ✓ (covers earliest UM data, 2019-09 trades).
- HOLDOUT ≥ 24 months ✓ (monthly leg ends 2026-09, daily leg ends
  2026-10-17 at ingestion time 2026-10-18).
- Ingestion-time data end is frozen: any file dated after 2026-10-17
  belongs to FORWARD even if downloaded later.

## Enforcement (no content decode)

Splits are assigned by FILENAME date only:

- Monthly file `<SYM>-<kind>-YYYY-MM.zip`: DEV iff `YYYY-MM < 2024-01`,
  else HOLDOUT. (The `2024-01` monthly file is entirely in HOLDOUT.)
- Daily file `<SYM>-<kind>-YYYY-MM-DD.zip`: DEV iff date < 2024-01-01,
  else HOLDOUT.
- `bookTicker` (ends 2024-04, discontinued) is out of scope entirely.

The downloader writes DEV files to `data/lake/raw/` (decodable) and
HOLDOUT files to `data/lake/holdout_raw/` (sealed by hash, never
decoded except by `verdict` with a one-shot token). Assignment code is
tested with filename fixtures (no content reads).

## Liquidity-scope rule

The 1m top-20 list and the metrics-download symbol list are computed
from DEV-period data ONLY, after this commit. The inventory's
lifetime-bytes top-20 (DATA_INVENTORY.md §8) MUST NOT be used — it
peeks at holdout volumes. Metric: total DEV-period quote volume from 1d
klines (a volume ranking, computed post-split; the ranking itself is
not a return signal and is frozen before any backtest).

## Power: detectable Sharpe on the holdout

Screen uses daily marked-to-market returns: N = 1021 days
(366 + 365 + 290), T = 2.797 years. For annualized Sharpe SR,
t = SR·√T = SR·1.6726 (iid normal approximation; bootstrap CIs used
in practice, this is the planning math).

| Bar | Required t | Detectable SR |
|---|---|---|
| one-sided 95% significance | 1.645 | **0.98** |
| two-sided 95% significance | 1.960 | 1.17 |
| 80% power, one-sided 95% test | 2.487 | 1.49 |

Screen legs (point SR > 0.3): threshold t = 0.50.
Sensitivity at true SR=1.0: P(Z > 0.50−1.67) ≈ **0.88**.
Type-I at true SR=0: P(Z > 0.50) ≈ **0.31** for this leg alone.

**Explicit statement: a ~33-month holdout cannot PROVE a true Sharpe
of ~1.** The holdout is a SCREEN: it kills strategies inconsistent
with edge (negative point, violated drawdown, 2x-cost failure) and
passes candidates to the forward-paper stage, which plus a tiny
canary carries the remaining uncertainty. The combined screen
(point > 0.3 AND ≥50% of dev OOS AND 80% bootstrap LB > −0.3 AND
positive at 2x cost AND drawdown in budget) is strictly tighter
than the point leg; realized family-wise error is reported, not
assumed.

## Statistical-look boundary (attestation)

Before this commit, the only lake-data operations were:
1. S3 delimiter listings (names, counts, sizes, dates) via
   `tools/vision_inventory.py`;
2. Four tiny probes (~7 KB): one funding CSV head, one metrics CSV
   head, one kline zip magic check, CHECKSUM format reads — to
   document column formats, not to compute statistics.

No per-symbol returns, volatilities, correlations, rankings by
performance, backtests, or parameter choices have been derived from
lake data. All Family B rules/parameters come from economic mechanism
+ literature conventions, documented per-prereg with a
knowledge-contamination note.

## Family B budget (E2.3, justification in DECISIONS.md D-032)

Family B has its own hypothesis budget (max 8) and its own Holm
family, separate from Family A (H1–H6). Rationale: different data
(multi-year daily public lake vs tick/dev data), different return
generating process and holding periods, disjoint trial universes.
Deflated-Sharpe trial counts apply within each family.
Family B registry: `research/autopilot_b/registry.json` (separate
chain from `research/autopilot/`).
