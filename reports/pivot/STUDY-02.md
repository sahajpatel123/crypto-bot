# STUDY-02 — P2/P3 economics screen on the frozen 30-day benchmark (NOT a strategy)

Status: **PREREGISTERED — RUN — descriptive result.** Hypothesis + method frozen in
`reports/pivot/study02-prereg.json` (commit `3811afe`) BEFORE any outcome was
computed; the tool + 17 unit tests landed pre-run (`1f2ca3c`); results filled
below, method untouched. This study creates **no strategy, no candidate,
consumes no PIVOT-01 attempt budget**, and claims no profit. It answers one
question with repo bytes: **do the P2 (funding carry) and P3 (4h+ swing)
families have economics that justify the owner's 10-day-capture decision?**

Author: independent 4th agent (owner-directed). Filed to manager for review.
Lane discipline: no worker-lane files touched; new files only
(`tools/pivot_study_02_carry_swing.py`, `tests/unit/test_pivot_study02.py`,
this report, the prereg, the results JSON).

## Data (frozen)

- `datasets/benchmark_30d.toml` manifest `9008ba92` (transform v2 causal),
  window 2026-09-11 → 2026-10-11 UTC, 8 symbols.
- 1m closes built causally from aggTrade parquet (last trade per minute;
  missing minutes stay missing). 1h closes = last trade of each hour.
- Settlement-grade funding parquets (REST `v1/fundingInfo` reconciled vs
  Vision, 0 mismatches): BTC/ETH full window (90 settlements each in-window);
  other 6 symbols September-only (manifest gap kind `funding-terms-absent`).
- Costs: cost-contract-v1, **26 bps taker RT** charged once per round trip.

## Deviation disclosure (before the results, for honesty)

Run 1 exposed an implementation bug: the one-position budget was shared
across hold lengths within a side, suppressing every long-hold cell
(overlaps counted, entries 0). The prereg's P2 wording is explicit —
"of the same cell" — so the fix (per-cell tracking) aligns the tool WITH the
frozen contract; P3's wording ("per (symbol, side)") was ambiguous and was
implemented per-cell for consistency, disclosed here. Run 1 was examined only
to diagnose that bug (empty cells + overlap counts); no threshold, window, or
convention was changed after seeing any economics. Tests re-run green; results
below are from run 2.

## RESULTS (run 2; method above untouched)

### P2 — funding carry, perp-only approximation

Funding settlements (BTC/ETH, full window):

| Metric | BTCUSDT | ETHUSDT |
|---|---|---|
| Settlements in window | 90 | 90 |
| Mean rate | 0.399 bp/8h | 0.402 bp/8h |
| Median rate | 0.420 bp/8h | 0.479 bp/8h |
| Fraction positive | 0.86 | 0.87 |
| **Annualized mean yield** | **4.37%** | **4.41%** |
| Funding per day | 1.20 bp | 1.21 bp |
| **Breakeven hold (one 26bp taker RT)** | **21.7 days** | **21.5 days** |
| Persistence (trail-3 mean vs next, Pearson) | 0.997 | 0.997 |
| Sign-match rate | 0.98 | 0.97 |

Signal cells (trigger: trailing-3 mean ≥ +1bp → SHORT / ≤ −1bp → LONG; T = the
venue baseline 0.01%/8h, declared a priori):

| Cell | sig | ent | net_mean | funding | price |
|---|---|---|---|---|---|
| BTC SHORT 8h | 2 | 2 | −78.61 | +0.59 | −53.19 |
| BTC SHORT 24h | 2 | 1 | −208.01 | +2.17 | −184.18 |
| BTC SHORT 72h | 2 | 1 | −750.64 | +4.90 | −729.54 |
| BTC SHORT 168h | 2 | 1 | −564.69 | +7.11 | −545.80 |
| ETH SHORT 8h | 1 | 1 | +16.45 | +1.00 | +41.45 |
| ETH SHORT 24h | 1 | 1 | +94.76 | +1.76 | +119.00 |
| ETH SHORT 72h | 1 | 1 | −413.71 | +6.42 | −394.13 |
| ETH SHORT 168h | 1 | 1 | −207.35 | +13.00 | −194.35 |
| BTC/ETH LONG (all holds) | 0 | 0 | — | — | — |

- **The LONG arm never triggered**: sustained negative funding (trailing-3
  mean ≤ −1bp) did not occur once in 30 days (funding 86–87% positive).
- The two positive cells are **n=1 each** — no inference possible, reported
  because the frozen rule reads literally, weighted accordingly.
- In every entered cell the funding component (≤ 13bp) is one to two orders
  of magnitude smaller than the price component (tens to hundreds of bps).
  Perp-only "funding-tilt" is a directional bet with a tiny carry kicker —
  not carry.
- Post-hoc sensitivity (labeled, BTC/ETH only): T=0.5bp → 31–33 entries, all
  net-negative (−32 to −409bp); T=2.0bp → ~0 entries. Conclusion is
  threshold-robust.

