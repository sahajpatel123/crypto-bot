# F-CARRY — Forward funding/basis carry, lower-hurdle sibling study (six cells, one look)

Status: FROZEN-BEFORE-ANY-FORWARD-READ once committed. Family F, hypothesis 1,
six cells, one look. This draft is not frozen until committed; no forward return
has been pulled, computed, or looked at, and none may be until the freeze commit.
Revision: draft rev 2 — review fixes C1/C2/C3 and advisory C4 applied per the
independent review gate; still DRAFT-NOT-FROZEN.

Predecessors: research/prereg/B4-delta-neutral-basis.md (KILLED on turnover;
stays KILLED), research/prereg/C1-b4b-carry.md (pre-authorized rule set),
research/prereg/B4b-forward-basis.md (the k=1.5 single-cell forward test, live
and untouched). Holdout is BURNED for B4 and every B4 variant including
F-CARRY (release/holdout-reconcile.json). No B4 result is reused or re-scored
here except as DSR trial-vector entries, which is a penalty, not evidence.

## Why this study exists, and why it is not part of B4b

B4b tests exactly one cell (k=1.5, both symbols) and forbids adding cells after
seeing forward data. Its entry hurdle, trailing APR above 41.45%, is a rich
regime; B4b's own prereg names regime absence as the likely binding constraint.
F-CARRY asks the adjacent question with no overlap in cells: is the same
delta-neutral carry harvestable at lower funding richness (k=1.0 and k=1.25),
and is it harvestable single-pair (BTC-only, ETH-only) as well as joint? Six
cells, all named here before any forward read.

B4b's turnover-budget audit (D-051) is inherited by reference, not relitigated:
turnover is reported, never gated. This file changes nothing about B4 (KILLED),
B4b (live), or any frozen gate.

## Economic mechanism

Identical to B4/B4b: when trailing perp funding stays above the round-trip cost
of a hedged book, spot-long plus perp-short collects that funding near-zero
delta. Lower k opens the book more often at thinner per-trade margin; the
single-pair splits test whether either leg-pair carries the effect alone (a
capacity and concentration question, decided forward, not by dropping symbols
after the fact).

## Counterparty test

Who loses: leveraged perp longs paying funding, plus impatient basis traders
unwinding early (same pool as B4). Why it could persist: spot/perp segmentation
(margin, custody, venue access) plus structural leverage demand. Why it should
fail: (a) at lower k, whipsaw around the hysteresis band pays 49 bps plus
impact repeatedly against thinner carry; (b) spot/perp flow decoupling leaks
delta exactly when funding is richest; (c) the effect exists only above
B4b-scale richness, in which case the lower-k cells correctly show costs
dominating. A clean KILL is a good outcome.

## Universe (chosen before seeing data)

BTCUSDT and ETHUSDT, the two deepest spot/perp basis markets (liquidity prior,
not a selection on results). Cells split them: BTC-only, ETH-only, or both may
be open. No other symbol can enter; no symbol is added later.

## Data

Forward window only, Binance Vision public archives only. No recorder input; a
stopped recorder does not stall this study. A forward day D (UTC) counts only
if every input marking D comes from a file whose own date is after 2026-10-17:

| Input | Vision path | Cadence |
|---|---|---|
| Spot klines | data/spot/daily/klines/<SYM>/1h/<SYM>-1h-YYYY-MM-DD.zip | daily |
| UM perp klines | data/futures/um/daily/klines/<SYM>/1h/<SYM>-1h-YYYY-MM-DD.zip | daily |
| UM funding | data/futures/um/monthly/fundingRate/<SYM>/<SYM>-fundingRate-YYYY-MM.zip | monthly |

Funding settlements are the 8h settlements at 00:00, 08:00, 16:00 UTC (three
per day). Vision publishes funding monthly only.

