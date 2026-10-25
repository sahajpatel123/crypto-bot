# v1.1.1 — the daily jobs the release notes promised, and a suite that cannot lie by order

**What this tag is:** two follow-ups to v1.1.0. It changes no trading behaviour, no
gate, no threshold and no strategy. The gate stays **NO-GO** and no strategy is armed.

**What this tag is not:** a new capability. The commands already existed at v1.1.0; this
release makes them run on a schedule and makes the unit suite order-independent.

## New in this release

- **The verdict watcher is actually scheduled.** `cryptobot verdict-watch --once` shipped
  in v1.1.0 with nothing calling it, so "delivers its verdict automatically" was true only
  if the owner wrote cron by hand. `deploy/macos/install.sh` now installs
  `com.cryptobot.verdict-watch`, a plain `StartCalendarInterval` agent that runs
  `verdict-watch --once` daily at 04:00 and records to `data/lake/verdicts/`.
- **A daily P&L agent.** `com.cryptobot.pnl` runs `cryptobot pnl daily` daily at 04:15,
  reading the run journals under `runs/` and writing `data/lake/pnl/latest.json`.
- **The scheduled commands cannot rot silently.** `tests/unit/test_deploy_launchd_agents.py`
  parses the installer, extracts every agent's `ProgramArguments`, and parses each
  `cryptobot.cli` command through the real argparse tree, so an agent pointing at a
  renamed subcommand or a dropped flag fails the suite instead of failing at 04:00.
- **The unit suite is order-independent.** `tests/unit/test_netguard_integration.py`'s
  `shim` fixture now tears down any process-global state an earlier file left behind
  (the DoH shim and urllib's cached opener) before installing its own, and
  `tests/unit/test_net_guard.py` uninstalls the shim after every test. At v1.1.0 the two
  files in one process failed with 2 errors and passed alone; the suite no longer depends
  on file order or on reaching the network.

## Unchanged on purpose

The recorder (`com.cryptobot.recorder`), the frozen holdout, the preregistered rules and
the gate are untouched. The two new agents are independent calendar jobs: they never load,
unload, restart or write near the recorder, and they open no venue connection.