**H-02 verdict: perp-only taker funding-tilt REJECTED on this data and on
arithmetic** (breakeven hold 21.7d > 7d threshold; every multi-trade cell
net-negative; price risk dominates funding by 1–2 orders of magnitude).
The funding ENGINE is real (4.4% annualized, highly persistent) but small:
capturing it requires the **delta-neutral spot+perp book held for weeks**
(breakeven ~22 days, then ~4.4%/yr net of one RT), which needs **spot-leg
data — Vision free archives — and NOT the 10-day tick capture**. A separate
$0 study (spot basis + funding) is the correct next step if P2 is pursued.

### P3 — 4h+ swing, volatility-vs-cost arithmetic and continuation

Arithmetic screen (1h closes, all 8 symbols; BTC/ETH shown):

| Symbol | h | stdev | median \|move\| | p90 | frac ≥ 26bp | frac ≥ 80bp |
|---|---|---|---|---|---|---|
| BTC | 4h | 71.3 | 32.1 | 108.0 | 0.570 | 0.176 |
| BTC | 8h | 103.0 | 48.3 | 155.2 | 0.712 | 0.306 |
| BTC | 24h | 191.8 | 86.2 | 296.0 | 0.818 | 0.526 |
| ETH | 4h | 96.4 | 41.1 | 147.0 | 0.648 | 0.265 |
| ETH | 8h | 134.7 | 66.0 | 210.9 | 0.775 | 0.426 |
| ETH | 24h | 229.9 | 110.8 | 394.0 | 0.859 | 0.582 |

- At 24h the median move is 3.3× (BTC) / 4.3× (ETH) the hurdle — the cost
  arithmetic is viable at swing horizons (unlike the 60s scalp, where the
  hurdle was 12× the typical move). At 4h it is marginal (1.2–1.6×).

Continuation cells (trigger: trailing-24h return ≥ ±100bps, declared a
priori; 48 cells across 8 symbols):

- **BTC/ETH: every cell net-negative** (−14.01 to −53.93 bp mean; hit rates
  0.27–0.50). Momentum continuation is absent on the two deepest books —
  mild reversal instead.
- Alts: positive cells exist — NEAR LONG 8h +95.65 (n=57), NEAR LONG 24h
  +271.08 (n=22), STRK LONG 4h +81.57 (n=95), STRK LONG 8h +210.36 (n=53),
  STRK LONG 24h +494.08 (n=21), W LONG 24h +92.91 (n=23), SOL LONG 24h
  +22.74 (n=19) — **but the sanity anchor kills the naive read**: window
  total returns were STRK **+337%**, NEAR **+136%**, W **+132%** vs BTC
  +8.9%. The positive cells are exactly the three coins that rallied
  massively in this one window. That is a regime artifact measured across 48
  uncorrected cells — the multiple-comparisons pattern, not demonstrated edge.
  SHORT-momentum is net-negative in 23/24 cells (all but ETH 24h +0.28, n=16).
- Post-hoc sensitivity (labeled, BTC/ETH only): trig=50bp → 1/12 cells
  positive; trig=200bp → 0/12. BTC/ETH non-edge is threshold-robust.

**H-03 verdict per the frozen rule: MERITS-CANDIDATE-EVALUATION** (not all
cells ≤ 0; arithmetic passes at 8h/24h) — **with the honest annotation** that
every positive cell sits on a +130–340% rally coin in this specific window,
BTC/ETH are uniformly negative, and no multiple-hypothesis correction exists.
If the owner wants a P3 candidate, it must be preregistered fresh (e.g.,
cross-sectional momentum-long with symbol-neutral construction) and evaluated
on data this study never touched — the 30-day benchmark is now development
knowledge for these cells.

## What this means for the capture decision (the study's purpose)

| Family | Economics measured | 10-day tick capture needed? |
|---|---|---|
| P1 maker/post-only | not measurable without book data | **Yes** — the only family that justifies it |
| P2 funding carry | funding 4.4% ann; perp-only taker form dead; delta-neutral form needs **spot+perp** | **No** — Vision free spot+perp+funding suffices to study it |
| P3 swing 4h+ | arithmetic viable at 8–24h; BTC/ETH continuation absent; alt positives = regime artifact | **No** for economics study — Vision free 1m/1h klines over months suffice |

The 10-day capture (≈186 GB top-2, owner-run per `coord/pivot/CAPTURE-RUNBOOK.md`)
is a **P1 investment**, not a project prerequisite. P2/P3 can be measured to
decision-grade depth on $0 Vision data first; if their economics are absent,
the capture question reduces to "is P1 worth building for" — a much smaller
ask. (Note: the frozen PIVOT-01 data floor requires quotes for ANY qualifying
dataset; if a P2/P3 candidate ever emerges from Vision data, the owner must
either extend a capture or amend the floor — an owner decision, recorded then.)

## Non-goals honored

No strategy/spec/code changes in any worker lane; no network calls; no
credentials; no candidate created; S1–S5/X1 not re-entered. Live submission
remains disabled. Nothing here is profitability evidence.
