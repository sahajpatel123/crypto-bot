# RESUME — crypto-bot state

Last checkpoint: 2026-10-25. Owner: Sahaj. Gate: **NO-GO**. No strategy has passed; the holdout is sealed.

Read this first after an interruption. Check `git log --oneline -5 origin/live/hardening` and the live PR list for current code and review state.

## State as of 2026-10-25T07:10Z

BASE
- live/hardening head = fc92c45 ("tests: stop pytest scratch filling laptop disks (#28)", push run 40170792405, lint/typecheck/test all success, test job 12.1 min).
- #27 merged (docs/research ledger row). #28 merged. Nothing unreviewed on the base.
- Historical baseline test-job duration on this repo: 12.1 min typical, 22.2 min worst observed (run 40169206876). Use this before calling any test job hung.

OPEN PRS
- #26 head e401b83, base live/hardening, open, not draft, merge_state unstable. lint success, typecheck success, test x2 in progress. Test step "Unit tests" started 06:47:16Z and was still running at 07:08Z = slow runner, NOT hung; log is not published mid-step.
- #29 head 2e16664, draft, base live/hardening: lint success, typecheck success, one test success, one test in progress. Recorded base_sha 8f0f106, so it is one merge behind fc92c45.
- #20 closed unmerged (superseded), lint failure + test cancelled — historical, not actionable.

RECORDER (measured on the Mac at 07:05Z, via devices_exec)
- Exactly ONE instance: pid 91414 python -m cryptobot.cli recorder start, under caffeinate/nice pid 91416. Same argv, one logical recorder. Do not start another.
- heartbeat.json ts_utc 2026-10-25T07:05:19Z against a 07:05:21Z clock = live.
- chunk rec-000414 (window 07:03:24Z), records 57,200, bytes 1,688,549. Chunks 412/413/414 all written within the last 10 minutes.
- data dir ~/Code/cryto-bot-edge/data/recorder = 2.2 GB total, chunks/ 420 entries.
- --disk-budget-mb 4096. df / = 15 GiB free (55% used).
- IMPORTANT CORRECTION: the earlier "recorder hits a disk cliff in ~7-10 days" is WRONG. The recorder self-caps at a 4096 MB budget and currently uses 2.2 GB, with 15 GiB free. There is no imminent storage cliff and no storage decision is needed from the owner. Remove any such warning from RESUME.md.

GATE (unchanged, NO-GO)
- B4 basis/carry: KILLED, turnover 17.05 vs frozen cap 12.
- C2: KILLED, holdout p=0.154, replication p=0.080.
- B4b forward basis/carry: UNDERPOWERED, 0/90 forward days, 0/20 round trips; forward clock starts 2026-11-01.
- DSR 0.8211 at the real 30-day hold cap (0.8055 as called); the 0.7838 / "22.5 bets" figure is impossible and stays deleted.
- Years gate needs 121 forward days: earliest possible PASS 2027-03-01. D1 unevaluated. Holdout sealed, no orders, no API key reads.

## Post-merge update as of 2026-10-25T08:06Z

BASE
- `live/hardening` is `a6353159a92ede3983f2a53a0a5944dc87cec870`, the squash merge commit for PR #26, with parent `fc92c4576701a9f92a2d7bb55cb94126e727a96b`.
- PR #26 merged at 08:06:35Z from head `4c9a992464989e6899e33665f78389e1eae64157`; all 6 CI checks passed.
- The 07:10Z state block above is preserved verbatim as the requested measured historical snapshot; its PR rows reflect that time. Gate remains NO-GO; holdout sealed, no orders, no API-key reads.

## Network: Binance is not geo-blocked on the Mac; Jio DNS sinkholes it

Verified 2026-10-25 in Ahmedabad: Reliance Jio's resolver answers `*.binance.com` and `*.okx.com` with `49.44.79.236`, a dead host. Real addresses via DoH (`1.1.1.1` / `8.8.8.8`) work; fapi REST returned 200, fstream websocket upgrade 101, and demo-fapi returned 200. SNI and certificate checks are unaffected. Earlier claims that Binance futures was unreachable or needed a VPN were wrong. `data.binance.vision`, `testnet.binancefuture.com`, and `api.bybit.com` are not sinkholed; Cloud fapi HTTP 451 is a separate geo restriction.

