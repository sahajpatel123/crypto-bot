# v1.1.0 — trade-ready build (gate still NO-GO)

**What this tag is:** the operational completion of the bot. Every command works end to
end, a fresh clone installs with one command, credentials are handled safely, an API key
that could move money is refused before anything trades, and the safety layer is proven
by executing tests rather than by assertion.

**What this tag is not:** a profitable bot. No preregistered strategy passed its frozen
gate, so this release ships with **zero armed strategies**. `cryptobot arm` refuses and
`cryptobot run --mode prod` refuses before it reaches the venue. The gate-by-gate ruling
is `research/PROGRAM_CLOSEOUT.md`; the frozen-data record is `research/ARCHIVE_FREEZE.md`.

## Gate at this tag

| Line | Verdict | Decisive number |
|---|---|---|
| B4 delta-neutral basis | **KILLED** | annualised turnover `17.05060731836767` against the frozen cap `12` |
| B4b forward basis | **UNDERPOWERED** | 0 of 90 forward days, 0 of 20 round trips; earliest evaluable 2027-01-29, earliest possible PASS 2027-03-01 |
| C1 TSMOM | **FAIL** | +9.33 bps/day, p `0.1059` against the DEV bar `p <= 0.0125` |
| C2 XSMOM | **KILLED** | replication p `0.0805` against the bar `p <= 0.01` (holdout p `0.154`) |
| C2-FWD | **WAITING** | 1 row booked, first look at 365 recorded days |
| D1 OI-flush reversal | **UNEVALUATED** | DSR not evaluable: `N_TRIALS` is `None` by design, and the recorder carries neither settled funding nor daily klines |
| R3 / C1-b4b carry | **UNCONFIRMED** | 0 of 90 forward days |
| H1–H6, S, X1, H-R2, C3, C4 | **FAIL / UNDERPOWERED** | see `research/PROGRAM_CLOSEOUT.md` §3 |

No line in this repository reached its own promotion or confirmation bar. Holding the
gate closed is the release's most important property.

## New in this release

- **Key handling that cannot leak.** `cryptobot keys set --profile prod|demo` reads the
  key and secret with no echo, stores them in the macOS Keychain (or a mode-0600
  git-ignored file when there is no Keychain), and refuses any target git tracks or does
  not ignore. Nothing prints a value, a prefix or a suffix. `cryptobot keys status`
  reports presence and backend only.
- **A permission check that runs before the first order.** `cryptobot keys check
  --profile prod|demo` signs `GET /sapi/v1/account/apiRestrictions` and fails on an
  enabled withdrawal scope, an enabled universal or internal transfer, a disabled read
  scope, no trading permission, or a key with no IP restriction (`--require-ip`, on by
  default). Exit 0 pass, 2 violation, 3 network or auth failure. The production path
  calls it and refuses to start when it fails, so it is enforcement, not advice.
- **One command from a fresh clone.** `./setup.sh` (or `make setup`) bootstraps `uv`,
  syncs the locked environment, verifies the interpreter, then runs `cryptobot doctor`
  and `cryptobot selftest`, stopping on the first failure.
- **A capital ladder that can rise.** The ladder used to demote only. `cryptobot ladder
  status|promote|demote` now records an evidence-bound promotion: rung history, the
  evidence document's sha256, the commit and the UTC stamp, refusing on missing evidence
  and never skipping a rung. Demotion stays automatic.
- **A daily P&L report.** `cryptobot pnl daily` renders realised P&L net of fees,
  funding, unrealised marks, win rate, per-symbol breakdown and drawdown from the run
  journal, as a table or JSON, and reports a corrupt journal line instead of silently
  dropping it.
- **Verdicts that fire by themselves.** `cryptobot verdict-watch --once` runs the B4b and
  D1 evaluators, records each study's status and code hashes, and exits 10 the moment a
  study's verdict changes — so a look happens when data permits, not when someone
  remembers.
- **A green `selftest --all`.** It was red at the previous tip because an audit test
  asserted that restarting the engine clears a Binance 429 window, while the shipped code
  deliberately persists that deadline across restarts. The safer behaviour stayed and the
  test was re-pinned.

## Verification at this tag

| Check | Command | Result |
|---|---|---|
| Lint | `ruff check src tests` | clean |
| Selftest | `cryptobot selftest --all` | `{"commands": 69, "failed": 0, "passed": 164, "verdict": "PASS"}`, exit 0 |
| Focused suites | `pytest` on credentials, keys check, setup script, ladder promotion, daily P&L, verdict watch | `139 passed`, exit 0 |
| Fresh install | fresh clone + `./setup.sh` | exit 0, doctor READY, selftest PASS |
| Gate | `cryptobot gate` | `NO-GO`, `strategies: []` |
| Arming | `cryptobot arm --capital-usdt 120 --max-daily-loss 6` | refused (no unexpired GO gate), exit 2 |
| Demo drill without keys | `tools/demo_drill_live.py` | `BLOCKED`, exit 2, no traceback |

## Owner sequence

```sh
git clone https://github.com/sahajpatel123/crypto-bot.git && cd crypto-bot
./setup.sh                          # one command: env, doctor, selftest
cryptobot keys set --profile demo    # paste demo keys, no echo
cryptobot keys check --profile demo  # refuses a key that can withdraw
python tools/demo_drill_live.py --execute-orders   # demo-account round trip
cryptobot owner                      # guided checklist
```

Live money stays one command away and gated:

```sh
cryptobot arm --capital-usdt 120 --max-daily-loss 6   # refuses without a GO gate
```

## Safety model

- Every order and position is reconciled against the venue by client order id; an
  unknown outcome is looked up, never assumed.
- A 429/418 window is persisted to the journal and survives a restart; submits
  refuse-fast inside it while cancels and reduces still attempt.
- The emergency path is `cryptobot stop --run-id <id> --flatten`: it halts and flattens.
  `ops kill` is deliberately emulator/sandbox-only and never touches production.
- Hard limits are enforced before submission and by flattening on breach; the operating
  and emergency stops are 0.5% and 1%.
- Arming needs a fresh unexpired GO gate bound to evidence hashes, an interactive
  terminal, a typed acknowledgement, and refuses in any CI environment.
