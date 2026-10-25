# B4b — Forward delta-neutral basis/carry (one honest test)

Status: FROZEN-BEFORE-ANY-FORWARD-READ. Committed before a single forward
return was pulled, computed, or looked at. Family C, one cell, one look.

Predecessor: `research/prereg/B4-delta-neutral-basis.md` (KILLED on a
turnover budget that this file does not reuse) and
`research/prereg/C1-b4b-carry.md` (the pre-authorized B4b rule set, whose
confirmation cell this file inherits). Holdout is BURNED for B4 and every
B4 variant (`release/holdout-reconcile.json`: three decodes). No B4 result
is reused or re-scored here.

## Why this study exists, and why the old kill does not carry over

B4's dev numbers were the strongest in Family B: pooled OOS Sharpe 4.396,
DSR 1.000, PBO 0.000, max DD 0.47%, 2x-cost Sharpe 1.723. It died on
exactly one bullet: one-way annualized turnover 17.05 against a frozen
budget of 12.

An independent audit of that bullet found it methodologically unsound,
for three reasons recorded here before any forward data is read:

1. **Double counting.** Every fill inside B4's P&L is already charged the
   full 53 bps round trip (fees + spread + slip). A turnover cap is not a
   second capacity measure on top of that; it penalizes the same cost
   twice.
2. **No capacity content.** "Turnover" is dimensionless (x equity per
   year). It carries no ADV term, so it cannot say whether the book could
   actually be traded. `slow_stats.capacity_estimate()` already exists and
   was dead code — the capacity question was never asked.
3. **Undefined convention.** The prereg never said whether one-way means
   per leg, per round trip, or half of the round trip. Under the
   half-round-trip convention B4 reads 8.53 and passes the same budget.
   A gate whose value moves by 2x with an undefined convention is not a
   gate.

B4b therefore swaps the turnover budget for what the budget was standing
in for: an explicit per-fill market-impact charge and a participation
limit measured against ADV. This is the only gate change. Every other B4
gate is inherited verbatim, plus the significance requirements the
original lacked.

**This file does not license B4's old numbers.** The evidence for B4b is
forward data only.

## Universe (chosen before seeing data)

BTCUSDT and ETHUSDT. Both may be open at once. These are the two deepest
spot/perp basis markets; the choice is a liquidity prior written before
any forward series exists, not a selection on results. No other symbol
can enter this study, and no symbol is added later because it "looks
rich".

## Data

Forward window only. A forward day is a UTC day D such that every input
used to mark D comes from a file whose own date is after 2026-10-17:

| Input | Vision path | Cadence |
|---|---|---|
| Spot klines | `data/spot/daily/klines/<SYM>/1h/<SYM>-1h-YYYY-MM-DD.zip` | daily files |
| UM perp klines | `data/futures/um/daily/klines/<SYM>/1h/<SYM>-1h-YYYY-MM-DD.zip` | daily files |
| UM funding | `data/futures/um/monthly/fundingRate/<SYM>/<SYM>-fundingRate-YYYY-MM.zip` | monthly files |

Funding settlements are the 8h settlements at 00:00, 08:00 and 16:00 UTC
(three per day). Vision publishes funding **monthly only** — there is no
`data/futures/um/daily/fundingRate/` prefix in the bucket (verified by
listing before this file was written).

**File rule, enforced by refusal, not by convention.** A daily file is
admissible iff its filename date is strictly greater than 2026-10-17. A
monthly file is admissible iff its filename month is strictly greater
than 2026-10. Every input row is additionally required to carry a
timestamp strictly greater than 2026-10-17T00:00:00Z. The recorder
refuses to run, loudly, if any admissible set cannot be formed. It never
"just uses what is available".

### The 14 days this rule costs us

The monthly funding file `2026-10` contains forward-day settlements
(2026-10-18..2026-10-31) but is itself a holdout-dated artifact under
`SPLIT.md` (monthly `<= 2026-10` is holdout). Decoding it would open a
sealed file to serve a forward study. We do not. Therefore:

- **Forward clock day 1 = 2026-11-01**, the first day whose funding comes
  from the `2026-11` monthly file.
- The 14 days 2026-10-18..2026-10-31 are permanently outside this study.
  This is a stated, deliberate cost, not an oversight.

Consequence for timing: the `2026-11` monthly funding file does not exist
until Binance publishes it (after month end). The recorder is catch-up
safe, so it books those days retroactively once the file lands.

## Signal rules (inherited verbatim from C1, cell frozen)

The single confirmation cell is C1's: **k = 1.5, drift_band = 0.05**.
It was fixed in C1 before any data and is not chosen from a ranking here.

- Decision clock: 00:00 UTC daily, one decision per day per symbol.
- A funding settlement is eligible only if its settlement time is
  **strictly before** the decision.
