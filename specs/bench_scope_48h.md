# Frozen 48h benchmark scope (manager, 12 Oct 2026 ~19:00 IST)

Dataset: datasets/benchmark_30d.toml, sha b423a7be (verify at run time).
Symbols: BTCUSDT + ETHUSDT ONLY (first economic benchmark; other 6 symbols
preserved in datasets/cache for later research).
Splits (IST accounting days): dev 15 (Sep 12–26), validation 7 (Sep 27–Oct 3),
test 8 (Oct 4–11). Test runs ONCE, after the dev/val improvement batch.
Armsets: S1 S2 S3 S4 S5 COMBINED CASH (7 per split, 21 cells).

Coverage: 126 sources, 70,635,512 manifest rows. Trades + mark prices present
all 30 days for both symbols. Gaps: funding-terms-absent Oct 1–11 both symbols
(October monthlies publish after month-end; beyond the deadline).

COST CAVEAT (frozen): test-split economics EXCLUDE funding (terms absent).
Report labels: costs-complete on dev/early-val; funding-absent on Oct days.
Run a preregistered funding sensitivity (0x/ Sep-median-rate) on dev/COMBINED
before citing test net. Missing funding is incomplete-cost evidence, never
an unqualified zero.

Throughput baseline (01487ac, single BTC day, Session replay): 2,825 ev/s
(297,611 events / 105.4s, 0 admits). Serial 21-cell ETA ≈ 60–70h; plan is
Q-008 streaming (memory fit in 8GB) + parallel cells (~10–12h wall on 8 cores).
S5 expected ineligible (no synchronized depth in archive); test on captures.
Spread: causal modeled quotes ONLY after Q-008 fix; pre-fix numbers invalid.
