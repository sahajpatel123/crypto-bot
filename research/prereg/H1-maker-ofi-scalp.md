# H1 — Maker-only order-flow-imbalance scalp (preregistered)

Status: FROZEN-BEFORE-EVALUATION (committed 2026-10-18, worktree
`live/final-hardening`). Hypothesis budget: 6 of 8 (H1–H6).

## Causal mechanism

Short-horizon queue imbalance at the top of the book predicts the next
mid-price move because resting liquidity is price-inelastic at
sub-second horizons. A post-only entry earns the spread instead of
paying it; the taker exit is the cost of not predicting the exit.

## Exact rules

- Instruments: BTCUSDT, ETHUSDT (USD-M perpetual).
- Signal at each book update: `imbalance = (bid_qty - ask_qty) /
  (bid_qty + ask_qty)` over top 5 levels, computed only from a clean,
  non-stale depth chain. Enter LONG when imbalance >= +threshold,
  SHORT when <= -threshold.
- Entry: post-only limit at the current best bid (LONG) / best ask
  (SHORT); cancel after 30s unfilled; never cross.
- Exit: stop 25bps / target 50bps from entry, taker stop-market,
  taker target limit at the target; max holding 15 minutes then taker.
- One position globally; no averaging; no re-entry within 60s of an exit.
- No entry if spread > 2bps or top-5 depth < 3x order notional.

## Parameter grid (all trials counted)

| Parameter | Values |
|---|---|
| imbalance threshold | 0.5, 0.6, 0.7 |
| queue-ahead assumption | 0, 0.5, 1.0 x visible size |
| max holding | 5, 15, 30 minutes |

27 cells. Any additional cell requires a new preregistration and counts
against the 8-hypothesis budget.

## Cost assumptions

Maker entry 2bps/side; taker exit 5bps/side; half-spread 2bps round
trip; latency/slippage 6bps round trip; funding booked at the observed
rate (negative funding is a cost, never a credit for sizing). Realistic
= 1x; promotion also checks 1.5x; confirmation checks 2x adverse.

## Dev promotion (must all hold)

- Pooled dev net expectancy > +2bps at realistic cost;
- day-block bootstrap 90% lower bound > 0;
- positive in at least 2 of 3 folds under anchored walk-forward with
  purge/embargo (no future information);
- >=100 dev trades and >=10 trading days.

DEV data only: `data/pilot`, `datasets/benchmark_30d` (already
inspected; never confirmation). Failure permanently KILLS H1.

## Confirmation (exactly once)

Sealed CONFIRM chunks sealed strictly after this config hash was
committed; >=300 trades; CI95 lower bound > 0 at realistic cost;
expectancy > 0 at 2x adverse cost; >=60% non-negative days; drawdown
inside the risk budget; Holm correction across the six-hypothesis
family. Too few trades => UNDERPOWERED, stay in AWAIT_CONFIRM_DATA and
extend only with newly sealed data.
