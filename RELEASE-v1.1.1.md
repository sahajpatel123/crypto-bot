# v1.1.1 — hermetic unit suite, scheduled verdicts (gate still NO-GO)

**What this tag is:** two surgical fixes on top of v1.1.0 (`36774a77`) and nothing else. No
strategy is armed, no threshold, prereg, holdout or gate changed, and the recorder is
untouched. The gate at this tag is still **NO-GO**; `cryptobot arm` and
`cryptobot run --mode prod` refuse exactly as they did at v1.1.0, and the gate-by-gate ruling
in `research/PROGRAM_CLOSEOUT.md` stands unchanged.

**New in this release**

- **The unit suite no longer depends on file order.** `tests/unit/test_netguard_integration.py`
  failed 2 tests when `tests/unit/test_net_guard.py` ran first (17 passed when the files were
  swapped): a process-global left behind by the earlier file meant the fresh DoH `lookup` was
  never consulted, so the transport dialled the real venue and timed out. The `shim` fixture
  now uninstalls any prior shim and drops the cached `urllib` opener before installing, and
  `tests/unit/test_net_guard.py` uninstalls after every test, so no file can leak that state
  into another. Test-only change: no product code, no runtime behaviour.
- **`verdict-watch` and the daily P&L are scheduled, not left to the owner.** `deploy/macos/install.sh`
  installs two new plain `StartCalendarInterval` agents: `com.cryptobot.verdict-watch` runs
  `.venv/bin/python -m cryptobot.cli verdict-watch --once` daily at 04:00, and
  `com.cryptobot.pnl` runs `.venv/bin/python -m cryptobot.cli pnl daily --out
  data/pnl/daily.json` daily at 04:15. Both read only, neither has `KeepAlive`, neither
  touches the recorder, and `tests/unit/test_deploy_launchd_agents.py` asserts both agents
  exist and that their commands parse in the CLI the installation ships.

**Unchanged at this tag:** the gate, the thresholds, `research/`, the sealed holdout, the
recorder, the alert sinks and every live-safety refusal.
