# H2 — Trend / volatility-regime continuation (preregistered)

Status: FROZEN-BEFORE-EVALUATION (committed 2026-10-18). Budget: 6/8.

## Causal mechanism

Multi-hour crypto trends persist because flow and funding adjust
slowly; entering after a volatility-normalized breakout captures part
of the move while a volatility-scaled stop keeps the per-trade loss
inside the budget. The regime filter avoids chop where the same signal
is negatively autocorrelated.

## Exact rules

- Instruments: BTCUSDT, ETHUSDT.
- Regime: ATR(14) on 5-minute bars above its 30-day median and
  `close > EMA(50)` (LONG) or `close < EMA(50)` (SHORT).
- Entry: stop-limit breakout of the prior 20-bar high/low, only when
  the breakout bar closes beyond it; taker entry at the close.
- Exit: stop = 1.5 x ATR(14), target = 3.0 x ATR(14), max holding 24h,
  time exit at the next 8h funding boundary if neither is hit.
- One position globally; no pyramiding; no entry in the 5 minutes
  before a scheduled funding timestamp.

## Parameter grid (all trials counted)

| Parameter | Values |
|---|---|
| breakout lookback | 12, 20, 40 bars |
| stop ATR multiple | 1.0, 1.5, 2.0 |
| target multiple | 2.0, 3.0, 4.0 |

27 cells. No post-hoc cell selection; all cells are reported.

## Cost assumptions

Taker entry and exit 5bps/side; spread 2bps; slippage 6bps; funding as
observed. Replay uses book-walk when depth is recorded; otherwise the
pessimistic one-tick-plus-latency model. Realistic 1x, promotion 1.5x,
confirmation 2x adverse.

## Dev promotion

Pooled net expectancy > +2bps; day-block bootstrap 90% lower bound > 0;
>=2/3 folds positive under anchored walk-forward with purge/embargo;
>=100 trades and >=20 days. Failure permanently KILLS H2.

## Confirmation (exactly once)

Sealed CONFIRM data after freeze; >=300 trades; CI95 lower bound > 0 at
realistic cost; >0 at 2x adverse; >=60% non-negative days; drawdown in
budget; Holm across H1–H6. UNDERPOWERED stays AWAIT_CONFIRM_DATA.
