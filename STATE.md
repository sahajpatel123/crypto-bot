# STATE — live/edge-sprint (Family B: low-frequency edge search)

Worktree: `/Users/sahajpatel/Code/cryto-bot-edge`
Branch: `live/edge-sprint` from `live/final-hardening` tip `a313254`
Date: 2026-10-18. Closeout 2026-10-19: read `PROJECT_CLOSEOUT.md` first.
Review date 2026-12-18. Resume at the closeout section, not at a new hypothesis.
Prior run (F0–F9) history is in git (`a313254` and below).
Rules: no orders, no keys, human-only arm, machine-written verdict/gate/
vault/autopilot artifacts, every claim cites command+output or file path.

## Completion checklist

| Item | Status | Evidence |
|---|---|---|
| Suite green, 0 failed | DONE | closeout: 1640 passed, 1 skipped, 0 failed in 1566.76s (`/tmp/closeout-suite.log`, EXIT:0) |
| Split + holdout sealed BEFORE analysis | DONE | chunk-2a22e52c3c8f50db before lake returns; B4 screen chunk sealed before its decode |
| Preregs committed before evaluations | DONE | b0b4ac4 / 70e2f38 |
| Leak tests present and passing | DONE | shift, shuffle, Sharpe>3, B1 future-bar test |
| Differential test passes | DONE | `test_differential_vectorized_vs_event` |
| Every verdict machine-written | DONE | `research/verdicts_b/B4.json` is void; `invalidations.json` names `2974cc1a…` (D-042) |
| RESEARCH_VERDICTS_B.md maps to verdict JSONs | DONE | |
| Arm/gate refusal tests pass | DONE | `test_autopilot_gate.py` arm refusals |
| OWNER_ACTIONS.md one ordered list | DONE | steps 1–17 |

## Task table

| ID | Task | Status | Evidence |
|---|---|---|---|
| E0.1 | Re-entry: read memory, full suite 0 failed | DONE | 1501 passed/1 skipped nobench + 27 bench = 1528/1/0 failed |
| E0.2 | Autopilot run-once Family A, record dev outcomes | DONE | closeout: H1–H6 UNDERPOWERED/AWAIT_DATA (`research/autopilot/dev/H*.json`) |
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
| E6.1 | DEV evaluation, all trials counted, kill failures | DONE | B1–B7 KILLED; 59 trials (`dev/B*.json` n_trials) |
| E6.2 | Freeze survivors, holdout screen once via verdict | DONE | B4 screen void (D-042); chain `research/verdicts_b/invalidations.json` |
| E6.3 | Autopilot Family B extension (FROZEN/HOLDOUT_SCREEN/SCREEN_PASS/FORWARD_*) | DONE | B1–B7 state KILLED; invalidated verdicts are refused |
| E6.4 | RESEARCH_VERDICTS_B.md from machine JSONs | DONE | |
| E7 | Slow paper path for the SCREEN_PASS | DONE | no survivor; `SLOW_ENGINE_DESIGN.md`; forward clock not started |
| E8 | OWNER_ACTIONS + README/ARCHITECTURE/RUNBOOK | DONE | steps 15–17 |
| E9 | FINAL_STATUS.md | DONE | see FINAL_STATUS.md; closeout supersedes any SCREEN_PASS reading |

## Owner hurdle review (2026-10-19)

`cryptobot monitor` on the committed DEV artifacts: NO-GO,
HURDLE_UNMET. Best result B4 OOS Sharpe 4.396, max drawdown 0.47%.
A 2%/day mean at that Sharpe would need ~8.7% daily vol. Plan:
`UPGRADE_PLAN.md`. Decision: D-047. No prereg edited. No cell retuned.

## Operational completion (resume the first non-DONE row)

Work on `release/v1` at `v1.0-final` and after. Gate stays NO-GO.
No demonstrated edge.

