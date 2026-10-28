# V-REG — Forward volatility-spike fade on majors (six cells, one look)

Status: FROZEN-BEFORE-ANY-FORWARD-READ once committed. Family V, hypothesis 1,
six cells, one look. This draft is not frozen until committed; no forward return
has been pulled, computed, or looked at, and none may be until the freeze commit.
Revision: draft rev 2 — review fixes M1/M2/M3/M4/M5 applied per the independent
review; still DRAFT-NOT-FROZEN.

Predecessors and boundary: research/prereg/B4-delta-neutral-basis.md (KILLED),
research/prereg/B4b-forward-basis.md (live), research/prereg/F-carry-forward.md
(frozen) are untouched; this study shares no signal, position, or verdict with
any of them. Adverse program history, disclosed as LOW prior rather than hidden:
B5 extreme-move reversion KILLED at daily resolution, H2 trend/vol-regime
KILLED on multi-year unseen history, H6 vol-shock filter signal-dead. V-REG
differs from all three on trigger (vol-expansion ratio, not price distance /
trend rule / filter overlay), resolution (daily decisions on 1h bars), universe
(BTC/ETH majors only), and execution (directional perp with funding charged).
D1 (OI-flush fade, unevaluated) is the intellectual cousin at 5m with an OI
trigger; V-REG reuses nothing from D1 and evades nothing of its fail-closed DSR
— V-REG carries its own trial count, specified below.

## Why this study exists

No program study tests a volatility mechanism standalone on forward data: H2 is
dead, H6 never fired, B5 died on a price trigger, D1 cannot run. V-REG asks one
self-contained question: after trailing volatility on a major explodes relative
to its own history, does fading the accompanying move earn positive expectancy
net of full costs? Prior: LOW (per the kills above). A clean KILL is a good
outcome. This is NOT a filter on carry or momentum legs: it has its own entry,
its own book, its own P&L, and passes or dies on its own gates with no other
study required to validate first.

## Economic mechanism

A volatility spike on a major marks stress: liquidations, margin calls, and
panic de-risking push price through a thin book. Once the forced flow exhausts,
liquidity replenishes and price partially reverts. V-REG sells the panic top
(short after up-spikes) and buys the fear bottom (long after down-spikes),
holding days not minutes. The trigger is vol EXPANSION (short-horizon realized
vol over long-horizon realized vol), so entries fire on regime stress whether
or not the price move alone looks extreme.

## Counterparty test

Who loses: liquidated leveraged traders, panic sellers/buyers, and forced
de-riskers who transact during the spike at any price. Why it could persist:
forced flow ignores price by construction, and only balance-sheet
liquidity providers absorb it. Why it should fail: (a) spikes that are informed
or trend-starting continue through the hold (fade into a trend); (b) the
round-trip cost plus impact approaches the expected reversion on majors; (c)
volatility expands without directional dislocation (choppy-flat stress), in
which case fades trade noise. B5's daily-reversion kill is the standing
evidence for (b)/(c).

## Universe (chosen before seeing data)

BTCUSDT and ETHUSDT, fixed BOTH-symbols book (every cell may hold both; no
universe splits — single-pair questions are reported diagnostics, not cells, to
hold the trial count at 6). The two deepest perp markets; liquidity prior, not
a selection on results. No other symbol can enter.

## Data

Forward window only, Binance Vision public archives only. No recorder input; a
stopped recorder does not stall this study. Spot files are NOT inputs
(perp-only execution). A forward day D (UTC) counts only if every input marking
D comes from a file whose own date is after 2026-10-17:

| Input | Vision path | Cadence |
|---|---|---|
| UM perp klines | data/futures/um/daily/klines/<SYM>/1h/<SYM>-1h-YYYY-MM-DD.zip | daily |
| UM funding | data/futures/um/monthly/fundingRate/<SYM>/<SYM>-fundingRate-YYYY-MM.zip | monthly |

Funding settlements are the 8h settlements at 00:00, 08:00, 16:00 UTC. Vision
publishes funding monthly only.

File rule (enforced by refusal): a daily file is admissible iff its filename
date is strictly greater than 2026-10-17; a monthly file iff its filename month
is strictly greater than 2026-10. Every row must carry a timestamp strictly
greater than 2026-10-17T00:00:00Z AND fall inside its own file's date window.
The runner refuses to run if no admissible set can be formed; it never uses
what is available.

