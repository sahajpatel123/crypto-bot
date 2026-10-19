# H4 — Cross-venue lead-lag (preregistered)

Status: FROZEN-BEFORE-EVALUATION (committed 2026-10-18). Budget: 6/8.

## Causal mechanism

Bybit/OKX linear-perp prices sometimes move before Binance USD-M
because of venue-specific flow, liquidation engines or latency
asymmetry. If a move at another venue predicts the next Binance
mid-price change after fees, a taker entry on Binance can capture it.

## Exact rules

- Instruments: BTCUSDT, ETHUSDT; comparison venues Bybit linear and OKX
  USDT swap (optional recorder plugins, enabled only when their streams
  are present and time-aligned within 50ms).
- Signal: at time t, `lead_return = (mid_v(t) - mid_v(t-Δ)) / mid_v(t-Δ)`
  for venue v; enter Binance in the same direction when
  `|lead_return| >= threshold` and Binance has not moved more than 50%
  of it yet.
- Entry: taker IOC at Binance top of book; max 1 position; no entry if
  the cross-venue clock offset exceeds 25ms.
- Exit: stop 25bps / target 50bps, max holding 60s, taker exit.
- No entry when either venue's book is stale (>250ms) or crossed.

## Parameter grid (all trials counted)

| Parameter | Values |
|---|---|
| lead window Δ | 100, 250, 500 ms |
| lead threshold | 2, 5, 10 bps |
| leader venue | bybit, okx, either |

18 cells. All trials counted; the recorder records both venues even
when the strategy is dormant.

## Cost assumptions

Binance taker 5bps/side, spread 2bps, slippage 6bps, plus 1bps
cross-venue clock/sync penalty. Realistic 1x, promotion 1.5x, confirm
2x adverse. If the measured lead is smaller than the round-trip cost
(26bps at 2x), the hypothesis is structurally dead and must be KILLED.

## Dev promotion

Pooled > +2bps after costs; day-block bootstrap 90% lower bound > 0;
>=2/3 folds positive; >=100 trades and >=10 days. Failure permanently
KILLS H4.

## Confirmation (exactly once)

Sealed CONFIRM data sealed after freeze; >=300 trades; CI95 > 0; >0 at
2x; >=60% non-negative days; drawdown in budget; Holm across H1–H6.
UNDERPOWERED stays AWAIT_CONFIRM_DATA.
