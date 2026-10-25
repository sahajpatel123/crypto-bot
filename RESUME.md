# RESUME — crypto-bot state

Last checkpoint: 2026-10-25 ~05:10 UTC. Owner: Sahaj. Gate: **NO-GO** (no strategy has passed; holdout sealed).

Read this first after any interruption. Then check `git log --oneline -5 origin/live/hardening`
and the PR list.

## Where the code is

| Ref | SHA | State |
|---|---|---|
| `origin/live/hardening` | `0c2ccc4` | **Merged base.** PR #21 landed. Installs and runs green. |
| PR #23 `reason/b4b-forward-basis-study-62b3f9db` | `64d5989` | Open. Merge of `8afd7d5` onto `0c2ccc4`. Lint + typecheck green; test job in progress. Awaiting independent re-review. |
| `reason/resume-state` | this commit | Docs-only: this file. |

`live/hardening` at `0c2ccc4` was verified locally, not just by badge:
`uv sync --locked --extra dev` exit 0; **1510 passed, 3 skipped** (unit);
**180 passed** (acceptance); `ruff check src tests` **0 findings**; collection
**1513 tests, 0 errors**.

PR #21 carried the real base repair: the spliced `uv.lock`, the duplicate `cmd_gate`
in `src/cryptobot/cli.py`, the `-2013` grace window, proof-by-id reconciliation,
marked venue equity, clamped reduce-only legs, and the CI step-masking fix
(one interpreter per step, blocking `uv sync --locked`, 60 min timeout).
The arm test now asserts a refusal for each of the six CI env markers.

## In flight

- **PR #23** (B4b forward basis study). Content is research-only vs base: `.gitignore`,
  `DECISIONS.md` (D-051..D-056), `RESEARCH_VERDICTS_B.md`, `research/prereg/B4b-forward-basis.md`,
  `family_b_driver.py`, `slow_stats.py`, `tools/forward_b4b.py`, `tools/run_family_b.py`,
  `tests/unit/test_forward_b4b.py`, `tests/unit/test_stats_confidence.py`.
  At `64d5989`: `ruff check src tests` clean; **38** research tests pass.
  Independence rule: **#23 does not merge until an independent reviewer re-checks the
  eight findings and CI is green.** The B4b session must not merge it itself.
- **Recorder** repaired (below). Watch the first closed chunk to confirm it is writing.

## Market-data recorder — repaired 2026-10-25T05:05Z

It had been **dead since 2026-10-20T07:19Z** (pid 25570 gone). Two causes, both fixed:

1. Every `com.cryptobot.*` launchd agent was **explicitly disabled**
   (`launchctl print-disabled` showed recorder/watchdog/autopilot/refresh/adjudicate
   => disabled).
2. The plist pointed at `/Users/sahajpatel/Code/crypto-bot-edge`, which **does not
   exist**. The real tree, with the code and all recorded data, is
   `~/Code/cryto-bot-edge` (typo).

Repair applied: backed up the plist (`com.cryptobot.recorder.plist.bak-<timestamp>`),
rewrote the four `crypto-bot-edge` paths to `cryto-bot-edge`, then `launchctl enable`
+ `bootstrap` + `kickstart` for **recorder only** — the trading-side agents
(autopilot, watchdog, adjudicate, refresh) were left disabled on purpose.

Now: one instance, `cryptobot.cli recorder start --symbols BTCUSDT,ETHUSDT
--chunk-seconds 300 --disk-budget-mb 8192`, out `~/Code/cryto-bot-edge/data/recorder`.
Resumed at chunk **rec-000395-20261025T050538Z**; series is continuous from
`rec-000000-20261018T213756Z` (~397 chunks, 2.1 GB). KeepAlive is on.

**Never start a second recorder.** Check with
`ps -axo pid,command | grep 'cryptobot.cli recorder' | grep -v grep` and the pid file
`~/Code/cryto-bot-edge/data/recorder/recorder.pid`.

