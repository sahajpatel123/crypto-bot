# H2 — 15m-4h trend with volatility-regime filter (preregistered)

Causal mechanism: at multi-hour horizons a 26bps round-trip is small
versus the expected move; trading only in high-expected-move regimes
(ATR percentile > 70) cuts cost drag per unit of signal.
Rules (exact): 1h bars; EMA20>EMA50 trend long (mirror short);
ATR(14) regime gate; stop 1.5xATR / target 3xATR; taker entry/exit.
Evaluation/confirmation: same protocol as H1.
Committed BEFORE any H2 evaluation run.
