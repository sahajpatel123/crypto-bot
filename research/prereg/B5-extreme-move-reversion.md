# B5 — Extreme-move mean reversion (4h–24h) conditioned on OI/funding

Status: FROZEN-BEFORE-EVALUATION (committed pre-evaluation, Family B 7/8).
Data: DEV lake (klines 1h + metrics OI + fundingRate). No holdout touch.

## Economic mechanism

Forced liquidations and stop cascades push price through fair value on
short horizons; once forced flow exhausts, market makers replenish and
price partially reverts. Conditioning on rising open interest selects
forced-flow dislocations (fresh leverage piling in, then wiped) over
informed repricing.

## Counterparty test

Who loses: liquidated leveraged traders and panic sellers/buyers
executing with urgency regardless of price. Why it persists: forced
flow is price-insensitive by construction (margin calls, stop
triggers); exchanges must liquidate into the book. Adverse selection
is the core risk: some extreme moves are informed (F1) — the OI
condition and fixed 24h exit bound the damage.

## Exact rules

- Universe: top_n=30, min_listing_age_days=90,
  min_quote_volume_30d=$10M, evaluated daily 00:00 UTC. For
  OI-confirm=yes cells, symbols without metrics coverage at signal
  time are ineligible (point-in-time; no backfill assumption).
- Signal (daily 00:00 UTC, from 1h bars): window W in {4h, 24h};
  move = close[now]/close[now−W] − 1; σ_W = trailing-30d std of
  non-overlapping W-returns; z = move/σ_W.
- Entry: if |z| > threshold T in {2, 3} AND (OI-confirm=no OR OI rose
  over max(W, 24h) — sum_open_interest now > W-ago) → fade: SHORT if
  z > 0, LONG if z < 0. OI prints are daily 00:00 UTC; the "now" print
  is the last print strictly before the signal date, so the 4h cell
  uses the trailing-24h OI change (intraday OI is unobservable;
  clarified pre-evaluation, D-035). One position per symbol; no
  re-entry within 24h of an exit (same symbol).
- Size: risk sleeve = min(5% equity risk, vol-scaled to 20% ann.
  sleeve vol); portfolio gross ≤ 2×; per-symbol ≤ 25% gross.
- Exit: 24h time exit (taker at the bar) OR protective stop at 2× the
  entry displacement against the position (checked on 1h closes).
- Execution: taker at the 00:00 UTC hourly open following the signal
  computation (same timestamp convention as daily open).

## Parameter grid (8 cells, ALL trials counted)

| window W | threshold T (σ) | OI-confirm |
|---|---|---|
| 4h, 24h | 2, 3 | yes, no |

Hold fixed (not gridded): 24h exit, 2× stop, daily signal cadence.

## Cost model (realistic all-in)

B1-identical (7.5bps taker/side, 1bp spread/side, sqrt-impact slip
floor 1bp, observed funding, taker-only, 2× adverse on
fee/spread/slip). Note: 24h holds cross 3 funding settlements;
funding is charged, never assumed zero.

## Rebalance / turnover

- Daily signal evaluation; 24h holds. Turnover budget ≤ 24× one-way
  annualized (selective entry, not daily churn).

## Dev promotion (numeric)

Walk-forward as B1 (pooled OOS 2021–2023): Sharpe ≥ 0.7; > 0.3 at 2×;
DSR ≥ 0.8 (trials = 8); PBO ≤ 0.3; ≥2 of 3 OOS years (same 2020
justification); plateau ≥70%; DD ≤ 35%; turnover ≤ 24×. Any miss KILLS B5.

## Confirmation (holdout screen, exactly once, via verdict)

Point > 0.3 and ≥50% dev OOS; 80% LB > −0.3; positive at 2×;
DD in budget; turnover reported; screen-not-proof caveat stated.

## Failure modes

F1: informed-flow adverse selection (fade into real news). F2: OI data
lags/sparse on small symbols (eligibility rule handles it; if too few
symbols qualify, the cells starve honestly). F3: stop-outs cluster in
trends (fade fights drift; the 2× stop + 24h exit cap each loss).

## Knowledge-contamination note

Same background knowledge as B1 (incl. recalled liquidation cascades
Mar-2020, May-2021, 2022). Avoidance: windows/thresholds are
round-number statistical conventions (4h/24h, 2σ/3σ), not values
tuned to recalled cascades; the OI condition comes from the forced-
flow mechanism, not from observed OI patterns (no OI series seen);
no date/event conditioning; written pre-computation.
