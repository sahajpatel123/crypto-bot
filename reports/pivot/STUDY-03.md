# STUDY-03 — P2 delta-neutral basis + P3 momentum replication on untouched $0 Vision data (NOT a strategy)

Status: **PREREGISTERED — FETCHED — RUN — descriptive result.** Method frozen in
`reports/pivot/study03-prereg.json` (commit `16c614d`) BEFORE any fetch or run;
fetcher + tool + 13 unit tests landed pre-run (`16e2271`); results below,
method untouched. Creates **no strategy, no candidate, consumes no PIVOT-01
attempt budget**. This is the direct follow-up to STUDY-02's two open
questions: (a) does the delta-neutral spot+perp carry exist economically, and
(b) do STUDY-02's alt-momentum positives replicate out-of-window?

Author: independent 4th agent (owner-directed). Filed to manager for review.
Lane discipline: no worker-lane files touched; new files only
(`tools/vision_fetch.py`, `tools/pivot_study_03_basis_replication.py`,
`tests/unit/test_pivot_study03.py`, this report, results JSONs, `data/vision/`
zips + per-file sha256 provenance — data untracked, fetch report tracked).

## Data (frozen + provenance)

- 58 Vision monthly archives requested, **56 present, 2 absent** (spot 1m
  2026-10 monthly not yet published — month incomplete; recorded absent,
  never imputed). Every file sha256-recorded in
  `reports/pivot/study03-fetch-report.json` + per-file `.provenance.json`.
- Window: **2026-06-01 → 2026-08-31 UTC** — touched by NO prior round.
- Conventions: kline close published at close_time; **count==0 minutes are
  MISSING** (no forward-fill; matches STUDY-02/transform-v2 semantics).
  Format quirk handled and tested: spot archives are headerless with
  MICROSECOND timestamps, futures headered milliseconds — normalized to ms.
- Funding: settlement rows (calc_time, interval, rate); STRK/W carry 4h
  intervals (551 settlements), others 8h (276) — attribution is
  interval-agnostic (timestamps only).

## Arm A — P2 delta-neutral spot+perp carry (BTC/ETH, fresh window)

Basis structure (b = (perp−spot)/spot, both legs present, coverage 1.000):

| Metric | BTCUSDT | ETHUSDT |
|---|---|---|
| Basis mean | **−4.35 bp** | **−4.64 bp** |
| Basis median / p10 / p90 | −4.44 / −5.47 / −3.31 | −4.65 / −5.71 / −3.57 |
| Fraction positive | 0.01 | 0.00 |
| Annualized premium | **−47.6%** | **−50.8%** |
| Convergence corr(b, Δb_8h) | −0.586 | −0.618 |
| Minutes with basis_ann ≥ +8% | 0.90% | 0.09% |

**The decisive structural fact: the perp traded at a persistent DISCOUNT to
spot across the entire window.** The classic carry (long spot + short rich
perp, collect funding + basis convergence) requires a POSITIVE basis; here
the basis leg is against the carry 99%+ of the time, and the negative
convergence correlation means the basis mean-reverts upward — the wrong
direction for a short-perp book.

Signal cells (trigger basis_ann ≥ 8%, a priori; 30 bps VIP0 book RT; exact
two-leg P&L; funding strictly inside hold):

| Cell | sig | ent | net_mean | funding | pnl |
|---|---|---|---|---|---|
| BTC 72h | 5 | 4 | −24.20 | +5.11 | +0.69 |
| BTC 168h | 4 | 3 | −18.73 | +9.67 | +1.60 |
| BTC 336h | 1193 | 2 | −16.71 | +14.21 | −0.92 |
| ETH 72h | 3 | 3 | +10.57 | +1.32 | +39.25 |
| ETH 168h | 2 | 2 | +38.00 | +7.05 | +60.95 |
| ETH 336h | 114 | 1 | −29.47 | −1.27 | +1.80 |

- 336h cells are structurally starved (exit data rarely exists 14 days into
  a 3-month window) — reported, not hidden.
- The ETH positives are **n=2 and n=3** — statistically vacuous; disclosed
  because the frozen rule reads literally, weighted accordingly.
- Capital efficiency at 168h: BTC −4.9%/−6.5%/−7.3% ann on total capital at
  L=1/2/3; ETH +9.9%/+13.2%/+14.9% (n=2 — noise, not yield).
