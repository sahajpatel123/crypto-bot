# RESEARCH VERDICTS — does anything have a real fee-inclusive edge?

**Answer (2026-10-24): no strategy has demonstrated a fee-inclusive
edge.** Intraday families (S, X1, H1–H5, B1–B7) die on costs; H2's
+56bps dev result was KILLED on 4.7 years of unseen history (−17bps,
n=6,441). The only consistent positive sign is daily cross-sectional
momentum (C2: +9.2 / +5.9 / +14.7 bps/day on DEV / holdout /
2020–21 replication, Sharpe 0.8–1.1, drawdowns to 38%), but no period
met its preregistered bar, so C2 is KILLED and Family C is closed.
Nothing below is dressed up as a pass.

## Evidence (development data only — see research/DATA_LEDGER.md)

| Family | Evidence | Numbers | Trials | Verdict |
|---|---|---|---|---|
| Taker scalps (prior pilot, S-family) | `data/pilot` (DEVELOPMENT, inspected) — audit input, reproduced in STATE.md T0.1 | 0/14 cells positive; best −25.37bps at 26bps round-trip cost | 14 cells | **FAIL** |
| H-R2 (prior benchmark) | `datasets/benchmark_30d` (DEVELOPMENT) | −13.42bps expectancy | — | **FAIL** |
| X1 (prior benchmark) | `datasets/benchmark_30d` (DEVELOPMENT) | 0 fills in 24 cells (F2 latch, since fixed) | 24 cells | **UNDERPOWERED** (measured the latch, not the strategy) |
| H1 maker OFI scalp | `reports/hypotheses/H1-accrual-01.json` — first live book capture (BTC/ETH, 5,962 snapshots) | 1 fill, −14.07bps (n=1); only 7 snapshots breach frozen 0.6 threshold | 1 | **UNDERPOWERED** (signal-starved on majors; alts are the future universe) |
| H2 trend/vol-regime | `reports/hypotheses/H2.json` — bar-level dev evaluation, 8 symbols, benchmark_30d + 2026-10-12..19 extension | net **+55.94bps/trade** on 290 trades; split-half +81.1 / +30.8bps; sized DD 329bps; +8.8bps equity/day. WARNING: edge concentrated in STRK/W/NEAR; BTC/ETH/SOL/ZEC/XRP negative — no post-hoc symbol dropping permitted | 290 | **UNDERPOWERED** (n<300 by 10 trades; concentration risk open) |
| **H2 multi-year (H2-HIST)** | `reports/hypotheses/H2-history.json` — frozen H2 rules on 2022-01..2026-08 archive 1h marks, never inspected; prereg `research/prereg/H2-history-falsification.md` | universe A (dev 8): **−17.09bps/trade, n=6,441**, gross +0.91bps, day-block CI95 [−29.9, −4.1]; 2x cost −35.1bps; years 2022 +10.2 / 2023 −25.2 / 2024 −12.8 / 2025 −36.1 / 2026 +5.9. 28-symbol universe B: −18.56bps, n=20,675. STRK −110bps, W −158bps over full history | 6,441 | **KILLED** — the +56bps dev edge was a one-regime artifact; no tuning permitted |
| Family C (daily/weekly portfolios) DEV 2022–24 | `reports/hypotheses/C-dev.json`, prereg `research/prereg/C-family-daily.md` | C1 TSMOM +9.3bps/day (p=0.106); C2 XSMOM +9.2 (p=0.0195, 2024 negative); C3 carry −0.7; C4 reversal −15.0 | 4 × ~1,060 days | **FAIL** (C3/C4 KILLED) |
| C2 XSMOM holdout 2025-01..2026-08 (one shot) | `reports/hypotheses/C2-holdout.json`, amendment `research/prereg/C-family-amendment-1.md` | +5.95bps/day net, Sharpe 0.83, CI95 [−5.2, +16.9], p=0.154, maxDD 26.6% | 607 days | **KILLED** — positive sign, not distinguishable from luck; survivor universe |
| C2 XSMOM replication 2020–21 (one shot, untouched) | `reports/hypotheses/C2-replication.json`, amendment `research/prereg/C-family-amendment-2.md` | +14.74bps/day, Sharpe 1.08, CI95 [−6.0, +36.6], p=0.080 vs preregistered p≤0.01; maxDD 37.8% | 695 days | **KILLED** — Family C closed |
| H3 funding-skew tilt | `reports/hypotheses/H3.json` — bar-level dev evaluation, 8 symbols, benchmark_30d | net −6.62bps/trade (gross +11.38bps), −28.6bps/active day, 28 days | 121 | **UNDERPOWERED** (n<300; net expectancy negative) |
| H5 alt maker OFI | `reports/hypotheses/H5-accrual-01.json` — live book capture (STRK/W/NEAR, 10,241 snapshots) | 0 signals, 0 fills; 0 snapshots breach even 0.3 imbalance | 0 | **UNDERPOWERED** (signal-dead: top-5 notional imbalance never fires) |