Two standing risks here:
- `~/Code/cryto-bot` is at `83b24c7`, **behind `0c2ccc4`**, and that commit has no
  `recorder` subcommand. The recorder therefore runs with
  `PYTHONPATH=~/Code/cryto-bot-edge/src` and `CRYPTOBOT_ROOT=~/Code/cryto-bot-edge`.
  Do not "fix" the plist back to the main checkout without first fast-forwarding it.
- The Mac has **8.9 GiB free (96% used)**. Recorder data is capped at 8 GB by
  `--disk-budget-mb`, currently 2.1 GB, so growth is bounded but the machine is tight.

## Strategy numbers (after fees, slippage, funding)

| Study | Verdict | Key numbers |
|---|---|---|
| B4 delta-neutral basis/carry (backtest) | **Killed** | Holdout burned (`release/holdout-reconcile.json`, three decodes). Turnover 17.05 vs frozen 12 — but that cap double-counts cost and measures no capacity. Nothing rescored. |
| B4b forward basis/carry | **UNDERPOWERED** | 0 of 90 forward days, 0 of 20 round trips. Forward clock starts 2026-11-01. No result exists yet. |
| B4 DSR (recomputed) | Passes 0.80 | 0.9464 at n_eff 91.5; **0.8211** at the real 30-day hold cap; 0.8055 as the runner calls it. The 0.7838 / "22.5 bets" figure in older notes is **impossible** (implies a 40.7-day hold) — it was wrong. |

B4b gate set (frozen, prereg `research/prereg/B4b-forward-basis.md`): Sharpe >= 0.70;
> 0.30 at 2x cost; DSR >= 0.80 at N=10; PBO <= 0.30; DD <= 35%; >= 2 positive calendar
years with >= 60 forward days each; median participation <= 1% and max <= 5% of ADV;
block-bootstrap lower bound > 0; Newey-West t(30) >= 2.0. Costs 49 bps round trip plus
`0.5*sigma*sqrt(Q/ADV20)` impact per fill. One look, at >= 90 days AND >= 20 round trips.

**A 90-day look can only KILL.** The years gate needs 121 forward days (2027-03-01),
and it is blocking and non-structural, so a PASS is impossible before then.

## Next steps, in order

1. PR #23: wait for the independent reviewer's verdict on `64d5989` and for the test
   job. Merge only if both are good; otherwise bound the fix and re-review.
2. Confirm the recorder closed chunk 395 and advanced `heartbeat.json` past
   2026-10-20T07:19:41Z. If not, read `~/Library/Logs/cryptobot/recorder.err`.
3. Once #23 is merged: re-run the base gates at the merge commit (`uv sync --locked
   --extra dev`, unit + acceptance, `ruff check src tests`).
4. Run `tools/forward_b4b.py` against whatever forward data exists; expect
   UNDERPOWERED until 2026-11-01 + 90 days. It must fire automatically when the
   thresholds are met — no manual look.
5. Keep the sealed holdout sealed. No rescoring of B4. No orders; trade-only keys,
   withdrawals disabled; the live switch stays with the owner via `cryptobot owner`.

## Ground rules for the next session

- `ruff check src tests` is the CI lint scope (ruff 0.17.1, blocking). `tools/` is not
  linted by CI; 138 findings live there and are not a merge blocker.
- CI installs `--extra dev` and calls `.venv/bin/pytest`. `uv run pytest` fails
  (`Failed to spawn: pytest`) because pytest is not in a dependency group.
- A bare `uv sync --locked` on Python 3.15 picks 3.15.1 and cannot build
  `nautilus-trader`; pin 3.12-3.14. CI pins 3.12.
- Mutations are the test of a test: for every guard, delete it and confirm a named
  test fails. Two were proven this way (spot accrual -> 1178.69 vs 1260.91;
  years 60->30 -> both years-gate tests).
