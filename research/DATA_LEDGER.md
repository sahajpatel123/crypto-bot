# Data ledger (T5 protocol) — every dataset use is logged here

| Dataset | Class | Use | Date |
|---|---|---|---|
| data/pilot | DEVELOPMENT (inspected) | Prior pilot: 0/14 cells positive, best -25.37bps @26bps cost (audit input) | pre-takeover |
| datasets/benchmark_30d | DEVELOPMENT (inspected) | Prior benchmarks (H-R2 -13.42bps, X1 0 fills) | pre-takeover |
| data/captures/campaign-1day-20261017 | CONFIRMATION (untouched) | NEVER read/touched by this program; reserved for exactly-once confirmation per hypothesis, owner-released | — |
| datasets/benchmark_30d (marks+funding parquets) | DEVELOPMENT (inspected) | H2/H3 bar-level dev evaluation via tools/eval_h123.py → reports/hypotheses/H2.json, H3.json (both UNDERPOWERED, negative); H1 UNEVALUABLE (no book channel) | this program |
| vision daily markPriceKlines 2026-10-12..18 (8 symbols) | DEVELOPMENT (extension, via tools/extend_benchmark.py) | H2 power extension: 289 trades, expectancy +56.60bps held on the fresh week | this program |
| data/captures/h1-accrual-01 (live depth, BTC/ETH) | DEVELOPMENT (prospective capture, prereg H1-book-capture.md) | H1 first scoring: 1 fill from 7 signals / 5,962 snapshots → UNDERPOWERED, signal-starved on majors; bulk deleted after scoring (disk), verdict + manifest kept | this program |
| binance-vision um monthly markPriceKlines 1h 2022-01..2026-08 (28 symbols, datasets/history_1h, untracked) | DEVELOPMENT (falsification, prereg H2-history-falsification.md @ d0909fd) | H2-HIST: universe A 6,441 trades −17.09bps/trade (gross +0.91), day-block CI95 [−29.9, −4.1], 2x −35.1bps, negative 2023/2024/2025 → **H2 KILLED**; universe B 20,675 trades −18.56bps | 2026-10-24 |
| history_1h daily closes + binance-vision um monthly fundingRate 2022-01..2024-12 (28 symbols) | DEVELOPMENT (Family C DEV, prereg C-family-daily.md) | C1 TSMOM +9.33bps/day p=0.106 FAIL; C2 XSMOM +9.19 p=0.0195 FAIL (2024 −1.08); C3 CARRY −0.70 KILLED; C4 REVERSAL −14.95 KILLED | 2026-10-24 |
| same, 2025-01..2026-08 | HOLDOUT (spent once, on C2 only, amendment 1) | C2 XSMOM +5.95bps/day, Sharpe 0.83, week-block CI95 [−5.2, +16.9], p=0.154, maxDD 2,658bps → **KILLED**; holdout now consumed for Family C | 2026-10-24 |
| binance-vision um monthly markPriceKlines 1h + fundingRate 2019-09..2021-12 (28 symbols; scored 2020-01..2021-12) | REPLICATION (spent once, C2 only, amendment 2) | C2 XSMOM +14.74bps/day, Sharpe 1.08, CI95 [−6.0, +36.6], p=0.080 (bar p<=0.01), maxDD 3,785bps → **KILLED**; Family C closed | 2026-10-24 |
