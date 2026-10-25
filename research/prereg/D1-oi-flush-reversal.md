# D1 — Open-interest flush reversal (intraday, 5-minute)

Status: FROZEN-BEFORE-EVALUATION. Family D, hypothesis 1 of 1. Committed
before any D1 return, forward price change, P&L or event count has been
computed. DEV data only (DEV = [2019-09-01, 2024-01-01) per
`research/prereg/SPLIT.md`). The holdout stays sealed: no file dated
2024-01-01 or later may be opened or decoded by D1. S3 object names may
be listed as metadata only to enforce the filename split; no content is
read for any date >= 2024-01-01.

Prior: LOW. The S-family taker scalps failed on costs; H2 was killed on
4.7 years of unseen history; B5 tested a related extreme-move/OI mechanism
at daily resolution and was killed. H1 and H5 book studies remain
underpowered rather than cost-killed. A clean KILL is a good outcome.
Nothing in this document may be rescued by post-hoc tuning.

## Economic mechanism

A liquidation cascade is forced, price-insensitive flow: margin calls and
auto-deleveraging push market orders into a thin book. The signature is an
abnormally large price move over a few minutes together with an abnormally
large drop in open interest over the same minutes (positions are being
closed, not opened). Once the forced flow is exhausted, market makers
replenish quotes and price partially reverts. D1 fades the move after the
flush, not during it.

Long flush: price falls sharply AND OI falls sharply -> longs were
liquidated -> go LONG (long-fade). Short flush (mirror): price rises
sharply AND OI falls sharply -> shorts were squeezed out -> go SHORT
(short-fade). A price shock with RISING OI is new aggressive positioning,
possibly informed; D1 does not trade it.

## Counterparty test

Who loses: liquidated leveraged traders and the engine that liquidates them
at any price. Why it could persist: forced flow ignores price by
construction; exchanges must liquidate into the book, and only
liquidity-providers with balance sheet can absorb it. Who is on the other
side of D1: the same liquidity-providers, who are paid for that risk; D1 is
a taker that pays the spread and fee to take the very inventory they are
trying to take. Why it should fail: (F1) shocks that are informed or
trending continue through the hold; (F2) the 1x taker round trip plus
shock-scaled slippage is of the same order as the expected reversion;
(F3) the effect, if any, accrues to makers, who are not modelled as a
strategy here beyond the diagnostic variant below.

## Metrics timestamp convention (empirically established; live availability unverified)

File: `data/futures/um/daily/metrics/<SYM>/<SYM>-metrics-YYYY-MM-DD.zip`,
Normally 288 unique time points per day, column `create_time`
("YYYY-MM-DD HH:MM:SS", UTC); some early files contain identical
duplicate rows, so uniqueness is enforced below rather than assumed.

Binance's own documentation does not settle this: the
`/futures/data/openInterestHist` page gives a bare `timestamp` field and
does not say whether it labels the start or the end of the 5-minute
period, and the `binance-public-data` README does not describe the
`metrics` files at all. The convention below is therefore established from
the file contents. The initial probe used the 8 files listed in
`research/DATA_LEDGER.md` (BTCUSDT and ETHUSDT, 2022-03-10 and
2023-06-15, with their same-day 1m klines); an independent recheck used
4 additional BTCUSDT files for 2020-10-15 and 2021-06-15. These probes
computed no returns, forward changes or P&L.

1. Taker ratio (column `sum_taker_long_short_vol_ratio`), 2023-06-15.
   For each row stamped T, the ratio was recomputed from the 1m klines
   (taker_buy_volume / (volume - taker_buy_volume)) summed over five
   windows of five 1m bars each. The window `[T-5m, T)` reproduces the
   published value (within 0.2%) in 256/287 rows for BTCUSDT and 270/287
   for ETHUSDT, with a median relative error of 0.0000. Windows shifted
   by one or two minutes reproduce at most 3/287 rows, and the "start"
   windows `[T, T+5m)` and `[T+5m, T+10m)` reproduce at most 3/288 and 1/287.
   So `create_time` T is the END of the aggregation interval: the row
   summarises the five minutes BEFORE T.