File rule (enforced by refusal): a daily file is admissible iff its filename
date is strictly greater than 2026-10-17; a monthly file iff its filename month
is strictly greater than 2026-10. Every row must carry a timestamp strictly
greater than 2026-10-17T00:00:00Z AND fall inside its own file's date window
(daily file: its own UTC day; monthly file: its own month). The runner refuses
to run if no admissible set can be formed; it never uses what is available.

Integrity (both enforced in code): every file checksum-verified against its
published .CHECKSUM on every run including resumed files; a forward day needs
all of its marks (both venues' bars inside the preceding forward day plus a
funding settlement landing in that day) — dropping 10 days of bars lowers the
day count by 10.

### The 14 days this rule costs us

The 2026-10 monthly funding file is holdout-dated under SPLIT.md and is never
decoded. Forward clock day 1 = 2026-11-01. The 14 days 2026-10-18..2026-10-31
are permanently outside this study. The 2026-11 funding file lands after month
end; the runner is catch-up safe and books those days retroactively.

## Signal rules (inherited from C1/B4b; cell parameters frozen here)

- Decision clock: 00:00 UTC daily, one decision per day per symbol in the
  cell's universe. A funding settlement is eligible only if its settlement time
  is strictly before the decision.
- Trailing funding: median of the 8h funding rate over the previous 7 days (21
  settlements). Annualized trailing carry APR = median_8h x 3 x 365. Fewer than
  21 eligible settlements: no decision (warm-up).
- Round trip RT = 53 bps = 0.0053, the B4 identity. Used ONLY as the hurdle
  constant below. Costs actually charged are the cost model in the next
  section.
- Entry hurdle APR = k x RT x 365 / 7. Enter a flat symbol when trailing APR >
  hurdle and median_8h > 0:
  - k=1.0: hurdle 0.2763571 = 27.64% APR (trailing median 8h rate above 2.52 bps)
  - k=1.25: hurdle 0.3454464 = 34.54% APR (trailing median 8h rate above 3.16 bps)
- Gloss note: the trailing-median-8h bps figures above (2.52 / 3.16) correct a
  10x gloss error inherited from frozen B4b (:149 prints 37.86 bps where the
  correct figure is 3.79 bps, per independent review); the executable APR
  hurdles are unchanged and B4b itself is not touched.
- Exit hysteresis: after at least 7 decision days in the position, exit when
  trailing APR < 0.5 x hurdle for 3 consecutive decision days, or when
  median_8h < 0. Maximum hold: none beyond the exit rules.
- Rebalance: while open, adjust the hedge only when |spot notional - perp
  notional| / equity > 0.05 (drift_band FIXED at 0.05, not gridded, to cap the
  trial count). Otherwise hold quantities unchanged.
- Execution: taker at the next 1h bar open after the decision, both legs
  simultaneously, equal notional at entry. No maker, no holdout.
- Marks: daily at 00:00 UTC from the last 1h close at or before decision time.
  Funding accrues to the short perp at observed settlements; spot earns none.

### Accounting identity (fixed before any forward read)

E = cash + qty_spot * spot_mark. The spot leg is a held asset: its P&L is the
mark, never also accrued into cash. Only the perp moves cash: at each daily
mark by qty_perp * (mark_now - mark_prev), and at every fill to that fill's own
price. With equal marks and qty_spot == qty_perp, E_t = E0 + funding - costs
for the whole hold — asserted in tests for trend +1%/day, 0, and -1%/day.

### Point-in-time discipline

A decision at 00:00 UTC on day D may use: spot/perp 1h bars with open time < D;
funding settlements with time < D. Nothing from D or later. Fill booked at the
open of the first 1h bar at or after D. Each decision asserted strictly greater
in timestamp than every input it used.

## Cost model (identical to B4b; the gate this study trades)

Charged in cash against equity, on notional actually traded. Nothing netted.

- Fees and spread per fill: spot taker 15 bps + 1 bp spread = 16 bps; perp
  taker 7.5 bps + 1 bp spread = 8.5 bps. Full round trip per symbol = 2 spot +
  2 perp fills = 49 bps of each leg's notional. (B4's 53 bps minus the fixed
  slip floor, replaced by impact below.)