- Trailing funding: median of the 8h funding rate over the previous 7
  days (21 settlements). Annualized trailing carry APR = median_8h x 3 x
  365. Fewer than 21 eligible settlements: no decision (warm-up).
- Round trip RT = 53 bps = 0.0053 identity of B4:
  2x(15 spot taker + 1 spread + 1 slip) + 2x(7.5 perp taker + 1 spread
  + 1 slip). Used only as the hurdle constant below, as in C1. The cost
  actually charged is the model in the next section, which replaces the
  fixed slip term.
- Entry hurdle APR = k x RT x 365 / 7 = 1.5 x 0.0053 x 52.142857 =
  **0.4145357** (41.45% APR, i.e. trailing median 8h rate above 37.86
  bps). Enter a flat symbol when trailing APR > hurdle and median_8h > 0.
- Exit hysteresis: after at least 7 decision days in the position, exit
  when trailing APR < 0.5 x hurdle for 3 consecutive decision days, or
  when median_8h < 0. Maximum hold: none beyond the exit rules (C1
  states no max-hold; the hysteresis is the exit).
- Rebalance: while open, adjust the hedge only when
  |spot notional - perp notional| / equity > 0.05. Otherwise hold
  quantities unchanged.
- Execution: taker at the next 1h bar open after the decision. Both legs
  simultaneously, equal notional at entry (delta-neutral at entry). No
  maker, no holdout.
- Marks: daily at 00:00 UTC from the last 1h close at or before the
  decision time. Funding accrues to the short perp at the observed
  settlements; the spot leg earns none.

### Point-in-time discipline

A decision at 00:00 UTC on day D may use: spot and perp 1h bars whose
open time is < D; funding settlements with time < D. It may not use any
bar, settlement or mark from D or later. The fill is booked at the open
of the first 1h bar at or after D. The evaluator computes the whole
series in one pass over already-downloaded files, and each decision is
asserted to have a timestamp strictly greater than every input it used.

## Cost model (the gate this study actually trades)

All costs are charged in cash against equity, on the notional actually
traded. Nothing is netted, nothing is deferred.

- **Fees and spread, per fill.** Spot taker 15 bps + 1 bp spread = 16
  bps. Perp taker 7.5 bps + 1 bp spread = 8.5 bps. A full round trip on
  one symbol is 2 spot fills + 2 perp fills = 32 + 17 = **49 bps** of
  each leg's notional. (B4's 53 bps minus the 4 bps of fixed 1 bp/fill
  slip floor, which this model replaces with impact — see below.)
- **Per-fill market impact.** `impact = 0.5 * sigma * sqrt(Q / ADV20)`,
  charged in cash as `impact * Q`, where
  - `Q` = the notional of that single fill (per leg per symbol),
  - `ADV20` = trailing 20-day median daily quote volume in USD for that
    symbol on that venue (spot ADV for the spot leg, UM ADV for the perp
    leg), computed only from bars strictly before the decision,
  - `sigma` = trailing 20-day realized daily volatility (std of daily log
    returns, ddof=1) of that symbol on that venue, strictly before the
    decision.
  The 1 bp slip floor is **removed**: a small order pays a small impact,
  not a floor. Impact is charged on entry fills and exit fills alike.
- **Adverse run (2x).** Fee, spread and impact are doubled; funding is
  observed, never doubled. Every gate is reported at 1x and at 2x.
- No borrow cost, no margin interest, no fee tier rebate. If the study
  passes, those are named as unmodelled in the report rather than
  retro-fitted.

The rationale for the impact form: it is the standard square-root law in
its dimensionless form, 0.5 x sigma x sqrt(participation), so a fill at
1% of ADV costs 5% of one daily sigma. It is charged per fill rather than
per round trip, so splitting an order does not escape it.

## Sizing (no turnover cap)

Per symbol, per leg: `Q_leg = min(0.5 * E, 0.01 * ADV20_d)` where E is
current equity and ADV20_d is that venue/symbol's trailing 20-day median
daily quote volume. Gross (all four legs) is therefore at most 2 x E, the
existing gross cap.

- The `0.01 * ADV20` term is the capacity limit: it caps a leg at 1% of
  a day's volume, so impact stays in the small-participation regime where
  the square-root law is calibrated, and it replaces the killed turnover
  budget with a quantity that actually measures market capacity.
- **Realized participation** `Q / ADV20` is recorded for every fill:
  median and maximum across the whole study are reported as gates.
- `slow_stats.capacity_estimate()` is used to report the implied equity
  at which the 1% participation cap starts to bind. That is the capacity
  answer the old turnover number could never give.
- **There is no turnover cap and no turnover gate.** Turnover is
  reported, never gated.

## Gates (all must pass; a miss is KILLED)

Capital base: E0 = 1,000 USDT (the Family B dev convention). Daily net
simple returns of the marked book.