## Why taker scalps fail structurally (T5.1, cost_model_v2)

`cryptobot research cost_model_v2.breakeven_table()`: at 25/25bps
stop/target with a taker entry (~13–18bps round-trip at 1x, more at
1.5x/2x stress), the required win rate exceeds 60–65% before any
alpha — the pilot's best cell (−25.37bps) is what that arithmetic
predicts without a real signal. Maker entry cuts the fee leg
(~2bps/side) but adds queue/adverse-selection risk, which the
conservative queue model in `execution/fill_realism.maker_fill`
(no credit for touches) prices honestly.

## Protocol for any future claim (T5.4/T5.5)

`cryptobot verdict` emits PASS/FAIL/UNDERPOWERED JSON bound to
config/data/code hashes, no manual override. PASS needs bootstrap
CI95 lower bound > 0 at realistic cost, expectancy > 0 at 2x adverse
cost, ≥300 trades, ≥60% non-negative days, drawdown in budget, Holm
correction across the family. Confirmation happens exactly once per
hypothesis on untouched data (the campaign capture, owner-released).

## Statistics fixes (2026-10-24)

`verdict.evaluate_trades` previously set its Holm p-value to 0 whenever
the CI lower bound was positive (so Holm never bit) and bootstrapped
correlated same-day trades as independent. It now uses a day-block
bootstrap and a real one-sided bootstrap p. Earlier verdicts were all
non-PASS, so no conclusion changes.

## Recommendation — what is left (ranked)

1. **Do not arm.** There is nothing validated to trade; the prod
   route now refuses any strategy a PASS verdict did not score.
2. **Forward study of daily XSMOM — preregistered and built
   (`research/prereg/C2-forward.md`, `tools/forward_c2.py`); it needs a
   host that can reach fapi.binance.com to run
   `tools/forward_c2.py record` daily (cron/systemd timer) for >=180 days,
   then one scoring. Background:** The
   historical record is exhausted (2020–2026 all read). The only honest
   way to resolve C2's "consistent but not significant" evidence is a
   NEW preregistration on data that does not exist yet: paper-trade it
   forward with a point-in-time universe (incl. delistings) for at
   least 6–12 months, scored once. Expect a Sharpe ~1 effect with
   ~30–40% drawdowns at 1x gross; it is a portfolio strategy, not a
   scalper, and would need a new runtime (multi-position, daily
   rebalance) — the current Session is one-position-at-a-time.
3. **Intraday book strategies** (H1/H5) only with a recorder that keeps
   full depth AND aggTrade prints; maker-only, never taker.
4. Every new claim: prereg committed first, DEV/holdout split, one
   shot, `cryptobot verdict --strategies ...`, then ≥14d pessimistic
   paper, demo drill, latency, gate, arm.