- Per-fill market impact: impact = 0.5 * sigma * sqrt(Q / ADV20), charged as
  impact * Q, where Q = single-fill notional per leg per symbol; ADV20 =
  trailing 20-day median daily quote volume (USD) per symbol per venue, strictly
  before the decision; sigma = trailing 20-day realized daily vol (std of daily
  log returns, ddof=1) per symbol per venue, strictly before the decision. No
  slip floor: small orders pay small impact. Charged on entry and exit fills.
- Adverse run (2x): fee, spread, impact doubled; funding observed, never
  doubled. Every gate reported at 1x and 2x.
- No borrow cost, no margin interest, no fee tier rebate. If the study passes,
  those are named as unmodelled, never retro-fitted.

## Sizing (no turnover cap)

Per symbol, per leg: Q_leg = min(0.5 * E, 0.01 * ADV20_d), E = current equity.
Gross (all four legs) at most 2 x E. Realized participation Q/ADV20 recorded
per fill; median and max reported as gates. slow_stats.capacity_estimate()
reports implied equity where the 1% cap binds. No turnover cap; turnover
reported only.

## Parameter grid (6 cells, ALL trials counted)

| k | universe |
|---|---|
| 1.0, 1.25 | BTC-only, ETH-only, BOTH |

2 x 3 = 6 cells. Fixed (not gridded): drift_band 0.05; OI/trailing windows per
rules above; entry/exit/hysteresis/rebalance as written. The grid is frozen; no
cell is added, removed, or re-parameterised after the first forward read. Any
addition is a new preregistration and its cells add to the program trial count.

## Selection rule

Eligible cells: every cell with >= 20 completed round trips (one open-and-close
in one symbol) at look time. Select the eligible cell with the largest 1x net
Sharpe (annualized, 365, on daily net simple returns of its own book from
E0 = 1,000 USDT). Exact Sharpe ties broken by lexicographically smallest
(k, universe) with universe order BTC < ETH < BOTH. All 6 cells reported
whatever the selection. Every gate below applies to the SELECTED cell; any
miss = KILLED.

## Gates (all must pass; a miss is KILLED)

| # | Gate | Threshold |
|---|---|---|
| 1 | Net Sharpe, annualized (365) | >= 0.70 |
| 2 | Net Sharpe at 2x cost | > 0.30 |
| 3 | Deflated Sharpe, N = 16 trials | >= 0.80 |
| 4 | PBO (bespoke CSCV over the 6 cells, procedure below) | <= 0.30, COMPUTED (not null) |
| 4b | Plateau fraction over the 2x3 grid | >= 70%, COMPUTED (not null) |
| 5 | Max drawdown | <= 35% |
| 6 | Positive calendar years (>= 60 forward days each) | >= 2 |
| 7 | Median participation | <= 1% of ADV20 |
| 8 | Max participation | <= 5% of ADV20 |
| 9 | 30-day block bootstrap, one-sided 80% lower bound on mean daily net return | > 0 |
| 10 | Newey-West t-stat of mean daily net return, lag 30 | >= 2.0 |