Integrity (both enforced in code): every file checksum-verified against its
published .CHECKSUM on every run including resumed files; a forward day needs
all of its marks (perp 1h bars inside the preceding forward day plus a funding
settlement landing in that day) — dropping 10 days of bars lowers the day
count by 10.

### The 14 days this rule costs us

The 2026-10 monthly funding file is holdout-dated under SPLIT.md and is never
decoded — no exception for warm-up, RV seeding, ADV20, or sigma. Forward clock
day 1 = 2026-11-01. The 14 days 2026-10-18..2026-10-31 are permanently outside
this study. The 2026-11 funding file lands after month end; the runner is
catch-up safe.

## Signal rules (frozen here)

Definitions on UM perp 1h bars (P(t) = close of the bar with open time t):
- h-returns: r(t) = ln(P(t)/P(t-1h)) over consecutive closes.
- RV_short(D) = sample std (ddof=1) of h-returns over the 120h strictly before
  decision day D (5d window). RV_long(D) = sample std (ddof=1) over the 1440h
  strictly before D (60d window). Require >= 95% of nominal bars present in
  each window and RV_long > 0, else no decision for that symbol that day.
- Ratio(D) = RV_short(D) / RV_long(D).
- TR(D) = trailing 120h log return = ln(P(last close before D)/P(first close of
  window)).

Rules:
- Decision clock: 00:00 UTC daily, one decision per day per symbol.
- Entry: if Ratio(D) >= R and the symbol is flat (no open V-REG position),
  schedule a taker entry at the open of the first 1h bar at or after D.
  Direction fades the trailing move: TR(D) < 0 -> LONG; TR(D) > 0 -> SHORT;
  TR(D) == 0 exactly -> no trade. Both sides pooled in every statistic;
  per-side counts and expectancies reported but never gated (no side selection).
- Exit: time exit only. H decision-days after the entry day, taker at the open
  of the first 1h bar at or after D_entry + H days. No stop, no target, no
  re-entry on the same event. One position per symbol at a time: a signal on a
  symbol holding a position is ignored.
- Same-day sequencing: on each decision day D, scheduled exits process before
  entries are evaluated, so a symbol whose position exits on D is flat for D's
  decision and IS eligible for a new entry at D.
- Warm-up consequence (stated now): RV_long needs ~60 forward days of bars, so
  first decisions fall around 2026-12-31. Days before that count as forward
  days (data present) with no decisions (windows unfilled).

## Parameter grid (6 cells, ALL trials counted)

| vol-ratio R | hold H (decision-days) |
|---|---|
| 1.5, 2.0, 2.5 | 2, 5 |

3 x 2 = 6 cells. Fixed (not gridded): RV windows 120h/1440h; 95% bar-presence
rule; universe BOTH; fade direction rule; one-position-per-symbol; time exit
only. The grid is frozen; no cell is added, removed, or re-parameterised after
the first forward read. Any addition is a new preregistration and its cells add
to the program trial count.

### Accounting identity (fixed before any forward read)

Perp-only book: equity is cash (variation margin settles). Cash moves at each
daily 00:00 UTC mark by qty * (mark_now - mark_prev) and at every fill to that
fill's own price. With entry and exit marks equal, E_t = E0 + funding - costs
exactly — asserted in tests on a flat-mark fixture. Funding accrues per the
cost model below.

### Point-in-time discipline

A decision at 00:00 UTC on day D may use: perp 1h bars with open time < D;
funding settlements with time < D. Nothing from D or later. Fill booked at the
open of the first 1h bar at or after D. Each decision asserted strictly greater
in timestamp than every input it used.

## Cost model (perp-only honest costing; deviation accepted per review)

Charged in cash against equity, on notional actually traded. Nothing netted.
- Fees and spread per fill: perp taker 7.5 bps + 1 bp spread = 8.5 bps per
  side. Round trip = entry + exit fills = 17 bps of position notional, plus
  per-fill impact on both fills.
- Per-fill market impact: impact = 0.5 * sigma * sqrt(Q / ADV20), charged as
  impact * Q, where Q = single-fill notional; ADV20 = trailing 20-day median
  daily quote volume (USD) on UM for that symbol, strictly before the decision;
  sigma = trailing 20-day realized daily vol (std of daily log returns, ddof=1)
  on UM, strictly before the decision. No slip floor. (ADV20/sigma warm-up is
  covered by the 60d RV warm-up; decisions need all windows filled.)
