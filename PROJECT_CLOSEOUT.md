# Project closeout (evidence only)

Worktree `/Users/sahajpatel/Code/cryto-bot-edge`, branch `live/edge-sprint`. Review date **2026-12-18**. No new hypothesis was added.

## Hypotheses

| Id | State | Evidence |
|---|---|---|
| H1–H6 | UNDERPOWERED / AWAIT_DATA | `research/autopilot/dev/H1.json`–`H6.json`. `data/pilot` and `datasets/benchmark_30d` are absent, so the dev evaluator had no trades. `estimate_power([])` returns status IMPOSSIBLE, reason "fewer than 2 dev trades", `required_trades` null, `days_required` null. Prereg floors still stand: H1 100 trades/10d (L2 depth), H2 100/20d, H3 100/30d, H4 100/10d (Bybit+OKX), H5 50/10d (liquidations), H6 only after H2/H3; confirmation 300. Preregs were not edited. |
| B1–B7 | KILLED | `research/autopilot_b/state/B*.json`, `dev/B*.json`. Failed gates: B1 OOS/DSR/PBO/plateau; B2 all seven bullets; B3 OOS/DSR/2x/plateau; B4 turnover (corrected 50% legs); B5 OOS/DSR/PBO/plateau/turnover; B6 PBO/plateau/turnover; B7 OOS/DSR/PBO/plateau/years/2x/turnover. |

Trials counted: **59** (`n_trials` 12+6+8+9+8+8+8 on the seven DEV artifacts). Family A grids were not run.

`research/verdicts_b/B4.json` document_sha256 `2974cc1a24cdc1ef99238380919a9070e271427798482a5ded351e03bda028e8` is void (25% per-leg clip, D-042). `research/verdicts_b/invalidations.json` names that hash. Verdict, autopilot, and gate refuse it.

## Holdout decodes

From `data/vault/access_log.json`, consumer `verdict`, all hypothesis B4:

| When (UTC) | Chunk | Chunk sha256 | Token sha256 |
|---|---|---|---|
| 2026-10-18T15:14:54.552172 | chunk-c87821b135ac9667 (198 files) | c87821b135ac9667d8ef780fe3fa2ed611c905b567e7809ab9f67917d2890b8e | 32a0fae8819ed99066d2ef604a83c03993bf7075f35a8709ec3df73067d249ba |
| 2026-10-18T15:15:55.691572 | chunk-c87821b135ac9667 (198 files) | c87821b135ac9667d8ef780fe3fa2ed611c905b567e7809ab9f67917d2890b8e | 8faf71e2a1d7754291e7a5127e3ec7c46c11d2ca7d2fdb142b281c8b5d5ba3d7 |
| 2026-10-18T15:25:38.237970 | chunk-74e0747f6d1aab3a (202 files) | 74e0747f6d1aab3aabec91f3bf524298895440cc560f0835dca430566b576f1f | 0d6ee79f414a9a241d392c631f9753e424180da149a89ac8708637100008cf22 |

Holdout is **clean** for H1–H6 and B1, B2, B3, B5, B6, B7 (no decode names them). Holdout is **BURNED** for B4 and any B4 variant. A future carry variant may only be confirmed on FORWARD data.

## Recorder

This host has no `cryptobot recorder` process, and `/opt/cryptobot/data/recorder` (the unit's `ExecStart` path) is not present, so disk per day and CPU were not measured from a live recorder. The code writes one gzip chunk per hour for BTCUSDT and ETHUSDT and stops if free space is under 50,000 MB (`RecorderConfig.disk_budget_mb`). That figure is a free-space floor, not a measured daily write.

## Rules

If every Family A hypothesis is KILLED, FAIL, or IMPRACTICAL, archive the project as a negative research result and stop the recorder. Any new idea requires a new preregistration with a new information source. No real capital unless the gate is GO and the owner arms.

## How to resume

1. Read this file and `STATE.md`. Confirm `research/verdicts_b/invalidations.json` still verifies (`verify_invalidation_chain` empty) and still names `2974cc1a…`.
2. Leave B1–B7 KILLED. Do not re-decode holdout for B4 or a B4 variant.
3. Family A moves only when the missing dev stores exist. `cryptobot autopilot run-once` then reads `research/autopilot/dev/H*.json`. Until `estimate_power` can see at least two dev trades, the state stays AWAIT_DATA.
4. On 2026-12-18, apply the archive rule above.
5. A new idea starts as a new preregistration and a new information source, then the existing verdict and gate. Capital stays off until a fresh GO gate and an owner arm.
