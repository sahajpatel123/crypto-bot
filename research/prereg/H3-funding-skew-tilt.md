# H3 — Funding-skew tilt (preregistered)

Status: FROZEN-BEFORE-EVALUATION (committed 2026-10-18). Budget: 6/8.

## Causal mechanism

When perpetual funding is extreme, leveraged positioning is crowded;
the perp tends to mean-revert toward spot as funding is paid and
positions unwind. The tilt is a *filter and direction* signal, not a
standalone high-frequency scalp.

## Exact rules

- Instruments: BTCUSDT, ETHUSDT.
- Signal: predicted funding rate for the next settlement, from
  premiumIndex + observed funding history. LONG only when funding is
  below its 30-day 10th percentile; SHORT only when above the 90th.
- Entry: taker at the next 1-minute bar open after the signal, only if
  H2's trend regime agrees or is neutral.
- Exit: stop 50bps / target 100bps; time exit 8h; one position.
- No entry within 10 minutes of a funding settlement.

## Parameter grid (all trials counted)

| Parameter | Values |
|---|---|
| percentile tail | 5, 10, 20 |
| stop/target | 25/50, 50/100, 100/200 bps |
| holding | 1h, 4h, 8h |

27 cells, all reported. H3 is also evaluated as a filter on H2; the
filter trial counts once and is included in the Holm family.

## Cost assumptions

Taker 5bps/side, spread 2bps, slippage 6bps, funding at the observed
rate (a cost when paying). 1x realistic, 1.5x promotion, 2x confirm.

## Dev promotion

Pooled > +2bps; bootstrap 90% lower bound > 0; >=2/3 folds positive;
>=100 trades and >=30 days. Failure permanently KILLS H3.

## Confirmation (exactly once)

Sealed CONFIRM data after freeze; >=300 trades; CI95 > 0; >0 at 2x;
>=60% non-negative days; drawdown in budget; Holm correction. Too few
trades => UNDERPOWERED.