2. Open interest (columns `sum_open_interest`, `sum_open_interest_value`),
   2023-06-15 and 2022-03-10. `sum_open_interest_value / sum_open_interest`
   is a price. Compared with the OPEN of each 1m bar, the smallest median
   absolute difference is at the bar whose open time equals T exactly:
   0.19 bps (BTCUSDT) and 0.12 bps (ETHUSDT) in 2023; 0.76 and 0.71 bps in
   2022. The next best bar (T-1m) is 2.1 bps (2023) and 4.6 bps (2022)
   off, and T+1m is 3.1 and 6.1 bps off. So the open-interest value is a
   SNAPSHOT taken at the instant T (at the open of minute T), not an
   average over a later period and not a value from T-5m.
3. The independent recheck reproduced the `[T-5m,T)` taker ratio in
   574/574 available rows (BTCUSDT, 2020-10-15) and 287/287 rows
   (BTCUSDT, 2021-06-15); the OI-implied price was closest to the open
   of minute T on both dates. The 2020-10-15 file had 576 rows: 288 unique
   timestamps duplicated twice with identical values. The 2022-03-10
   taker-ratio field is blank, so the initial taker-ratio evidence comes
   from 2023 only. D1 does not use any taker or long/short ratio column.
   The row timestamp labels an OI snapshot at instant T and a taker-flow
   interval ending at T. The archive does NOT establish when a live client
   could first receive the row; Binance's documentation is silent on
   publication latency. The historical results must therefore be
   described as timestamp-aligned research, not proof of live point-in-time
   availability.

Lag rule (frozen). Treat the row as usable only at T+5 minutes (one full
metrics interval after its timestamp); enter at the open of the 1m bar
starting T+6 minutes. This is a conservative fixed latency assumption,
not a measured service-level guarantee. No price or OI information
stamped after T may enter the signal or its trailing sigmas. Monthly
universe rankings use completed daily files from M-1 and become active
only at 00:06 UTC on the SECOND calendar day of M, allowing one full day
for the previous-month files to publish; no signals are taken on the
first day of M. Actual live publication latency remains unverified. A
pipeline that uses a metrics row before T+5m, or labels the next row's
T+5m observation as if it were the T observation, must fail the named unit
test in PR #2 (`test_metrics_shift_lookahead_is_detected`). The mutation
proof shifts the metrics values one 5-minute row forward while retaining
the earlier signal timestamp, creating lookahead.

Only `sum_open_interest` and `sum_open_interest_value` are used. Rows with
a blank, non-positive or unparsable `sum_open_interest` are missing, and a
window that contains a missing row yields no event. Normalize metrics input
before any windows: exact duplicate rows with the same symbol, timestamp
and values are collapsed to one row; two or more different rows for the
same symbol/timestamp invalidate that symbol-day. Do not select one
conflicting row by order. PR #2 must test identical-row idempotence
(`test_identical_metrics_duplicates_are_deduplicated`) and conflicting-row
rejection (`test_conflicting_metrics_duplicates_invalidate_day`).

## Universe (computed from DEV data only; frozen rule, no list is frozen here)

SPLIT.md fixes that the liquidity universe is a quote-volume ranking
computed from DEV-period data only and never from lifetime or holdout
volume. D1 applies that rule point-in-time rather than with one static
list, because a single ranking over the whole DEV span would choose, with
hindsight, the symbols that became large later (survivorship in the
selection itself). The rule stays inside SPLIT.md's constraint: the inputs
are DEV-dated 1d kline quote volumes only, they are volume (not returns),
and the rule is fixed here before any backtest.

- Candidate set: every USD-M perpetual whose symbol is `<BASE>USDT` with no
  underscore, taken from the S3 listing of
  `data/futures/um/daily/klines/`, including contracts that have since
  been delisted (delivery contracts such as `BTCUSDT_231229` and non-USDT
  quotes are excluded). Before stage 0, snapshot the full candidate
  listing (metadata only), record its retrieval time, symbol/date manifest
  and SHA-256 in the output and DATA_LEDGER, and verify that it contains
  historical delisted symbols. The metrics listing showed LUNAUSDT,
  SRMUSDT, FTTUSDT, BTSUSDT, HNTUSDT and RAYUSDT; this is not by itself
  proof that the kline candidate listing is exhaustive. If the kline
  listing cannot demonstrate coverage of delisted USD-M USDT perps, report
  survivorship as unresolved and do not claim an unbiased universe. A
  symbol's life is the date range of its own files.
