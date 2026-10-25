# Command matrix

Generated from the CLI parser. A row is PASS only when `cryptobot selftest` exercised it. Modes: replay, paper, emulator-demo (paper or the live adapter pointed at 127.0.0.1), prod.

| Command | Mode | Expected | Test |
|---|---|---|---|
| `cryptobot doctor` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot run` | replay, paper, emulator-demo, prod | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot replay` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot status` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot stop` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot readiness` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot preflight` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot reconcile` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot report` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot backtest` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot latency-probe` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot data verify` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot compact` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot verdict` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot gate` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot arm` | n/a | prod and arm refuse without a human TTY arm | PASS |
| `cryptobot autopilot run-once` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot autopilot status` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot autopilot report` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot research register` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot research power` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot demo-drill` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot recorder start` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot recorder stop` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot recorder status` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot recorder verify` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot vault seal` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot vault freeze` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot vault issue-token` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot vault verify` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot vault verify-holdout` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot vault holdout-eligible` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot calibrate` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot fixtures ingest` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot host-check` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot dashboard` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot adjudicate` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot final-status` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot acceptance` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot monitor` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot selftest` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot emulator serve` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot emulator drill` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot ops status` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot ops positions` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot ops orders` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot ops pause` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot ops resume` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot ops cancel-all` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot ops cancel` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot ops flatten` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot ops kill` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot ops order` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot background install` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot background uninstall` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot background status` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot owner` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
| `cryptobot keys set` | n/a | secret-safe entry (getpass or `--from-stdin`); `--profile prod\|demo` picks CRYPTOBOT_API_* vs CRYPTOBOT_DEMO_*; refuses a tracked or unignored path | PASS (help/bad-flag); behavior: unit |
| `cryptobot keys status` | n/a | both profiles, booleans and backends only, never a value; non-zero when the selected profile is missing or storage is unsafe | PASS (help/bad-flag); behavior: unit |
| `cryptobot keys check` | n/a | signed apiRestrictions table; `--profile prod` targets api.binance.com, `--profile demo` the demo host; exit 0 pass / 2 violation / 3 network-or-auth | PASS (help/bad-flag); behavior: unit (injected transport) |
| `cryptobot certify` | n/a | works, or a clear non-zero refusal with no traceback | PASS |
