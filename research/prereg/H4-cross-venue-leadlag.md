# H4 — Cross-venue lead-lag (preregistered, F4.1)

Causal mechanism: price discovery concentrates on the most liquid
venue; lagging venues (Bybit/OKX linear perps vs Binance USD-M)
adjust with a measurable delay that a fast follower can capture.
Rules (exact): BTCUSDT/ETHUSDT; when Binance 1s return exceeds
+/-15bps while the follower venue moved <5bps in the same second,
enter follower-side in the Binance direction; exit at convergence
(follower within 3bps of Binance-implied) or 30s; stop 20bps.
Costs: follower taker round-trip from cost_model_v2 per venue
(measured, never assumed equal). Grid: entry threshold {10,15,25}bps
x max hold {15,30,60}s — 9 trials, all counted.
Min trades 300. Dev promotion: pooled expectancy > +2bps realistic,
bootstrap-90 lower bound > 0, positive in >=2/3 folds. Confirmation:
F4.5 protocol on sealed CONFIRM data only.
Committed BEFORE any H4 evaluation.