| # | Gate | Threshold |
|---|---|---|
| 1 | Net Sharpe, annualized (365) | >= 0.70 |
| 2 | Net Sharpe at 2x cost | > 0.30 |
| 3 | Deflated Sharpe, N = 10 trials | >= 0.80 |
| 4 | PBO (CSCV) | <= 0.30 |
| 5 | Max drawdown | <= 35% |
| 6 | Positive years | >= 2 |
| 7 | Median participation | <= 1% of ADV20 |
| 8 | Max participation | <= 5% of ADV20 |
| 9 | 30-day block bootstrap, one-sided 80% lower bound on mean daily net return | > 0 |
| 10 | Newey-West t-stat of mean daily net return, lag 30 | >= 2.0 |

Gate 3 trial count: **N = 10** is every B4/B4b cell ever run, not a
number picked to flatter this study — the 9 dev cells decoded in
`research/autopilot_b/dev/B4.json` plus this one forward cell. The trial
Sharpe vector for the deflated-Sharpe expected maximum is those 9 dev
cell Sharpes plus the B4b forward Sharpe.

Gate 3 also uses an **autocorrelation-adjusted effective sample size**,
because the B4b daily series is mostly exact zeros and strongly
autocorrelated. The naive n = number of days overstates confidence; the
fixed `slow_stats.deflated_sharpe` now estimates n_eff from the
Newey-West variance inflation with a 30-day lag window (Bartlett
weights), and takes the smaller of that and the holding-period
estimate `n / mean_hold_days`. This is a statistics repair made before
the forward read and applied to all studies, not a thumb on B4b's scale.

### Gates that cannot be assessed early, stated before the fact

Two gates are structurally not computable on a short sample. They are
recorded as `null` and the verdict is capped at UNDERPOWERED — never
silently passed:

- **Gate 6 (>= 2 positive years):** needs 2 calendar years with at least
  60 forward days each. Under the 2026-11-01 clock that becomes
  assessable on 2028-12-31 at the earliest.
- **Gate 4 (PBO):** CSCV needs a cross-section of competing trials on a
  common timeline. This study scores exactly one preregistered cell
  forward; one cell has no IS/OOS ranking to invert. PBO is therefore
  `null` here, and the selection penalty it is meant to impose is
  carried by gate 3, whose expected-maximum term is the same
  multiple-testing correction in deflated-Sharpe form, at N = 10. If this
  runner were ever pointed at more than one cell, PBO becomes a hard
  gate. This is a stated limitation of a single-cell forward study, not a
  gate removed to make passing easier.

## Stopping rule (one look, no peeking)

- **UNDERPOWERED** until BOTH: (a) >= 90 forward days, and (b) >= 20
  completed round trips. A round trip is one open-and-closed position in
  one symbol.
- The verdict fires **once**, on the first run where both conditions
  hold. The evaluator writes the verdict JSON and refuses to overwrite a
  non-UNDERPOWERED verdict; a second look requires a new prereg.
- Nothing else is a verdict: 90 days with 12 round trips stays
  UNDERPOWERED and the recorder says how many of each it still needs.
- A PASS is a pass of *this* cell on forward data. It authorizes a paper
  phase (`FORWARD_PAPER`), not capital.

### Known timing risk, stated now

The entry hurdle is trailing APR > 41.45%. That is a genuinely rich
funding regime; long stretches of ordinary funding will simply keep the
book flat, and flat days are many exact zeros. The binding constraint is
therefore likely to be 20 round trips, not 90 days. If so, the honest
answer is that the study is waiting on regime, not on plumbing, and the
recorder reports the gap explicitly each run instead of scoring early.

## What this study may NOT do

- It may not read, decode or reference any holdout file, including the
  `2026-10` monthly funding file.
- It may not reuse, rescore or restate any B4 dev or void-screen result
  as forward evidence. B4's dev numbers appear in this file only as the
  reason the study exists and as the DSR trial vector.
- It may not add cells, symbols, parameters or variants after seeing
  forward data.
- It may not drop, soften or reinterpret a gate after seeing forward
  data. A gate that cannot be computed is `null`, and `null` never means
  pass.
- It may not report a return series it did not compute from files that
  passed checksum verification.

## Failure modes

- **F1** Basis regime where funding stays rich but spot lags perp on
  spikes: the hedge leaks delta exactly when it matters, and the leak
  shows up as drawdown, not as funding.
- **F2** Negative-flip whipsaw: the hysteresis band is entered and
  exited repeatedly and the 49 bps plus impact is paid each time.
- **F3** Regime absence: funding never clears 41.45% APR, the book sits
  in cash, and the study is correctly UNDERPOWERED for a long time. This
  is a finding about the regime, not a defect of the runner.
- **F4** Impact understatement: participation is capped at 1% ADV, so
  this study cannot speak to size far above that. Capacity beyond the
  cap is unmeasured, by construction.