- Funding: charged at every UTC settlement (00:00/08:00/16:00) with entry_time
  < settlement <= exit_time. LONG pays +rate, SHORT receives it (cost =
  s_pay * rate * 1e4 bps, s_pay = +1 LONG / -1 SHORT). Missing settlement
  record: charge an adverse debit = largest absolute funding rate for that
  symbol observed SO FAR in the forward window (point-in-time), both sides pay,
  flagged imputed_funding, doubled at 2x. Never book missing funding as zero.
  If no funding rate has been observed yet for the symbol when an imputation is
  required, the imputation is REFUSED and the affected forward day cannot count
  (dropped from the day count, never scored with zero funding) — fail-closed.
- Adverse run (2x): fee, spread, impact doubled; funding debits doubled and
  funding credits set to zero. Every gate reported at 1x and 2x.
- No borrow cost, no margin interest, no fee tier rebate. If the study passes,
  those are named as unmodelled, never retro-fitted.
- DEVIATION BOX (accepted per independent review; was the sole template
  deviation): the F-CARRY template's 49 bps RT is the FOUR-leg delta-neutral
  round trip (2x16 spot + 2x8.5 perp). V-REG executes ONE perp leg (two fills =
  17 bps + impact). Charging 49 bps would misstate this study's own economics
  by ~3x and could kill a real edge on fictitious costs. This prereg therefore
  charges actual fills per the repo's own principle (B4b-forward-basis.md:193:
  "the gate this study actually trades"). Thresholds are NOT loosened — all 10
  gates below are identical to F-CARRY's. The 49bps-conservative-bound fallback
  noted in rev 1 is WITHDRAWN following the reviewer's accept ruling.

## Sizing (no turnover cap)

Per position: Q = min(0.5 * E, 0.01 * ADV20_d), E = current equity. Gross
across both symbols at most 1.0 x E. Realized participation Q/ADV20 recorded
per fill; median and max reported as gates. slow_stats.capacity_estimate()
reports implied equity where the 1% cap binds. No turnover cap; turnover
reported only. Per-symbol P&L split and each-symbol-alone expectancy reported
as diagnostics (ungated).

## Selection rule

Eligible cells: every cell with >= 20 completed round trips at look time.
Select the eligible cell with the largest 1x net Sharpe (annualized, 365, on
daily net simple returns of its own book from E0 = 1,000 USDT). Exact Sharpe
ties broken by lexicographically smallest (R, H). All 6 cells reported whatever
the selection. Every gate below applies to the SELECTED cell; any miss = KILLED.

## Gates (all must pass; a miss is KILLED)

| # | Gate | Threshold |
|---|---|---|
| 1 | Net Sharpe, annualized (365) | >= 0.70 |
| 2 | Net Sharpe at 2x cost | > 0.30 |
| 3 | Deflated Sharpe, N = 6 trials | >= 0.80 |
| 4 | PBO (bespoke CSCV over the 6 cells, procedure below) | <= 0.30, COMPUTED |
| 4b | Plateau fraction over the 3x2 grid | >= 70%, COMPUTED |
| 5 | Max drawdown | <= 35% |
| 6 | Positive calendar years (>= 60 forward days each) | >= 2 |
| 7 | Median participation | <= 1% of ADV20 |
| 8 | Max participation | <= 5% of ADV20 |
| 9 | 30-day block bootstrap, one-sided 80% lower bound on mean daily net return | > 0 |
| 10 | Newey-West t-stat of mean daily net return, lag 30 | >= 2.0 |

