# STATE — live/edge-sprint (Family B: low-frequency edge search)

Worktree: `/Users/sahajpatel/Code/cryto-bot-edge`
Branch: `live/edge-sprint` from `live/final-hardening` tip `a313254`
Date: 2026-10-18. Memory for this run; resume at first non-DONE task.
Prior run (F0–F9) history is in git (`a313254` and below).
Rules: no orders, no keys, human-only arm, machine-written verdict/gate/
vault/autopilot artifacts, every claim cites command+output or file path.

## Completion checklist

| Item | Status | Evidence |
|---|---|---|
| Suite green, 0 failed | DONE | 1528 passed, 1 skipped, 0 failed |
| Split + holdout sealed BEFORE analysis | DONE | chunk-2a22e52c3c8f50db before lake returns; B4 screen chunk sealed before its decode |
| Preregs committed before evaluations | DONE | b0b4ac4 / 70e2f38 |
| Leak tests present and passing | DONE | shift, shuffle, Sharpe>3, B1 future-bar test |
| Differential test passes | DONE | `test_differential_vectorized_vs_event` |
| Every verdict machine-written | DONE | `research/verdicts_b/B4.json` |
| RESEARCH_VERDICTS_B.md maps to verdict JSONs | DONE | |
| Arm/gate refusal tests pass | DONE | `test_autopilot_gate.py` arm refusals |
| OWNER_ACTIONS.md one ordered list | DONE | steps 1–17 |

## Task table

| ID | Task | Status | Evidence |
|---|---|---|---|
| E0.1 | Re-entry: read memory, full suite 0 failed | DONE | 1501 passed/1 skipped nobench + 27 bench = 1528/1/0 failed |
| E0.2 | Autopilot run-once Family A, record dev outcomes | DONE | all H1–H6 DEV_EVAL, no dev artifacts; left to timer |
| E1.1 | Vision inventory, DATA_INVENTORY.md | DONE | `tools/vision_inventory.py`, `DATA_INVENTORY.md`; probes verified |
| E1.2 | Checksummed download | DONE | resume pull 118137 ok / 0 failed (terminal 972826); 49077 dev + 118548 holdout zips |
| E1.3 | Parquet store + hash manifest + DQ report | DONE (code) | `research/lake.py`, 4 tests; build runs when bytes land |
| E1.4 | Point-in-time universe + no-lookahead test | DONE | `research/universe.py`, 5 tests incl. lookahead proof |
| E2.1 | SPLIT.md prereg + commit (DEV/HOLDOUT/FORWARD, detectable Sharpe) | DONE | `research/prereg/SPLIT.md` fb95e02 |
| E2.2 | Vault HOLDOUT class + seal holdout pre-analysis + import lint | DONE | chunk-2a22e52c3c8f50db, 118548 files, manifest sha 2a22e52c…, decode_accesses 0, before any return statistic |
| E2.3 | Family B budget (8) + Holm family justification | DONE | SPLIT.md + D-032 |
| E3 | Family B preregs B1–B7 committed pre-evaluation | DONE | 7 preregs + configs + registry b0b4ac4/70e2f38; D-035 pre-eval corrections |
| E4.1 | Slow backtester vectorized + event reference + differential | DONE | `slow_backtest.py`, differential 1e-9, 10 engine tests |
| E4.2 | Realism (fees+50%, funding, sqrt impact, filters, liq, delist) | DONE | hand-computed cost test; liq/delist/spot/stops |
| E4.3 | Capital sweep 120/1000/10000 | DONE | `capital_sweep` + test |
| E4.4 | Leak detectors as tests | DONE | shift/shuffle/SR3/no-lookahead signals |
| E4.5 | Reviewer sub-agent breaks E4; fix findings | DONE | 15 findings; all CRITICAL/HIGH fixed + tested (37 E4/E5 tests green) |
| E5 | Statistics module + tests (WF, bootstrap, DSR, PBO, SPA, plateau, regimes, DD, capacity) | DONE | `slow_stats.py`, 9 tests |
| E6.1 | DEV evaluation, all trials counted, kill failures | DONE | only B4 promotes; B1 B2 B3 B5 B6 B7 KILLED |
| E6.2 | Freeze survivors, holdout screen once via verdict | DONE | `research/verdicts_b/B4.json` SCREEN_PASS |
| E6.3 | Autopilot Family B extension (FROZEN/HOLDOUT_SCREEN/SCREEN_PASS/FORWARD_*) | DONE | B4 is SCREEN_PASS; log verifies |
| E6.4 | RESEARCH_VERDICTS_B.md from machine JSONs | DONE | |
| E7 | Slow paper path for the SCREEN_PASS | DONE | `slow_path.py`; forward clock not started |
| E8 | OWNER_ACTIONS + README/ARCHITECTURE/RUNBOOK | DONE | steps 15–17 |
| E9 | FINAL_STATUS.md | DONE | live = MIN = 3/10 |