| ID | Task | Status | Evidence |
|---|---|---|---|
| A | Command matrix + selftest | DONE | `cryptobot selftest --all` PASS, 57 commands, 132 checks, `COMMAND_MATRIX.md`. Exact exits, creds/bare/monitor checks (D-048) |
| B | Exchange emulator + drill + soak | DONE-MINIMAL | Real-socket drill 8 cells PASS + 24-step soak, EMULATED-stamped incl. lists, gate rejects. Full WS streams, tick/step server checks, 418/502/504, SIGKILL-resume are future work (D-048) |
| C | Operator commands | DONE | `cryptobot ops` incl. STOP/TP via algo, post-only, cancel/cancel-all, flatten, kill; prod refuses every action; 10 tests in `test_ops_commands.py` (D-048) |
| D1 | Move data root | CUT | `EXTERNAL_DATA_ROOT` empty. Data stays in the worktree. D-046 |
| D2 | Recorder coverage | DONE | `RECORDER_COVERAGE.md`. H4 other venues IMPRACTICAL-BY-RESOURCE (D-046) |
| D3 | C1 timeline | DONE | `c1_final_utc`. Test `test_c1_final_date_never_passes_the_grace`. Force-close stays at T per frozen prereg (D-048) |
| D4 | Sleep / gap notify | CUT | caffeinate is already in the recorder plist. A new gap notifier was not added |
| D5 | background install/status | DONE | `cryptobot background status` prints the adjudication date. install.sh uses `$ROOT/.venv` (D-048) |
| E1 | owner wizard | DONE | `cryptobot owner` prints PASS/TODO + send-back, validates --step (D-048) |
| E2 | README quickstart | DONE | fresh clone `/tmp/cryptobot-ops-clean2` at `3bf4baa`: install 1.3s, doctor READY, selftest 132/0 PASS, drill 8 cells EMULATED + soak 24h, final-status/owner/background/monitor/ops all run. `release/cleanroom-ops2.log` ends CLEANROOM_OK |
| E3 | certify | DOING | `cryptobot certify` exit 0 on `e7babf2` (132/0, 57 cmds). Final cert after suite + clean-room |
| E4 | suite + tag | DOING | final full suite + tag after E2/E3; `v1.0.0` stays at `82582f0` |

## Consolidation task table (resume the first non-DONE row)

| ID | Task | Status | Evidence |
|---|---|---|---|
| Z0 | Re-entry | DONE | tip `00474c1` tag `closeout-v1`. Dirty before Z1.1: OWNER_ACTIONS.md, RESEARCH_VERDICTS_B.md, SLOW_ENGINE_DESIGN.md, research/autopilot_b/dev/B2.json, B4.json, reports/2026-10-18.json, state/B1–B7.json, transitions.json, transitions.json.VOIDED-foreign, untracked dev/_family.json |
| Z1.1 | Provenance: archive or commit dirty Family B | DONE | restored to committed artifacts; `archive/z1.1-uncommitted.patch`; D-044 |
| Z1.2 | release/v1, tag v1.0-closeout, bundle + tar | DONE | tag `v1.0-closeout` = `d3e0ba7`; branch `release/v1`; `release/v1.0-closeout.bundle`, `release/research-artifacts.tar`, `release/SHA256SUMS` |
| Z1.3 | Holdout map + INC-1 | DONE | `tools/holdout_reconcile.py`; `release/holdout-reconcile.json` subset_ok false (132/198 and 132/202 inside chunk-2a22; spot and rest_tail outside); D-045 |
| Z1.4 | Clean-room proof | DONE | clone of `release/v1.0-closeout.bundle` at `d3e0ba7` (`release/cleanroom.log`). `uv sync --locked` then `--extra dev`. Pytest on Python 3.12: 3 failed, 1640 passed, 1 skipped; failures are `copy.replace` (3.13+). Fixed with `dataclasses.replace`; those 3 tests pass on the 3.12 venv. Acceptance RC 0. Gate NO-GO RC 2. Arm REFUSED TTY RC 2. B1 and B6 rederive MATCH (`release/rederive.log`) |
| Z2.1 | Configurable data root | DONE | `src/cryptobot/research/data_root.py`, `tests/unit/test_data_root.py`, `research/DATA_ROOT.md` |
| Z2.2 | Family A dev eval on pilot + benchmark | DONE | `tools/family_a_dev.py` on external pilot (29 days, no quote channel) and local benchmark (aggTrade 248, fundingRate 10, markPrice 248). H1–H6 UNDERPOWERED/AWAIT_DATA. `estimate_power([])` IMPOSSIBLE, days_required null. Report `research/autopilot/reports/family-a-z2.json` |
| Z3 | Passive launchd jobs + RECORDER_COSTS.md | DONE | `deploy/macos/install.sh` loaded 5 agents. 18:36 elapsed, heartbeat fresh, 3 sealed chunks, manifest chain clean, vault head unchanged. Costs in `RECORDER_COSTS.md`: 9.9% of one core, 58.21 MB/hour, ~12 days to the 8192 MB guard |
| Z4 | C1 B4b prereg before any forward read | DONE | `research/prereg/C1-b4b-carry.md` and `research/configs/C1.toml` committed before any forward read. Confirmation cell k=1.5, drift_band=0.05. Holdout BURNED |
| Z5 | Adjudication table + cryptobot adjudicate | DONE | `research/prereg/ADJUDICATION.md` committed before launchd. `cryptobot adjudicate` hash chain. Tests: ARCHIVE_NEGATIVE unloads plists, PAPER_ONLY, READY_FOR_HUMAN_DECISION, SYNTHETIC refused, AWAIT_DATA force-closed. C1 holdout burn appended on `invalidations.json` |
| Z6 | PROJECT_FINAL_REPORT.md + final-status | DONE | `PROJECT_FINAL_REPORT.md`. `cryptobot final-status` prints H1–H6 AWAIT_DATA, B1–B7 KILLED, C1 AWAIT_FORWARD, adjudication WAITING |
| Z7 | Suite green, tag v1.0-final | DONE | Python 3.12 full suite: 1656 passed, 1 skipped, 0 failed, 1634.42s (`/tmp/z7-suite.log` EXIT:0). Tag `v1.0-final` |

