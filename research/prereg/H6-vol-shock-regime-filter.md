# H6 — Volatility-shock regime filter (preregistered meta-layer)

Status: FROZEN-BEFORE-EVALUATION (committed 2026-10-18). Budget: 6/8.

## Causal mechanism

A volatility shock changes the payoff of every short-horizon strategy:
mean-reversion signals get run over, while breakout signals improve.
This is a *meta-layer*, not a standalone trade generator. It may only
gate or size existing hypotheses; it may never create an entry alone.

## Exact rules

- Instruments: BTCUSDT, ETHUSDT.
- Shock definition: 1-minute realized volatility > 3x its 60-minute
  median, or an absolute 1-minute return > 50bps.
- For H1/H3 (mean-reversion): block new entries for 5 minutes after a
  shock; existing positions keep their stops.
- For H2/H4 (continuation): allow entries only in the shock direction
  for 10 minutes; size at 50% during the first minute.
- Never changes stop/target geometry; never increases size.

## Parameter grid (all trials counted)

| Parameter | Values |
|---|---|
| RV multiple | 2x, 3x, 4x |
| shock return | 30, 50, 80 bps |
| block/allow window | 2, 5, 10 min |

27 cells. Evaluated as a filter on H2 and H3 only; every filtered cell
counts as a trial. No cherry-picking of the best base hypothesis.

## Cost assumptions

Same as the underlying hypothesis; the filter adds no execution cost
but is judged on net P&L after the same 1.5x promotion stress.

## Dev promotion

The filtered variant must beat the unfiltered baseline by > +2bps
pooled, bootstrap 90% lower bound > 0, and >=2/3 folds positive. A
filter that merely reduces trade count without improving net
expectancy is KILLED.

## Confirmation (exactly once)

Sealed CONFIRM data after freeze; >=300 trades in the filtered variant;
CI95 > 0; >0 at 2x; >=60% non-negative days; drawdown in budget; Holm
across H1–H6. UNDERPOWERED stays AWAIT_CONFIRM_DATA.
