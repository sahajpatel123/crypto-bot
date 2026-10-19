# H5 — Liquidation-cascade fade (preregistered)

Status: FROZEN-BEFORE-EVALUATION (committed 2026-10-18). Budget: 6/8.

## Causal mechanism

Forced liquidations create temporary price dislocations because the
liquidation engine crosses the book regardless of fair value. Once the
forced flow stops, market makers replenish and the price partially
reverts. The fade is only valid when the cascade is large relative to
normal depth and the book is not still deteriorating.

## Exact rules

- Instruments: BTCUSDT, ETHUSDT.
- Signal: `forceOrder` liquidations in a rolling 5s window with total
  notional >= $2m (BTC) / $500k (ETH), all on one side, and a
  displacement >= 15bps from the 1-minute VWAP. Wait 1s after the last
  liquidation; enter opposite the liquidation side only if the book
  imbalance has stopped deteriorating.
- Entry: taker IOC; one position; no entry during a venue maintenance
  or data gap.
- Exit: stop 50bps / target 100bps; max holding 5 minutes; taker exit.
- No entry if the cascade's last print is older than 2s or depth is
  stale.

## Parameter grid (all trials counted)

| Parameter | Values |
|---|---|
| cascade notional | 1m, 2m, 5m USD (scaled for ETH) |
| displacement | 10, 15, 25 bps |
| reversion wait | 0.5, 1, 2 s |

27 cells. All counted.

## Cost assumptions

Taker 5bps/side, spread 2bps, slippage 6bps, plus a 10bps
cascade-impact penalty (the book is thinner than normal). Realistic
1x, promotion 1.5x, confirmation 2x adverse.

## Dev promotion

Pooled > +2bps; bootstrap 90% lower bound > 0; >=2/3 folds positive;
>=50 trades (cascades are rare) and >=10 days. Failure permanently
KILLS H5.

## Confirmation (exactly once)

Sealed CONFIRM data after freeze; >=300 trades; CI95 > 0; >0 at 2x;
>=60% non-negative days; drawdown in budget; Holm across H1–H6. Too
few trades => UNDERPOWERED.