Gate 3 trial count: N = 6 = the 6 V-REG forward cells (own mechanism family).
Justification, pre-committed: forward-only disjoint data (nonexistent at
prereg) + disjoint rules, per the D-032 separate-family precedent — the same
basis on which B4b counts N=10 (own mechanism) rather than program-wide
hundreds. The adverse H/B history (B5, H2, H6) is disclosed as LOW prior, not
counted as trials: their unrun cells have no Sharpe vectors, and inflating N
without vector entries would require inventing Sharpes — exactly what
D1-amendment-3 forbids. The trial Sharpe vector is the 6 V-REG forward cell
Sharpes, all scored at look (the stopping rule guarantees >= 20 RTs per cell,
so no missing-cell case arises). Report-only sensitivities (computed, never
gated): DSR at N=12 and N=25.
Gate 3 uses the autocorrelation-adjusted effective sample size (Newey-West
variance inflation, 30-day Bartlett window, min with n/mean_hold_days), the
pre-existing slow_stats.deflated_sharpe repair.
Gate 4 PBO: bespoke procedure implemented VERBATIM (same text as F-CARRY Gate
4, which the reviewer verified): split chronological calendar days into 8
consecutive partitions with numpy.array_split semantics (sizes differ by at
most one day; remainder to earliest); all 70 C(8,4) 4-vs-4 splits; select
highest in-sample daily Sharpe per split (ties: smallest (R, H)); lambda =
number of the other 5 cells with strictly lower OOS Sharpe / 5; selected cell
takes lowest rank within OOS ties; ties do not count as lower; all-tied OOS =>
lambda 0; PBO = fraction of splits with lambda < 0.5. Deterministic, no seed.
Substituting slow_stats.pbo_cscv is FORBIDDEN (opposite lambda scale,
different block edges). Hand-worked-example unit test on synthetic 6-cell data
required, with hand-computed lambdas/PBO asserted exactly.
Gate 4b plateau: slow_stats.plateau_fraction over the 3x2 grid exactly as
Family B DEV used it; gate >= 70%. Cell keys are (R, H) tuples; Hamming-1
neighbours differ in exactly one coordinate. Fail-closed refusal if the
function cannot accept this grid shape — never silently nulled.

### Gates that cannot be assessed early, stated before the fact

Gate 6 needs 2 calendar years with >= 60 forward days each. Under the
2026-11-01 clock: 2026 supplies 61 forward days, 2027 reaches its 60th on
2027-03-01 = forward day 121. Gate 6 is first assessable at 121 forward days
and BLOCKS a PASS (not structural). Consequence: a 90-day look cannot PASS. The
runner reports years_assessable_from_forward_day / years_assessable_from /
forward_days_to_first_possible_pass in every document. PBO and plateau are
COMPUTED (6 cells exist); no structural nulls.

## Stopping rule (one look, no peeking)

- UNDERPOWERED until BOTH: (a) >= 90 forward days, and (b) >= 20 completed
  round trips in EVERY cell.
- Immediate-kill rule (D1 pattern, pre-committed), evaluated exactly ONCE at
  the first run where BOTH power conditions hold, before gates 1-10, and never
  before power (never on thin pre-power data): for each cell i, compute
  GROSS_i = arithmetic mean over that cell's completed round trips (both
  symbols and both sides pooled; open positions excluded) of gross trade return
  in bps of position notional, where one trade's gross = 10^4 * s *
  (P_exit/P_entry - 1) with s = +1 LONG / -1 SHORT and no costs; and ALLIN_i =
  arithmetic mean over the SAME round trips of all-in cost in bps of position
  notional (fees + spread + impact on both fills + signed funding cost with
  adverse imputation where applied). Denominator for both means = the cell's
  completed-round-trip count. If max_over_cells(GROSS_i - ALLIN_i) < 0, V-REG
  is KILLED immediately: no further gate evaluated, no parameter changed, no
  subset re-examined. A kill here is a verdict (written once, never overwritten).
- The verdict fires ONCE, on the first run where power holds and the
  immediate-kill does not trigger. The evaluator writes the verdict JSON and
  refuses to overwrite a non-UNDERPOWERED verdict; a second look needs a new prereg.
- A 90-day look can only KILL (gate 6 unassessable before day 121). Between 90
  and 120 days a non-killing run writes an UNDERPOWERED document naming years
  as the blocking gate; not a verdict; may be rewritten.
- 180-day regime milestone (reporting only, never a verdict): any cell with
  < 20 RTs at 180 forward days is labeled regime-absent; if no cell reaches 20
  RTs by 180 days the study is UNDERPOWERED regime-absent — a finding, not a
  defect. Waiting continues.
- A PASS is a pass of the selected cell on forward data. It authorizes a paper
  phase (FORWARD_PAPER), not capital.

### Known timing risk, stated now