- Monthly reconstitution uses only data dated before M: rank candidates
  by their summed 1d-kline `quote_volume` over the previous full calendar
  month M-1; take the top N = 30 (a symbol must have all days of M-1
  present to be ranked); require listing age >= 90 days at the start of M
  (age = days since the symbol's first 1d kline file). The ranking is
  frozen for all of M. Binance's [public-data README](https://raw.githubusercontent.com/binance/binance-public-data/master/README.md)
  says daily files become available the next day but gives no release
  time; the ranking therefore becomes active at 00:06 UTC on the second
  calendar day of M, with no signals on the first day of M.
- First ranking is for 2020-10 (metrics start 2020-09-01), active
  2020-10-02 00:06 UTC. Later rankings use only DEV months.
- A symbol that is delisted mid-month stays in the universe until its
  data ends. A missing entry bar means no entry. Once entered, never erase
  a trade because its scheduled exit bar is missing: exit at the open of
  the first later available 1m bar within DEV, booking funding through
  that actual exit and full taker costs. If no later bar exists before the
  symbol's data ends, close at the last available DEV bar close with full
  costs and flag `forced_exit_data_end`; this terminal-price convention
  cannot price an unobserved post-delisting move and must be disclosed.
- An entry is forbidden if its scheduled exit time is >= 2024-01-01
  00:00 UTC. All actual entry, exit and funding timestamps must be
  strictly before the DEV cutoff; no row dated 2024-01-01 or later may be
  opened. If an entered trade's exit bar is missing near the cutoff, use
  the last available DEV bar close by the rule above.
- Funding is charged at every crossed settlement. If a funding record is
  missing, do not drop the trade: charge an adverse funding debit equal to
  the largest absolute funding rate for that symbol in the 365 days
  preceding entry, with both LONG and SHORT paying that debit. If no full
  trailing year is available, the symbol is ineligible at entry. This
  fallback is point-in-time, reported as `imputed_funding`, and doubled at
  2x stress. A symbol-day without a metrics file yields no events.

## Exact event definition

Time is 5-minute grid time T = the `create_time` of a metrics row (so
T mod 5 min = 0). W is the window length in minutes, W in {5, 15}; every
window is made of whole 5-minute steps.

- Price: 1m bar OPEN prices (`open`) of the symbol's own USD-M
  perpetual klines; `P(t)` is the open of the 1m bar starting at t, i.e.
  the price at instant t. Return shock `r_W(T) = ln P(T) - ln P(T - W)`.
- OI: `O(T)` = `sum_open_interest` of the row stamped T. OI change
  `g_W(T) = ln O(T) - ln O(T - W)`.
- Trailing sigmas (point-in-time): `sigma_r,W(T)` = sample standard
  deviation (ddof=1) of `r_W` over NON-overlapping windows ending at
  T - W, T - 2W, ... covering the trailing 7 days (7*1440/W observations
  at most) and ending at or before T - W, so the current window is never
  inside its own sigma. `sigma_g,W(T)` is the same for `g_W`. Minimum 70%
  of the nominal observation count required, else no event. Raw (not
  demeaned) z-scores.
- `z_r = r_W / sigma_r,W`, `z_g = g_W / sigma_g,W`.
- Event: `|z_r| >= K` AND `z_g <= -2.0` (fixed, not gridded: OI fell by at
  least two of its own standard deviations over the same window). K is a
  grid parameter.
- Direction (fade): `z_r <= -K` -> LONG (long-fade); `z_r >= +K` ->
  SHORT (short-fade). Each side is evaluated by the same rule and the two
  sides are pooled in every statistic; per-side counts and expectancies
  are reported but not gated (no side selection is allowed).
- One position per symbol at a time: an event on a symbol that is in a
  position (from its entry to its exit) is ignored. No other cooldown.
- Portfolio: every event is an independent unit-notional trade; returns
  are in bps of notional. Events are strongly clustered in time (market-wide
  flushes); this is handled by day-block resampling and the distinct
  event-day gate, not by position caps.

## Entry and exit

- Entry: row T becomes usable at T+5m under the frozen latency rule;
  taker at the OPEN of the 1m bar starting at T + 6 minutes (entry price
  `P(T+6m)`).
- Exit: taker at the OPEN of the 1m bar starting at (T + 6m + H), H the
  fixed holding period in minutes (grid parameter). Time exit only; there
  is no stop, no target and no re-entry on the same event. (A protective
  stop is deliberately omitted: one more tuned parameter on a 5-minute
  signal is a degree of freedom, and B5's 2x stop was never shown to matter.)
- Gross trade return (bps) = `10^4 * s * (P_exit / P_entry - 1)`,
  `s = +1` LONG, `-1` SHORT.

## Parameter grid (8 cells, ALL trials counted)

| window W (min) | shock threshold K (sigma) | hold H (min) |
|---|---|---|
| 5, 15 | 3, 4 | 15, 60 |

Fixed (not gridded): OI condition `z_g <= -2.0`; sigma lookback 7 days;
universe N = 30, age >= 90 days; metrics availability lag 5 minutes;
entry at T+6 minutes; one position per symbol; time exit only. 2 x 2 x 2 = 8 cells. The grid is frozen. No cell
is added, removed, edited or re-parameterised after the first return is
computed; any addition is a new preregistration and its cells are added to
the program trial count.

## Cost model (frozen; per trade, bps of notional)

Per side (entry and exit each pay it):

- taker fee 5.0 bps (USD-M VIP-0 taker 0.05%);
- half-spread 1.0 bp;
- shock-scaled slippage `1.0 + 0.05 * |r_W|_bps` bps, where `|r_W|_bps`
  is the absolute entry-time shock in bps (so a 75 bps flush costs
  4.75 bps of slippage per side; the same value is used on the exit side).

Round trip at 1x = 2 * (5.0 + 1.0 + 1.0 + 0.05*|r_W|_bps) = 14.0 +
0.1*|r_W|_bps bps, before funding.

Funding: charge from the `fundingRate` monthly archive at every UTC
settlement (00:00, 08:00, 16:00) with `entry_time < settlement <=
exit_time`; a LONG pays `+rate`, a SHORT receives it (cost =
`s_pay * rate * 10^4` bps, `s_pay = +1` for LONG, `-1` for SHORT). If a
funding record is missing, keep the trade and apply the adverse trailing
365-day max-absolute-rate debit described in the data-gap rule; never book
missing funding as zero.

2x stress: every fee, spread and slippage component is doubled, funding
debits are doubled and funding credits are set to zero.

Net return = gross - round-trip cost - funding cost. "1x" means the
costs above; "2x" the stress above. Costs are never reduced, rounded or
re-estimated after the fact.

### Optional maker-entry variant (diagnostic only, 8 more cells counted)

Same events, same exit. Entry replaces the taker market order with a
passive limit order at `P(T+6m)` in the fade direction (buy for LONG, sell
for SHORT), time-to-live 5 minutes from T+6m. Conservative queue model,
NO credit for touches: the order fills only if a 1m bar from T+6m through
T+10m, inclusive, trades STRICTLY THROUGH the limit by at least 1 bp (LONG:
`low <= limit * (1 - 0.0001)`; SHORT: `high >= limit * (1 + 0.0001)`),
and then fills at the limit price at that bar's close time; the holding
period H runs from the next 1m bar open after the filling bar, with a
taker exit. Maker fee 2.0 bps, half-spread 0 on the entry side, exit side
as taker (5.0 + 1.0 + slippage computed from the original signal-time
shock `|r_W(T)|`; do not recompute an exit-time shock). Unfilled
orders are not trades and are not replaced, so the traded sample is the
adverse-selected sample by construction. Fill rate is reported. The
variant can never turn a KILLED verdict into a pass and has no gates of
its own; it is reported for information and its 8 cells count toward the
program trial count N below.

## Gates (every gate applies to the SELECTED cell; any miss = FAIL)

Eligible cells have both >= 300 events AND >= 100 distinct event days.
Select the eligible taker cell with the largest 1x net Sharpe (defined
below); if no cell is eligible, the verdict is UNDERPOWERED. Break exact
Sharpe ties by lexicographically smallest `(W,K,H)` tuple. All 8 cells are
reported whatever the selection. Optional maker cells are diagnostic only
and are never eligible for selection or for reviving D1.

Sharpe unit used everywhere in D1: group trades by UTC entry day; for each
day that has at least one trade, `x_d` = mean net trade return of that
day's trades (bps); `SR = mean(x_d) / std(x_d, ddof=1)` over event days,
NOT annualised.

1. n >= 300 events (trades after exclusions) AND >= 100 distinct event
   days.
2. Mean net return per trade > 0 at 2x costs.
3. Day-block bootstrap (UTC day blocks, 5,000 resamples, seed 7) 95%
   confidence interval of the mean net trade return at 1x: lower bound > 0.
4. DSR >= 0.80 by this explicitly custom D1 calculation (not
   `slow_stats.dsr_detail`): for each of the 8 taker cells, compute
   `SR_j = mean(x_d,j)/sd(x_d,j)` in the unannualized event-day units
   above. `V = sample variance (ddof=1) of those 8 SR_j`; the expected
   maximum is `SR0 = sqrt(V) * [(1-g)*Phi^-1(1-1/N) +
   g*Phi^-1(1-1/(N*e))]`, `g=0.5772156649`, `N` = the exact frozen
   program-level configuration count. D1 deliberately estimates the trial
   dispersion from its own 8 frozen cells and uses the program-wide N to
   penalize prior searches; this exchangeability approximation is a
   limitation, not a claim that cell dispersion is program-wide. For the
   selected cell, `DSR = Phi((SR-SR0)*sqrt(n_d-1) /
   sqrt(1-skew*SR+(kurt-1)/4*SR^2))`, with `n_d` event days, skew and
   Pearson kurtosis of that cell's `x_d`. No autocorrelation adjustment
   is applied beyond day aggregation. PR #2 must test fixed intermediate
   values (`V`, `SR0`, `n_d`, skew, kurtosis and DSR) against a synthetic
   fixture before evaluation.
5. PBO <= 0.30 by CSCV over the 8 cells on the full calendar-day series
   of mean net daily return (days with no trade = 0). Split chronological
   calendar days into 8 consecutive partitions with `numpy.array_split`
   semantics (remainder days go to the earliest partitions). For each of
   the 70 ways to choose 4 partitions in-sample, the other 4 are OOS;
   select the highest in-sample daily Sharpe, breaking exact ties by
   lexicographically smallest `(W,K,H)`. Let `lambda` be the OOS rank
   fraction of the selected cell, defined as the number of the other 7
   cells with strictly lower OOS Sharpe divided by 7 (`0` = worst,
   `1` = best). For OOS ties, assign the selected cell the lowest rank
   within its tie group; ties do not count as lower-scoring competitors.
   Thus an all-tied OOS set has `lambda = 0`. `PBO` is the fraction of
   splits with `lambda < 0.5`. This deterministic calculation has no
   random seed.
6. >= 60% positive months: of the calendar months 2020-10 .. 2023-12
   (39 months), the fraction whose mean net 1x trade return is > 0 must be
   >= 0.60. A month with no trade counts as NOT positive.
7. >= 3 of the 4 DEV years positive at 1x: 2020 (October-December), 2021,
   2022, 2023; a year is positive if its mean net trade return is > 0 and
   it has >= 30 trades (fewer = not positive).
8. Concentration: remove the three symbols with the largest total net 1x
   contribution (ties broken by symbol name); the pooled mean net return
   among all remaining trades must still be > 0. This is a fixed gate,
   not permission to drop symbols from the reported whole-universe result.

All eight must pass for the verdict `PASS_DEV`. PASS_DEV is not a
trading approval: it only permits the orchestrator to consider a one-shot
holdout screen; the sealed holdout is not touched by D1.

### Program-level trial count N (frozen: N = 428)

The DSR count unit is a distinct frozen strategy configuration (signal,
universe, execution and parameter values). Re-scoring the same unchanged
configuration on a new data window is not another configuration; changing
the universe or strategy rule is. Count every preregistered grid cell even
if not run, plus every distinct fixed configuration already scored. The
inventory below maps all current source studies to that unit; no known
configuration is omitted or counted twice.

| Source file(s) / record | Configurations |
|---|---:|
| `research/prereg/H1-maker-ofi-scalp.md`, `H2-trend-vol-regime.md`, `H3-funding-skew-tilt.md`, `H4-cross-venue-lead-lag.md`, `H5-liquidation-cascade-fade.md`, `H6-vol-shock-regime-filter.md` — all grid cells | 153 |
| `research/prereg/B1-vol-scaled-trend.md` through `B7-low-vol-tilt.md` — all grid cells | 59 |
| `research/prereg/H2-history-falsification.md` — alternate 28-symbol universe B (universe A reuses an H2 grid configuration) | 1 |
| `research/prereg/H4-vol-ranked-trend.md` — separate fixed hypothesis | 1 |
| `research/prereg/H5-alt-maker-ofi.md` — separate fixed hypothesis | 1 |
| `research/prereg/C-family-daily.md` — C1-C4 | 4 |
| `research/prereg/C1-b4b-carry.md` — all DEV-sanity cells; its forward setting is one of these | 4 |
| Pre-prereg records in `RESEARCH_VERDICTS.md` and `DECISIONS.md`: pilot S (14), X1 (24), H-R2 (1), EXP-001/002 executed trials (150) | 189 |
| `research/prereg/D1-oi-flush-reversal.md` — taker grid | 8 |
| `research/prereg/D1-oi-flush-reversal.md` — maker diagnostic grid (counted whether run or not) | 8 |
| **Program total N** | **428** |

Crosswalk for separately recorded evaluations: `H1-book-capture.md` uses
an H1 configuration already represented in its 27-cell grid. In
`H2-history-falsification.md`, universe A reuses an H2 grid configuration;
universe B is the additional configuration above. The H2 2026 extension
reuses its existing H2 rule. `C2-forward.md`, its amendment, and the C2
holdout/replication use the unchanged C2 rule already counted in
`C-family-daily.md`; data windows do not create new configurations.
`B4b-forward-basis.md` uses the `k=1.5, drift_band=0.05` configuration
already counted in `C1-b4b-carry.md`. The C-family amendments and
`ADJUDICATION.md` alter reporting/protocol, not strategy configurations.
The inventory covers all current preregistration files and the separately
reported fixed hypotheses above; each counted cell is one distinct
configuration. No additional changed-parameter evaluations appear in the
repository's current preregistration and verdict records; the listed
repeated evaluations were reconciled to their unchanged configurations. The sum is
`153+59+1+1+1+4+4+189+8+8 = 428`; the D1 gate uses 428.

## Immediate-kill rule (no tuning, no appeal)

For each taker grid cell i compute GROSS price expectancy (mean gross
trade return before fees, spread, slippage or funding) minus its mean 1x
all-in cost (fees, spread, slippage and signed funding cost; credits reduce
1x cost, while missing funding uses the adverse imputation rule). If
`max_i(gross_i - all_in_cost_i) < 0`, D1 is KILLED immediately: no further
gate is evaluated for selection, no parameter is changed, no cell is
added, no subset of symbols or years is re-examined, and the maker variant
cannot revive it. Any cell with negative gross-minus-all-in-cost cannot
be selected.

## Power analysis (event COUNTS only; no return is used)

Nothing about returns is used here. The only quantity ever computed
before the verdict is the event COUNT, in a count-only stage ("stage 0"):
for each of the 8 cells, the number of events, distinct event days,
per-year and per-month counts, and per-symbol counts, using the trigger
(past prices and OI) and the no-overlap rule only; no forward price, no
entry/exit return, no cost is evaluated. The frozen consequence of stage 0
is mechanical: a cell with fewer than 300 events or fewer than 100 event
days is `UNDERPOWERED` and cannot be selected; if no cell reaches 300
events the verdict is `UNDERPOWERED` and the rest of the pipeline does not
run. Stage 0 may not change the grid, the thresholds or the universe.

Planning arithmetic (assumptions, not measurements): with a one-sided 5%
test and 80% power the minimum detectable mean, in units of the standard
deviation of independent day-block mean returns, is
`(1.645 + 0.842) / sqrt(n_eff)`; `n_eff` is the number of independent day
blocks because events cluster by day. This is not per-trade standard
deviation. No return variance is estimated here.

| independent day blocks n_eff | minimum detectable mean (sd units) |
|---:|---:|
| 100 | 0.249 |
| 300 | 0.144 |
| 1,000 | 0.079 |

Raw events are not independent blocks, so 300 events on 100 days is
treated as 100 blocks. The 1x cost hurdle (about 14 bps plus 0.1 x the
shock) is a fixed bps number, so whether a given minimum detectable effect
is smaller than the hurdle cannot be known before returns are seen. The
table is only a normal-approximation planning calculation in units of the
standard deviation of independent day-block means; it does not establish
power for the actual clustered, fat-tailed series.
Expected count scale for planning only: 30 symbols x 288 five-minute
steps x ~1,185 days is ~10 million symbol-steps, and the joint event is a
tail event in both price and OI, so the count is expected to be in the
low thousands per cell, spanning orders of magnitude depending on how
fat-tailed and correlated the two series are; stage 0 is what settles
it.

## Dev evaluation protocol

- Data: DEV files only (filename date < 2024-01-01), from
  data.binance.vision, downloaded to a scratch directory outside the
  repository, processed symbol by symbol, deleted afterwards, never
  committed. The tool must refuse to open any file whose filename date is
  >= 2024-01-01 and must never decode one.
- Sources: daily 1m klines and daily metrics for the universe's symbols,
  monthly fundingRate, 1d klines for the ranking, S3 listing for the
  candidate set. Every dataset use is logged in `research/DATA_LEDGER.md`.
- Order: PR #1 (this document) merges first; no return is computed before
  that. PR #2 builds the pipeline with unit tests on synthetic data and
  the mutation proof, then runs stage 0, then the evaluation. Output:
  `research/autopilot_d/dev/D1.json` (machine-written, binds this
  document's SHA-256, code hash, data manifest) plus a short
  machine-written verdict note.
- Stop: after the DEV result. No holdout file is decoded or scored.
- Seeds: bootstrap 7, CSCV 7. No other randomness.

## Failure modes

F1: flush moves are informed or trending and continue through the hold.
F2: costs (14+ bps round trip plus funding) exceed the reversion (the
immediate-kill rule is for this). F3: clustering: a handful of
market-wide crash days produce most events (day-block CI, distinct-day
gate, positive-month and year gates). F4: OI series artefacts (contract
migrations, sparse small-symbol OI) produce spurious z_g (minimum
observation rule; missing rows void windows). F5: concentration in a few
symbols (gate 8). F6: data end effects for delisted symbols (forced exit
at the last open at full costs). F7: sigma estimation at 5 minutes is
dominated by intraday seasonality and a 7-day window; D1 accepts that and
does not tune it.

## Knowledge-contamination note

Same background knowledge as B5/B6: the author expects liquidation
reversal to exist at some scale and to be costly. Avoidance: round
thresholds (3 and 4 sigma, 2 sigma for OI), windows of 5 and 15 minutes,
holds of 15 and 60 minutes; no recalled "OI down X% means long" number;
the sign is the hypothesis; no event, date or symbol is named in any rule.
The only data touched before this commit are the probe files listed in the
ledger (two symbols, two dates, DEV period) used to prove the timestamp
convention, plus S3 listings (names and dates only); no returns, forward
price changes, volatilities or counts were computed from them.

## Amendment rule

This document is frozen. A change to any rule, threshold, grid cell,
universe parameter or gate requires a new preregistration with a new
file, is described by its author before any further return is computed,
and adds its cells to the program trial count. A result is never
re-evaluated under changed rules.