- Supplementary (Sept 11–30 benchmark window, prior-use labeled, perp leg
  from the repo's sealed parquet): **zero signals** — the basis never reached
  +8% ann in September either.
- POST-HOC (labeled): 4%/12% triggers and BNB 24bps costs — BTC negative in
  every arm; ETH's n≤3 positives persist but remain vacuous.

**Arm A verdict per the frozen rule: NOT-WORTH-AT-RETAIL-SCALE.** BTC fails
the median-168h ≥ 0 condition outright. ETH passes the literal rule only on
n=2 cells; the descriptive basis structure (persistent discount, 0.09%
trigger incidence) says the carry opportunity does not exist for ETH either
in these windows. Combined with STUDY-02 (perp-only form dead): **P2 is
measured dead at retail scale in both forms.** The funding engine is real
(~4.4% ann) but small, capital-inefficient at retail fee tiers, and the basis
worked against the book.

## Arm B — P3 momentum replication (exact STUDY-02 construction, fresh window)

Frozen rule: REPLICATED iff ≥ 2 of {NEAR, STRK, W} LONG 24h cells have
net_mean > 0 with n ≥ 15.

| Symbol | STUDY-02 (Sept–Oct) LONG 24h | STUDY-03 (Jun–Aug) LONG 24h | Verdict |
|---|---|---|---|
| NEARUSDT | +271.08 (n=22) | **−66.08 (n=58)** | flipped |
| STRKUSDT | +494.08 (n=21) | **−109.69 (n=59)** | flipped |
| WUSDT | +92.91 (n=23) | **−97.93 (n=58)** | flipped |

**0 of 3 replicate → NOT-REPLICATED. STUDY-02's alt-momentum positives are
CONFIRMED as a regime artifact.** The same construction on a fresh window
inverts every previously-positive cell.

Full 48-cell grid (Jun–Aug): LONG-24h means are positive on 6/8 symbols
(BTC +16.0, ETH +27.3, SOL +68.5, ZEC +117.2, XRP +36.1) **but the medians
are ≈0 or negative on 4 of those 6** (ETH −61.9, ZEC −7.3, XRP −79.4) — the
means are outlier-driven fat-tail artifacts, the typical trade loses. Across
two windows and 96 cells with no multiple-hypothesis correction, scattered
positive means are exactly what chance produces. SHORT-momentum stays
net-negative in 20/24 cells across both windows.

**Arm B verdict: NOT-REPLICATED per the frozen rule.** No P3 candidate is
merited on this evidence. If the owner ever wants a P3 round, it must be
preregistered fresh with a family-wise correction and enough power — not
assembled from these cells.

## Strategic synthesis (STUDY-02 + STUDY-03 together)

| Family | Mechanism | Measured outcome | Status |
|---|---|---|---|
| Taker scalp (S1–S5/X1) | 26bp hurdle vs 2.1bp moves | 0/60 wins; cost-killed | **Dead (measured)** |
| P2 perp-only funding-tilt | 1.2bp/day funding vs 26bp RT | breakeven 21.6d hold | **Dead (arithmetic)** |
| P2 delta-neutral basis | basis −4.4bp mean, ann −48% | carry structure absent | **Dead (measured, $0)** |
| P3 swing momentum | viable cost physics at 24h | no replicable edge; regime artifact | **No edge (replicated null)** |
| **P1 maker/post-only** | earn the spread; toxicity filter | **never measurable without book data** | **The only unmeasured family** |

**The 10-day capture decision is now sharpened, not blurred:** it is the only
path to the only unmeasured family. Everything measurable for $0 has now been
measured, and the honest answer is that retail-fee taker and carry physics on
BTC/ETH/majors do not contain the edge the owner is looking for. What remains
is P1 — the hardest, most competitive mechanism, where the realistic
expectation must be set accordingly (professional market makers are the
counterparty).

## Non-goals honored

No strategy/spec/code changes in any worker lane; no credentials; no orders;
live submission untouched and disabled. Nothing here is profitability
evidence. Both studies are $0 and reproducible:
`python tools/vision_fetch.py --out data/vision` then
`python tools/pivot_study_03_basis_replication.py --vision-dir data/vision
--out <out>.json` (byte-deterministic).
