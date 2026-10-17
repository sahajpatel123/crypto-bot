# H5 — Liquidation-cascade fade (preregistered, F4.1)

Causal mechanism: forced liquidation flow (forceOrder stream)
overshoots fair value; once the cascade exhausts, price mean-reverts.
Rules (exact): BTCUSDT/ETHUSDT; cascade = >=500k USDT liquidation
notional in 60s one direction; fade entry opposite the cascade when
5-min post-cascade drift stalls (two consecutive 1-min bars inside
0.2x ATR); stop beyond cascade extreme +0.5 ATR; target 1.0 ATR.
Costs: taker round-trip cost_model_v2 at 1.5x stress for entry
(cascades are volatile). Grid: cascade threshold {250k,500k,1M} x
target {0.75,1.0,1.5} ATR — 9 trials, all counted.
Min trades 300. Dev promotion / confirmation: same as H4.
Committed BEFORE any H5 evaluation.