The fix is opt-in `CRYPTOBOT_DOH=1`; it is only for a network where `cryptobot host-check` proves sinkholing. It is off by default. CLI and exchange-facing tools install `src/cryptobot/netguard.py`; `tools/netshim/sitecustomize.py` is standalone for processes that cannot import cryptobot. See `tools/netshim/README.md`.

## Recorder and forward data

- One launchd recorder only: `com.cryptobot.recorder`, tree `~/Code/cryto-bot-edge`, `PYTHONPATH=~/.cryptobot/netshim:~/Code/cryto-bot-edge/src`, `CRYPTOBOT_DOH=1`, `--symbols BTCUSDT,ETHUSDT --chunk-seconds 300 --disk-budget-mb 4096`, data in `~/Code/cryto-bot-edge/data/recorder`. Ingress was verified at 2026-10-25T05:33Z (50,400 records in the first 33 seconds). At 07:05Z it had 400 sealed chunks, 0 gaps in the last three, and one harmless unsealed `rec-000396-20261025T051309Z` not in the manifest. The measured volume was about 1.5 GB per UTC day; the recorder self-caps at 4096 MB. With 2.2 GB used and 15 GiB free there is no imminent storage cliff or owner storage decision.
- The recorder plist uses `KeepAlive{SuccessfulExit:false}` and `ThrottleInterval 30`, so a clean stop does not restart into empty chunks. Never start a second recorder; verify the process and `recorder.pid` first.
- `com.cryptobot.guard` runs every 5 minutes. It restarts only when no recorder is running, no STOP file exists, and free space is above the configured threshold; it prunes pytest scratch older than 6 hours only when pytest is not running. It alerts on low runway, stale heartbeat, duplicate recorder, or a C2-FWD ledger 2+ days behind. It never touches chunks, manifest, or ledgers.
- A full `pytest tests/unit` run on the Mac once wrote 1.2–2.1 GB of scratch in about 25 minutes, dropping free space from 9.4 to 3.7 GiB; scratch was removed. PR #28 now configures pytest to retain only failed-test `tmp_path` directories from the latest run and reports residual basetemp size after cleanup; passing tests leave no retained pytest scratch. This does not reduce peak writes during a run: never run full unit or acceptance suites on the owner's Mac. Use CI or Reason Cloud, and put targeted-test scratch under `/tmp` then delete it.
- C2-FWD is running from `~/Code/cryto-bot-fwd` at 9dc49f9 with `CRYPTOBOT_DOH=1`, launched by `com.cryptobot.c2fwd` four times daily (05:50/11:50/17:50/23:50 IST). Its ledger is `data/forward_c2/ledger.jsonl`; first row booked 2026-10-25T05:43Z for day 2026-10-24 (universe 30, 12 positions). Preregistered scoring runs once at 365/730/1095 rows (first about 2027-10-24); no P&L is read before then.

## Gate and next steps

- B4 basis/carry is KILLED (turnover 17.05 vs frozen cap 12); C2 is KILLED (holdout p=0.154, replication p=0.080).
- B4b forward basis/carry is UNDERPOWERED: 0/90 forward days and 0/20 round trips. Its clock starts 2026-11-01; earliest possible PASS is 2027-03-01 because the years gate needs 121 forward days. A 90-day look can only KILL. D1 is unevaluated.
- Keep the sealed holdout sealed. No rescoring of B4. No orders; trade-only keys, withdrawals disabled, and the live switch remains with the owner via `cryptobot owner`.
- Use CI for full unit and acceptance tests. CI runs `uv sync --locked --extra dev`, then `.venv/bin/pytest`; `uv run pytest` fails because pytest is not in a dependency group. CI uses Python 3.12, and the repo supports Python 3.12–3.14; bare sync on 3.15 cannot build `nautilus-trader`.
- Blocking lint scope is `ruff check src tests` (ruff 0.17.1); `tools/` is outside CI's lint scope. Verify netshim/library parity with `python3 tools/netshim/sync_core.py --check`.