The 60d RV warm-up means first decisions only around 2026-12-31 — 30 decision
days before the 90-day mark (2027-01-29). Vol spikes severe enough to clear
R >= 1.5 on majors may arrive a few times a year or cluster in crises; the
binding constraint is very likely 20 RTs per cell, not 90 days. The runner
reports the per-cell gap each run instead of scoring early.

## Trial-count addition

This study adds 6 cells to the program inventory as new mechanism family V
(DSR N=6 own-family, see Gate 3). D1's frozen N_TRIALS=None accounting is
unaffected (separate family convention per D-032). B4/B4b/F-CARRY counts and
vectors are untouched. Any future vol sibling adds its cells the same way.

## Evaluator pattern (behavioral spec; implementation follows tools/forward_fcarry.py)

- CLI surface: status (forward-day count, per-cell RT counts, blocking gate,
  days to first possible PASS; never a verdict before the stopping rule), run
  (one-shot verdict at power; refuses overwrite of a non-UNDERPOWERED verdict),
  verify (recomputes every number from checksummed inputs).
- Every output binds: this prereg's SHA-256, evaluator code SHA-256
  (code_sha256 over its own modules, d1_eval._code_hashes pattern), data
  manifest (file names + CHECKSUM values + row counts), config hash.
- Refusals (fail-closed, loud): any file failing CHECKSUM; any row outside its
  file's date window; any row dated <= 2026-10-17; any B4/B4b/F-CARRY/H/B/D1
  number reused as evidence; plateau/PBO uncomputable (refuse, never null);
  any decision using a bar or settlement not strictly before its decision day.
- Each guard ships with a test that fails when the guard is deleted
  (mutation-proofing, D-056 pattern, minimum: checksum skip, window-violation
  import, stale-mark scoring, lookahead RV window, turnover-gate introduction,
  DSR N tampering, hand-worked PBO example on synthetic 6-cell data).

## What this study may NOT do

- Read, decode, or reference any holdout file, including the 2026-10 monthly
  funding file. No exception for warm-up, RV/ADV20/sigma seeding, or funding
  imputation baselines: trailing windows use forward data only.
- Condition on, filter, or select by any carry, momentum, funding-level, or
  other study's signal. V-REG entries derive ONLY from the vol-ratio + trailing
  return rules above.
- Reuse, rescore, or restate any B4/B4b/F-CARRY/H/B/C/D1 result as evidence.
  No external Sharpe enters the DSR vector.
- Add cells, symbols, parameters, or variants after seeing forward data — to
  this study or any other.
- Drop, soften, or reinterpret a gate after seeing forward data. Uncomputable =
  null = never pass (and for PBO/plateau, uncomputable = refuse).
- Report a return series not computed from checksum-verified files.
- Run before this prereg is committed. Any run against a draft is VOID.

## Failure modes

- F1 Informed continuation: spikes that start trends run through the hold; the
  fade adds losers to a trend. Shows as negative expectancy + failed years gate.
- F2 Whipsaw costs: repeated spike entries in choppy stress pay 17 bps +
  impact each cycle against thin reversions. The 2x gate prices this.
- F3 Regime absence: majors stay calm or spikes never clear R=1.5; books flat;
  correctly UNDERPOWERED, possibly for a long time.
- F4 Impact understatement above the cap: participation capped at 1% ADV.
- F5 Selection overfit across 6 cells on one shared window: mitigated by DSR
  N=6 + real PBO + real plateau + years gate + immediate-kill; unselected cells
  stay in the report.
- F6 Directionless volatility: ratio fires on choppy-flat stress where the
  trailing-return sign is noise; fades trade randomness. Indistinguishable from
  F1 ex ante — the verdict decides.

## Knowledge-contamination note

Same background as B4/H2/B5 (recalled rich funding, recalled 2021 trends,
recalled crash reversals). Avoidance: R values are round multiples (1.5/2.0/
2.5x own history), H values are 2/5-day conventions, RV windows are 5d/60d
conventions; no recalled "vol above X means fade" number; direction is the
frozen fade rule, not a fitted sign; no date, event, or symbol named in any
rule; no forward file existed when the grid was fixed (2026-11 funding
unpublished). No return, volatility, count, or P&L was computed from any
forward-dated file. The B5/H2 kills are the reason the prior is LOW, stated
here rather than discovered later.
