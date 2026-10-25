# D1 — Open-interest flush reversal (intraday, 5-minute)

Status: FROZEN-BEFORE-EVALUATION. Family D, hypothesis 1 of 1. Committed
before any D1 return, forward price change, P&L or cell statistic has been
computed on any data. DEV data only (DEV = [2019-09-01, 2024-01-01) per
`research/prereg/SPLIT.md`). The holdout stays sealed: no file dated
2024-01-01 or later may be listed-for-decode, decoded or scored by D1.

Prior: LOW. Every intraday family so far (S, X1, H1-H5, B5) died on costs;
H2 was killed on 4.7 years of unseen history; B5 tested the same mechanism
at daily resolution and died. A clean KILL is a good outcome. Nothing in
this document may be rescued by post-hoc tuning.

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

## Point-in-time convention of the 5-minute metrics rows (PROVEN, not assumed)

File: `data/futures/um/daily/metrics/<SYM>/<SYM>-metrics-YYYY-MM-DD.zip`,
288 rows per day, column `create_time` ("YYYY-MM-DD HH:MM:SS", UTC).

Binance's own documentation does not settle this: the
`/futures/data/openInterestHist` page gives a bare `timestamp` field and
does not say whether it labels the start or the end of the 5-minute
period, and the `binance-public-data` README does not describe the
`metrics` files at all. The convention below is therefore established from
the file contents. The probe used only the 8 files listed in
`research/DATA_LEDGER.md` (BTCUSDT and ETHUSDT, 2022-03-10 and
2023-06-15, with their same-day 1m klines), and computed no return,
forward change or P&L.

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
3. Therefore row T carries information up to and including instant T and
   nothing later. (The taker ratio in 2022-03-10 rows is blank, so
   evidence 1 comes from 2023 only; D1 does not use any taker or long/short
   ratio column.)

Lag rule (frozen). A row stamped T is treated as known at instant T. The
first order that can act on it is the open of the 1m bar starting at
T + 1 minute (a deliberate one-bar latency; the price at instant T itself
is not tradable by a decision that needs the whole row). No price or OI
information stamped after T may enter the signal, the trailing sigmas, the
universe or the entry price. A pipeline whose metrics are shifted by one
bar (+5 minutes, i.e. using the row of the NEXT interval as if it were
known) must change the event set and must fail a named unit test in PR #2
(`test_metrics_shift_lookahead_is_detected`).

Only `sum_open_interest` and `sum_open_interest_value` are used. Rows with
a blank, non-positive or unparsable `sum_open_interest` are missing, and a
window that contains a missing row yields no event.

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
  `data/futures/um/daily/klines/` AS IT IS, including contracts that have
  since been delisted (delivery contracts such as `BTCUSDT_231229` and
  non-USDT quotes are excluded). The listing shows delisted symbols
  (LUNAUSDT, SRMUSDT, FTTUSDT, BTSUSDT, HNTUSDT, RAYUSDT were present in
  the metrics listing when checked), so delisted contracts are in the
  universe while they were liquid. A symbol's life is the date range of
  its own files.