## E0.2 Family A dev outcomes (2026-10-18)

Command: `PYTHONPATH=src python -m cryptobot.cli autopilot run-once` → RC=0.
Result: H1–H6 all remain `DEV_EVAL`, blocked `dev/<H>.json not present`.
No DEV trades exist for Family A; nothing to promote or kill. Preregs
unedited. Family A confirmation still waits for recorder data; left to
the systemd timer. Machine report updated:
`research/autopilot/reports/2026-10-18.json`.

## E1.1 inventory (measured, subagent ses_eb1a1a8e9ffe0y708UEU0wkeyt)

- Monthly UM datasets (8): klines 1056 syms, mark 1039, premium 982,
  index 979, fundingRate 988, aggTrades 1044, trades 1044, bookTicker 315.
  Monthly leg ends 2026-09.
- Daily UM datasets (9): same minus fundingRate, plus metrics 1038 syms,
  bookDepth 1008. Daily leg ends 2026-10-17.
- Klines intervals: 1m–1d all 1056/1056; 1w/3d 346; 1mo 280; no `1M`.
- Range: klines 2020-01→2026-09; trades BTC back to 2019-09 (earliest UM).
- Delisted retained: LUNAUSDT frozen 2022-05, LENDUSDT ends 2020-11,
  ANCUSDT 2022-05, expired quarterlies present; 134/1056 no daily extension.
- bookTicker discontinued ~2024-04 (do not plan on it).
- metrics daily-only (OI + L/S ratios, 5-min rows); fundingRate monthly-only.
- Spot BTC/ETH 1d 2017-08→2026-09 available (basis leg possible).
- Planned pull ≈ 13.8 GB zipped (metrics ≈ 9.7 GB dominates).
- aggTrades/trades TB-scale: out of scope.
- Evidence: `DATA_INVENTORY.md`, raw `/tmp/vision-inventory.json`.
- Independent verification (this run): metrics + funding probes match
  (`curl` 2026-10-18, columns + CHECKSUM scheme confirmed).

## Key constraints derived

- Liquidity-scope lists (1m top-20, metrics subset) must be computed
  from DEV-only data AFTER SPLIT.md commits C. The inventory's
  lifetime-bytes top-20 must NOT be used (peeks at holdout volumes).
- Holdout bytes: filename-date split, hash raw bytes, never decode
  before freeze. DQ reports are DEV-only until verdict-time validation.
- Metrics pull is request-heavy (~1 file/symbol/day): two-pass pull —
  pass 1 klines/funding/mark, then metrics only for symbols that ever
  enter the trailing top-30 universe (computed from DEV+filenames... no:
  universe membership uses klines closes — a return look. Restrict
  membership computation to DEV-period klines; holdout-only entrants get
  metrics pulled at verdict time if needed. Document in pull plan.)

## Resume note (2026-10-18 evening)

First non-DONE task is E1.2, then E6.1. Do not decode holdout.
Independent reviewers confirmed, and this run fixed before any lake eval:
- `slow_stats.deflated_sharpe` now uses non-annualized SR and sqrt(T-1)
  (annualized plug-in was a false DSR≈1). Pinned at 0.97137 in
  `test_dsr_exact_and_monotone`.
- Holdout lb80 is the 20% bootstrap order statistic (`lower_q=0.20`),
  not the 10% end of a two-sided 80% interval.
- Backtester: liquidation fills at the breaching wick; stops are
  time-sorted inside [d, d+1d) and later funding is not charged after
  the stop; drawdown is a positive fraction in both engines; zero-vol
  positive equity is infinite Sharpe and leak-flagged; missing-bar
  trail stats fall back to the previous bar; exact-zero targets are
  not counted as drops.
CJK vision URLs are percent-encoded (`_ascii_url`). Pull resumed after
that fix; seal holdout bytes (hash only) the moment the pull exits,
before `build_lake` or any return statistic.

## Commands run

- E0 suite nobench → `edge-suite-nobench.log`: 1501 passed, 1 skipped.
- E0 suite bench (background) → `edge-suite-bench.log`.
- E0.2 autopilot run-once → RC=0, all DEV_EVAL.
- E1.1 `tools/vision_inventory.py --out /tmp/vision-inventory.json`.
- Probes: metrics/funding curl 200, formats confirmed.