Gate 3 trial count: N = 16 = 9 B4 DEV cells + 1 B4b forward cell + 6 F-CARRY
forward cells. Every cell ever run on this mechanism counts; the penalty is
strictly harsher than B4b's N=10. The trial Sharpe vector is those 9 DEV cell
Sharpes plus the B4b forward Sharpe plus the 6 F-CARRY forward Sharpes.
Missing-B4b rule (frozen): if B4b has no scored forward Sharpe when F-CARRY
fires (B4b still UNDERPOWERED), the vector's dispersion V is computed over the
15 available Sharpes with q(16) retained — the N penalty stays at 16 and is
never revised down. Limitation disclosed: V over 15 rather than 16 is an
approximation. Report-only sensitivities (computed, never gated): DSR at N=15,
DSR at N=25, and DSR with B4b imputed at min(vector) at N=16 — the adversarial
bound for a would-be-outlier B4b, alongside the N=15/N=25 band.
Gate 3 uses the autocorrelation-adjusted effective sample size (Newey-West
variance inflation, 30-day Bartlett window, min with n/mean_hold_days), the
pre-existing slow_stats.deflated_sharpe repair, not a study-specific choice.
Gate 4 PBO: CSCV over the 6 cells on the full calendar-day series of mean net
daily return (no-trade days = 0), by the bespoke procedure specified HERE,
implemented VERBATIM. Substituting slow_stats.pbo_cscv is FORBIDDEN: it uses
the opposite lambda scale (rank/(k+1), where bad is > 0.5) and different block
edges (i*n//s, which disagrees with array_split — e.g. n=100 gives
[12,13,12,13,...] vs array_split's [13,13,13,13,12,12,12,12]). Procedure: split
chronological calendar days into 8 consecutive partitions with
numpy.array_split semantics (partition sizes differ by at most one day;
remainder days go to the earliest partitions). For each of the 70 ways to
choose 4 partitions in-sample (the other 4 OOS), select the highest in-sample
daily Sharpe, breaking exact ties by lexicographically smallest (k, universe)
with universe order BTC < ETH < BOTH. Let lambda = the number of the other 5
cells with strictly lower OOS Sharpe, divided by 5 (0 = worst, 1 = best). Tie
rules: the selected cell takes the lowest rank within its OOS tie group; tied
cells do not count as lower-scoring competitors; an all-tied OOS set has lambda
= 0. PBO = the fraction of the 70 splits with lambda < 0.5. Deterministic, no
seed. The evaluator ships a hand-worked-example unit test on synthetic 6-cell
data with hand-computed lambdas and PBO asserted exactly — the test must fail
if the bespoke procedure is replaced by pbo_cscv or any other implementation.
Gate 4b plateau: slow_stats.plateau_fraction over the 2x3 grid exactly as
Family B DEV used it; gate >= 70%. Cell keys are (k, universe) tuples with
universe order BTC < ETH < BOTH; Hamming-1 neighbours differ in exactly one
coordinate (the best cell has at most 3 neighbours). The evaluator refuses
(fail-closed) if that function cannot accept this grid shape — the gate is
never silently nulled.

### Gates that cannot be assessed early, stated before the fact

Gate 6 needs 2 calendar years with >= 60 forward days each. Under the
2026-11-01 clock, 2026 supplies 61 forward days and 2027 reaches its 60th on
2027-03-01 = forward day 121. Gate 6 is first assessable at 121 forward days
and BLOCKS a PASS (not structural). Consequence: a 90-day look cannot PASS. The
runner reports years_assessable_from_forward_day / years_assessable_from /
forward_days_to_first_possible_pass in every document. Unlike B4b, PBO and
plateau are COMPUTED here (6 cells exist), so there are no structural nulls.

## Stopping rule (one look, no peeking)

- UNDERPOWERED until BOTH: (a) >= 90 forward days, and (b) >= 20 completed
  round trips in EVERY cell. A round trip is one open-and-closed position in
  one symbol; single-pair cells count only their own symbol.
- The verdict fires ONCE, on the first run where both hold. The evaluator
  writes the verdict JSON and refuses to overwrite a non-UNDERPOWERED verdict; a
  second look requires a new prereg.
- A 90-day look can only KILL (gate 6 unassessable before day 121). Between 90
  and 120 days a non-killing run writes an UNDERPOWERED document naming years
  as the blocking gate; that document is not a verdict and may be rewritten.
- 180-day regime milestone (reporting only, never a verdict): any cell with
  < 20 RTs at 180 forward days is labeled regime-absent; if no cell reaches 20
  RTs by 180 days the study is UNDERPOWERED regime-absent — a finding about the
  regime, not a defect of the runner. Waiting continues; regime absence is
  never converted into a KILL.
- A PASS is a pass of the selected cell on forward data. It authorizes a paper
  phase (FORWARD_PAPER), not capital.

### Known timing risk, stated now

Lower hurdles trade more often than B4b's but still need sustained positive
funding (2.52 / 3.16 bps trailing median 8h). Long ordinary-funding stretches
keep books flat (many exact zeros). The binding constraint may still be 20 RTs
per cell rather than 90 days; the runner reports the per-cell gap each run.

## Trial-count addition

This study adds 6 cells to the program inventory (mechanism-family N rises
10 -> 16 for carry DSR). D1's frozen N_TRIALS=None accounting is unaffected
(separate family convention per D-032; this file neither sets nor implies any
program-wide N). Any future carry sibling adds its cells the same way.

## Evaluator pattern (behavioral spec; implementation follows tools/forward_b4b.py)

- CLI surface: status (prints forward-day count, per-cell RT counts, blocking
  gate, days to first possible PASS; never a verdict before the stopping rule),
  run (one-shot verdict at power; refuses overwrite of a non-UNDERPOWERED
  verdict), verify (recomputes every number from checksummed inputs).
- Every output binds: this prereg's SHA-256, evaluator code SHA-256
  (code_sha256 over its own modules, d1_eval._code_hashes pattern), data
  manifest (file names + CHECKSUM values + row counts), config hash.
- Refusals (fail-closed, loud): any file failing CHECKSUM; any row outside its
  file's date window; any row dated <= 2026-10-17; any B4/B4b number reused as
  evidence; plateau/PBO uncomputable for any reason (refuse, never null).
- Each guard ships with a test that fails when the guard is deleted
  (mutation-proofing, D-056 pattern, minimum: checksum skip, window-violation
  import, stale-mark scoring, turnover-gate reintroduction, DSR N tampering,
  hand-worked PBO example on synthetic 6-cell data with hand-computed lambdas
  and PBO asserted exactly).

## What this study may NOT do

- Read, decode, or reference any holdout file, including the 2026-10 monthly
  funding file. No exception for warm-up, ADV20, or sigma seeding: trailing
  windows use forward data only, and cells simply have no decisions until their
  windows fill.
- Reuse, rescore, or restate any B4 DEV, void-screen, B4b, or C1 result as
  forward evidence. B4/B4b Sharpes appear only inside the DSR trial vector.
- Add cells, symbols, parameters, or variants after seeing forward data — to
  this study or to B4b. B4b stays exactly one cell.
- Drop, soften, or reinterpret a gate after seeing forward data. Uncomputable =
  null = never pass (and for PBO/plateau here, uncomputable = refuse).
- Report a return series not computed from checksum-verified files.
- Run before this prereg is committed. Any run against a draft is VOID.

## Failure modes

- F1 Basis decoupling: funding rich but spot lags perp on spikes; hedge leaks
  show as drawdown, not carry.
- F2 Whipsaw (amplified at lower k): hysteresis entered/exited repeatedly, 49
  bps + impact paid each cycle against thinner carry. This is the expected way
  lower-k cells die; the 2x gate prices it.
- F3 Regime absence: funding never clears even 27.64% APR; books sit in cash;
  correctly UNDERPOWERED, possibly for a long time.
- F4 Impact understatement above the cap: participation capped at 1% ADV, so
  size far above that is unmeasured by construction.
- F5 Selection overfit across 6 cells on one shared window: mitigated by DSR
  N=16 + real PBO + real plateau + the years gate; the selection rule is
  frozen and the unselected cells stay in the report.

## Knowledge-contamination note

Same background as B4 (recalled rich 2021 funding, flat 2023). Avoidance: k
values are round multiples of measured cost (1.0x, 1.25x of 53 bps), not
recalled funding levels; universe splits are the liquidity prior (the two
deepest pairs, alone and joint); holds/exits/rebalance inherited unchanged; no
date-conditioned rules; no forward file existed when the grid was fixed
(2026-11 funding unpublished). No return, volatility, count, or P&L was
computed from any forward-dated file.