- Monthly reconstitution on the first UTC day of each month M, using only
  data dated before M: rank candidates by their summed 1d-kline
  `quote_volume` over the previous full calendar month M-1; take the top
  N = 30 (a symbol must have all days of M-1 present to be ranked);
  require listing age >= 90 days at the start of M (age = days since the
  symbol's first 1d kline file). The ranking is frozen for all of M.
- First reconstitution is 2020-10-01 (metrics start 2020-09-01, so the
  first ranking month, September 2020, is the first month with OI). No
  events are generated before 2020-10-01. Later reconstitutions through
  2024-01-01 (exclusive) use only DEV months.
- A symbol that is delisted mid-month stays in the universe until its
  data ends; its open positions at data end are closed at the last bar
  open at the same costs (no free exit). A symbol with a missing 1m bar at
  the needed entry or exit minute produces no trade (not a free fill).
- Symbols must also have the metrics file for the day; otherwise the
  symbol-day yields no events.

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

- Entry: taker at the OPEN of the 1m bar starting at T + 1 minute
  (entry price `P(T+1m)`).
- Exit: taker at the OPEN of the 1m bar starting at (T + 1m + H), H the
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
universe N = 30, age >= 90 days; entry latency 1 minute; one position per
symbol; time exit only. 2 x 2 x 2 = 8 cells. The grid is frozen. No cell
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

Funding: charged from the `fundingRate` monthly archive for every funding
settlement instant (00:00, 08:00, 16:00 UTC) with `entry_time < settlement
<= exit_time`; a LONG pays `+rate`, a SHORT receives it (cost =
`s_pay * rate * 10^4` bps, `s_pay = +1` for LONG, `-1` for SHORT). Missing
funding data for a crossed settlement -> the trade is dropped and counted
in an `excluded_no_funding` field (never booked as zero funding).

2x stress: every fee, spread and slippage component is doubled, funding
debits are doubled and funding credits are set to zero.

Net return = gross - round-trip cost - funding cost. "1x" means the
costs above; "2x" the stress above. Costs are never reduced, rounded or
re-estimated after the fact.

### Optional maker-entry variant (diagnostic only, 8 more cells counted)

Same events, same exit. Entry replaces the taker market order with a
passive limit order at `P(T+1m)` in the fade direction (buy for LONG, sell
for SHORT), time-to-live 5 minutes from T+1m. Conservative queue model,
NO credit for touches: the order fills only if a 1m bar from T+1m through
T+5m, inclusive, trades STRICTLY THROUGH the limit by at least 1 bp (LONG:
`low <= limit * (1 - 0.0001)`; SHORT: `high >= limit * (1 + 0.0001)`),
and then fills at the limit price at that bar's close time; the holding
period H runs from the next 1m bar open after the filling bar, with a
taker exit. Maker fee 2.0 bps, half-spread 0 on the entry side, exit side
as taker (5.0 + 1.0 + slippage on the exit-time shock `|r_W|`). Unfilled
orders are not trades and are not replaced, so the traded sample is the
adverse-selected sample by construction. Fill rate is reported. The
variant can never turn a KILLED verdict into a pass and has no gates of
its own; it is reported for information and its 8 cells count toward the
program trial count N below.

## Gates (every gate applies to the SELECTED cell; any miss = FAIL)

The selected cell is the grid cell with the largest 1x net Sharpe (defined
below) among cells with >= 300 events; if no cell has >= 300 events the
verdict is UNDERPOWERED. All 8 cells are reported whatever the selection.

Sharpe unit used everywhere in D1: group trades by UTC entry day; for each
day that has at least one trade, `x_d` = mean net trade return of that
day's trades (bps); `SR = mean(x_d) / std(x_d, ddof=1)` over event days,
NOT annualised.

1. n >= 300 events (trades after exclusions) AND >= 100 distinct event
   days.
2. Mean net return per trade > 0 at 2x costs.
3. Day-block bootstrap (UTC day blocks, 5,000 resamples, seed 7) 95%
   confidence interval of the mean net trade return at 1x: lower bound > 0.
4. Deflated Sharpe ratio DSR >= 0.80, with the PROGRAM-LEVEL trial count
   (below), `SR0 = sqrt(V) * [(1 - g) * Phi^-1(1 - 1/N) + g *
   Phi^-1(1 - 1/(N*e))]`, `g = 0.5772156649`, `V` = sample variance
   (ddof=1) of the 8 grid cells' event-day Sharpes in the unit above, `N`
   = the program-level count; `DSR = Phi( (SR - SR0) * sqrt(n_d - 1) /
   sqrt(1 - skew*SR + (kurt-1)/4*SR^2) )` with `n_d` the number of event
   days (already day-clustered, so no further effective-n adjustment),
   skew and (Pearson) kurtosis of `x_d`.
5. PBO <= 0.30 by CSCV over the 8 cells on the calendar-day series of
   mean net daily return (days with no trade = 0), 8 partitions of
   consecutive days, seed 7.
6. >= 60% positive months: of the calendar months 2020-10 .. 2023-12
   (39 months), the fraction whose mean net 1x trade return is > 0 must be
   >= 0.60. A month with no trade counts as NOT positive.
7. >= 3 of the 4 DEV years positive at 1x: 2020 (October-December), 2021,
   2022, 2023; a year is positive if its mean net trade return is > 0 and
   it has >= 30 trades (fewer = not positive).
8. Concentration: excluding the single symbol with the largest total net
   1x contribution, the pooled mean net 1x trade return is still > 0.
   (H2 died with edge concentrated in 3 symbols; no post-hoc symbol
   dropping is ever allowed, so concentration is a gate, not an option.)

All eight must pass for the verdict `PASS_DEV`. PASS_DEV is not a
trading approval: it only permits the orchestrator to consider a one-shot
holdout screen; the sealed holdout is not touched by D1.

### Program-level trial count N (frozen: N = 427)

DSR deflates for every trial the program has ever run, not just D1's.
Counted from the repository's preregistrations and records (cells x
hypotheses; the count is a floor, never padded downward):

| Source | Trials |
|---|---:|
| Family A H1-H6 prereg grids (27+27+27+18+27+27) | 153 |
| Family B B1-B7 grids (12+6+8+9+8+8+8) | 59 |
| B4b forward cell | 1 |
| Family C daily C1-C4 | 4 |
| C1 DEV-sanity grid | 4 |
| C2 forward cell | 1 |
| Pre-prereg: taker-scalp pilot S (14 cells), X1 (24 cells), H-R2 (1), EXP-001/EXP-002 executed trials (150) | 189 |
| D1 taker grid | 8 |
| D1 maker-entry variant cells (counted even if never run) | 8 |
| **Program total N** | **427** |

Sensitivity (reported, not gating): the same DSR with N = 238 (preregistered
cells only, excluding the 189 pre-prereg trials). The gate uses 427.

## Immediate-kill rule (no tuning, no appeal)

For each grid cell compute the GROSS price expectancy (mean gross trade
return, before fees, spread, slippage and funding) and that cell's mean 1x
round-trip cost (fees + spread + slippage only). If the highest gross
expectancy over the 8 cells is BELOW the mean 1x cost of its own cell, D1
is KILLED immediately: no further gate is evaluated for selection, no
parameter is changed, no cell is added, no subset of symbols or years is
re-examined, and the maker variant cannot revive it. If a cell's gross
expectancy is below its 1x cost it cannot be selected.

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
test and 80% power the minimum detectable mean, in units of the per-trade
standard deviation of net return, is `(1.645 + 0.842) / sqrt(n_eff)`;
here `n_eff` is the number of independent day blocks, because events
cluster by day. The per-trade standard deviation is NOT estimated here.

| independent day blocks n_eff | minimum detectable mean (sd units) |
|---:|---:|
| 100 | 0.249 |
| 300 | 0.144 |
| 1,000 | 0.079 |

Raw events are not independent blocks, so 300 events on 100 days is
treated as 100 blocks. The 1x cost hurdle (about 14 bps plus 0.1 x the
shock) is a fixed bps number, so whether a given minimum detectable effect
is smaller than the hurdle cannot be known before returns are seen; the
point of the table is that the gates (n >= 300, >= 100 event days) are
not set so loosely that a noise cell can pass: at the floor (100 blocks)
only effects of about a quarter of one per-trade sd are detectable.
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
