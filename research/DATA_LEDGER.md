# Data ledger (T5 protocol) — every dataset use is logged here

| Dataset | Class | Use | Date |
|---|---|---|---|
| data/pilot | DEVELOPMENT (inspected) | Prior pilot: 0/14 cells positive, best -25.37bps @26bps cost (audit input) | pre-takeover |
| datasets/benchmark_30d | DEVELOPMENT (inspected) | Prior benchmarks (H-R2 -13.42bps, X1 0 fills) | pre-takeover |
| data/captures/campaign-1day-20261017 | CONFIRMATION (untouched) | NEVER read/touched by this program; reserved for exactly-once confirmation per hypothesis, owner-released | — |
| datasets/benchmark_30d (marks+funding parquets) | DEVELOPMENT (inspected) | H2/H3 bar-level dev evaluation via tools/eval_h123.py → reports/hypotheses/H2.json, H3.json (both UNDERPOWERED, negative); H1 UNEVALUABLE (no book channel) | this program |
| vision daily markPriceKlines 2026-10-12..18 (8 symbols) | DEVELOPMENT (extension, via tools/extend_benchmark.py) | H2 power extension: 289 trades, expectancy +56.60bps held on the fresh week | this program |
| data/captures/h1-accrual-01 (live depth, BTC/ETH) | DEVELOPMENT (prospective capture, prereg H1-book-capture.md) | H1 first scoring: 1 fill from 7 signals / 5,962 snapshots → UNDERPOWERED, signal-starved on majors; bulk deleted after scoring (disk), verdict + manifest kept | this program |
