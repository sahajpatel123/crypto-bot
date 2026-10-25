# RESUME — crypto-bot state

Last checkpoint: 2026-10-25 (PR #26). Owner: Sahaj. Gate: **NO-GO** (no strategy has passed; holdout sealed).

Read this first after any interruption. Then check `git log --oneline -5 origin/live/hardening`
and the PR list.

## Where the code is

| Ref | State |
|---|---|
| `origin/live/hardening` (`9dc49f9` at the last check) | Merged base: PR #21 (repairs), #23 (B4b forward study), #25 (this file). |
| PR #26 `netguard` | DNS-sinkhole fallback, host-check row, docs. See "Network" below. |

Last verified base gates (at `0c2ccc4`): `uv sync --locked --extra dev` ok; **1510 passed,
3 skipped** (unit); **180 passed** (acceptance); `ruff check src tests` 0 findings. Re-run in
CI after each merge; do not run full suites on the owner's Mac (below).

## Network: Binance is NOT geo-blocked; the ISP's DNS sinkholes it

Root cause (verified 2026-10-25, Ahmedabad, Reliance Jio): Jio's resolver answers
`*.binance.com` and `*.okx.com` with `49.44.79.236` (a dead host), so every connect times
out. Real addresses via DoH (`1.1.1.1`/`8.8.8.8`) work: fapi REST 200, fstream websocket 101,
demo-fapi 200. SNI/certs are unaffected. Earlier notes saying "needs a VPN" were wrong.
`data.binance.vision`, `testnet.binancefuture.com`, `api.bybit.com` are not sinkholed. Cloud
machines get HTTP 451 from fapi (US geo-block); that is a different problem.

Fix: opt-in `CRYPTOBOT_DOH=1` (`src/cryptobot/netguard.py`, called from `cryptobot.cli.main`
and the exchange-facing tools; `tools/netshim/sitecustomize.py` for processes that cannot
import cryptobot). `cryptobot host-check` has a `dns-sinkhole` row that FAILs only when the
system address is dead and the DoH address connects. Off by default. See `tools/netshim/README.md`.

## Market-data recorder (state 2026-10-25)

- One instance only: launchd `com.cryptobot.recorder`, tree `~/Code/cryto-bot-edge`
  (typo is real), env `PYTHONPATH=~/.cryptobot/netshim:~/Code/cryto-bot-edge/src`,
  `CRYPTOBOT_DOH=1`, `--symbols BTCUSDT,ETHUSDT --chunk-seconds 300 --disk-budget-mb 8192`,
  data `~/Code/cryto-bot-edge/data/recorder`. It was dead 2026-10-20 -> 10-25 (agents disabled
  and the plist pointed at a missing path); repaired, ingress verified 2026-10-25T05:33Z
  (50,400 records in the first 33 s). 400 sealed chunks, 0 gaps in the last three. KeepAlive is
  `SuccessfulExit=false`, ThrottleInterval 30, so a clean stop is not restarted into empty chunks.
- **Never start a second recorder**: `ps -axo pid,command | grep 'cryptobot.cli recorder' | grep -v grep`
  and `~/Code/cryto-bot-edge/data/recorder/recorder.pid`.
- Volume ~1.5-2 GB per UTC day. `--disk-budget-mb` is a FREE-SPACE floor (checked on
  reconnect; below it the recorder exits 0), not a cap. The Mac had ~8.9 GiB free, so it
  reaches the floor in about 3-4 days: **an owner decision** (free space, point the output at
  other storage, or raise the floor deliberately).
- `com.cryptobot.guard` (every 5 min) restarts the recorder only if none runs, no STOP file
  exists and free space > floor + 1.5 GiB; prunes stale pytest scratch; warns on low runway,
  stale heartbeat, two recorders, or a C2-FWD ledger 2+ days behind. It never touches chunks.
- **Never run full test suites on the owner's Mac**: one `pytest tests/unit` wrote 1.2-2.1 GB
  of scratch (some tests ~137 MB each) and nearly filled the disk. Use CI or the cloud.
- C2-FWD forward recorder: not running anywhere before 2026-10-25; now scheduled on the Mac
  (`com.cryptobot.c2fwd`, 4x/day, worktree `~/Code/cryto-bot-fwd` at `9dc49f9`,
  `CRYPTOBOT_DOH=1`). First ledger row 2026-10-25 (day 2026-10-24). Scoring happens
  automatically at the preregistered 365/730/1095 rows (first ~2027-10-24); no P&L is read before.

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

1. B4b clock starts 2026-11-01; `tools/forward_b4b.py` reads forward data and stays
   UNDERPOWERED until >= 90 days and >= 20 round trips. Earliest possible PASS 2027-03-01
   (years gate needs 121 forward days). A 90-day look can only KILL.
2. Owner decision on recorder disk (above) within ~3 days.
3. After any merge: re-run base gates in CI (`uv sync --locked --extra dev`, unit + acceptance,
   `ruff check src tests`).
4. Keep the sealed holdout sealed. No rescoring of B4. No orders; trade-only keys,
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
