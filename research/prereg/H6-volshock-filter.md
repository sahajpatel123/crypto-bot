# H6 — Volatility-shock regime filter, meta-layer (preregistered)

Causal mechanism: most scalp expectancy concentrates in
high-expected-move regimes; a filter that only trades after a
volatility shock (realized vol jump) raises edge per trade enough to
clear taker costs, even if the underlying signal is unchanged.
Rules (exact): meta-layer over H1/H2 signals; trade only when
30-min realized vol exceeds its 30-day 80th percentile AND the last
15-min range exceeded 2x ATR(1h); otherwise flat. No standalone
entries. Grid: percentile {70,80,90} x range mult {1.5,2,3} — 9
trials, all counted. Min trades 300 (filtered). Dev promotion /
confirmation: same as H4, evaluated on the host hypothesis trades.
Committed BEFORE any H6 evaluation.