## Closeout (2026-10-19)

Evidence page: `PROJECT_CLOSEOUT.md`. Tag `closeout-v1`.

- C1: `research/verdicts_b/B4.json` document_sha256
  `2974cc1a24cdc1ef99238380919a9070e271427798482a5ded351e03bda028e8`
  is invalidated in `research/verdicts_b/invalidations.json` (D-042,
  25% per-leg clip). Verdict, autopilot, and gate refuse a listed hash
  and refuse a broken chain. Tests: `tests/unit/test_invalidation.py`.
- C2: three holdout decodes, all consumer `verdict`, hypothesis B4
  (chunks `c87821b135ac9667` twice, `74e0747f6d1aab3a` once). Holdout
  is clean for H1–H6 and B1–B3, B5–B7. BURNED for B4 and any B4
  variant. Future carry variants confirm on FORWARD data only.
- C3: H1–H6 `AWAIT_DATA`. `estimate_power([])` is IMPOSSIBLE
  ("fewer than 2 dev trades"); `days_required` is null. Stores
  `data/pilot` and `datasets/benchmark_30d` are absent. Preregs
  unedited.
- C4: `PROJECT_CLOSEOUT.md`. Review date 2026-12-18.
- C5: suite 1640 passed, 1 skipped, 0 failed, 1566.76s,
  `/tmp/closeout-suite.log` EXIT:0.

No new research. Recorder disk/day and CPU were not measured: no
recorder process on this host, and `/opt/cryptobot/data/recorder` is
absent.

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

## Official holdout chunks (E6.2 use; latest per leg, zero pre-freeze decodes)
- klines: chunk-3f104eec72e7d745 (34,760)
- markPriceKlines: chunk-62e972497f0e2c52 (35,494)
- premiumIndexKlines: chunk-d77aca777ad358c9 (32,189)
- fundingRate: chunk-2c330fb27f671e68 (16,105)
- metrics: chunk-231cc79b795dd852 (123,414)
- spot: chunk-10f9e3e4e089375a (66)
- rest_tail: chunk-2df6f950d29a75ac (6,712)
Superseded (same bytes, older seals): chunk-e3ca72/chunk-4cb724/chunk-af97c4/chunk-24045b.
Foreign all-in-one chunk-2a22 + foreign B4-screen chunk-c878 (2 post-freeze decodes) exist but are NOT used officially. My voided B4 screen decoded chunk-74e0 once (superseded by D-042 rerun).
