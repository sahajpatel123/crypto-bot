# H1 — Maker-only order-flow-imbalance scalp (preregistered, T5.3)

Causal mechanism: short-horizon book imbalance predicts the next
mid-price move; a maker entry avoids the taker fee + spread that made
taker scalps structurally negative at ~26bps round-trip.
Rules (exact): BTCUSDT/ETHUSDT; imbalance (bid-ask qty, top 5) beyond
+/-0.6; post-only limit at best bid/ask; cancel after 30s unfilled;
stop 25bps / target 50bps (maker entry, taker exit); max 1 position.
Evaluation: T5.4 protocol on DEVELOPMENT data only (data/pilot,
datasets/benchmark_30d — already inspected, so results are dev
evidence, never confirmation). Confirmation: exactly once on
untouched data (campaign capture, owner-released), no re-runs.
Committed BEFORE any H1 evaluation run.
