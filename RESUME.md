# RESUME — crypto-bot state

Snapshot: **2026-10-25 07:54Z**, base `origin/live/hardening` @ `fc92c45` (PR #28).
Gate: **NO-GO**, unchanged. Sealed holdout untouched. No orders, no API-key reads, no live money.
Read this file, then `git log --oneline -5 origin/live/hardening`, then the PR list. That is the
whole handover; do not re-derive anything below.

## 1. Current state

The trading system is in **NO-GO** and no strategy has passed: Family B is closed (B1–B7 all
killed on frozen gates), Family C is closed (C2 killed on replication), D1 is unevaluated for lack
of forward data, and the only live experiment is the C2-FWD forward recorder booking its first
rows. Two things were repaired this milestone and are the reason the state is trustworthy at all:
the **statistical gate** now rests on a provable upper bound `N_max` instead of an unknowable exact
`N` (the old `N >= 470` lower bound silently made the gate *easier*, not safer — see §5), and the
**market-data recorder** is alive and was caught silently discarding three of its five subscribed
streams for the whole 18–25 Oct run, with the fix in PR #33 pending. The recorder is running now on
the owner's Mac (pid 91414, heartbeat fresh) and is the single point of failure for every forward
verdict; nothing that touches Binance can run anywhere else (see §6). The evaluator must consume
`N_max` as one `N_TRIALS` constant and refuse to emit a DSR verdict when it is unset.

## 2. Done and merged into `live/hardening`

Verified directly on GitHub while writing this file, not from notes.

| PR | Title | Head SHA | State / checks |
|---|---|---|---|
| #23 | B4b forward test + two statistics repairs | `64d5989` | **Merged** (merge commit `9dc49f9`). Base for everything below. |
| #27 | docs(research): record Family B diagnostic archive touch | `3c111fa` | **Merged** as `8f0f106` (squash). Docs only. |
| #28 | tests: stop pytest scratch filling laptop disks | `3461180` | **Merged** as `fc92c45` (squash) = current base. Lint/typecheck/test/acceptance green. |

`live/hardening` @ `fc92c457` is the shipped base. CI on it is green (`lint`, `typecheck`, `test`,
`acceptance`).

## 3. In progress — open PRs, by owner

Check state read from GitHub at 2026-10-25 07:54Z. `combined_state` is the aggregate I read.

| PR | Owner / topic | Head SHA | Checks I read |
|---|---|---|---|
| #33 | **Recorder** — record trade flow, fail loudly on a silent stream | `5b1688d` | `lint` success, `typecheck` success, `test` in progress. Mergeable. Ready (not draft). |
| #32 | **E1** — emulator recovery fault matrix | `f785df4` | `lint` success, `typecheck` success, **`test` FAILURE**, second `test` run in progress. Draft. **Do not merge** until the test failure is fixed and re-run. |
| #31 | **Gate audit (G1)** — audit gate statistics on synthetic data | `0de94ea` | `lint`, `typecheck`, `test` all success. Mergeable, clean. Draft. |
| #30 | **C2-FWD** — audit booking and scoring integrity | `8de4979` | `lint`, `typecheck`, `test` all success. Mergeable, clean. Draft. |
| #29 | **D1** — open-interest flush reversal, preregistration only | `1afe667` | `lint` success, `typecheck` success, `test` in progress. Draft. |
| #26 | **Netguard** — opt-in DoH fallback for the ISP DNS sinkhole | `4c9a992` | `lint` success, `typecheck` success, `test` in progress. Ready (not draft). |

Nothing here is a gate verdict. No PR above changes a prereg threshold, a holdout file or CI.

## 4. Next steps, in priority order

1. **#33 recorder streams.** Once `test` is green, merge it — the recorder is losing trade prints
   every hour it is not merged. Then watch the first sealed chunk under the new code and confirm it
   contains `trade_agg` records and that no stream-silent alert fired.
2. **#32 E1.** Fix the failing `test` job (read the job log, reproduce, push a fix). It is a draft;
   do not publish it as ready while red.
3. **#31 and #30.** Both are green and clean. Review the audits and mark ready if the conclusions
   hold; #31 is the one that certifies the `N_max` gate arithmetic, so it should land before any
   evaluator change consumes `N_max`.
4. **#29 D1.** Complete the prereg review and land it — the D1 run is blocked on one look being
   defined before any forward data is read. Then D1 stays `UNEVALUATED` until forward data exists.
5. **#26 netguard.** Green but larger (24 files, +3,016). Merge only with an independent review;
   it touches networking that every recorder restart depends on.
6. **C2-FWD.** Keep the 4×/day launchd job (`com.cryptobot.c2fwd`) running; scoring looks at
   365/730/1095 rows only, so nothing is readable yet. Never read its P&L early.
7. **Do not re-open Family B or C, and do not rescore B4.** The holdout is spent.

## 5. Key numbers

### DSR is unevaluable — and that no longer matters

Exact `N` (the true number of trials) is **unavailable**. The H1–H6 DEV summaries and the B1–B7
aggregates carry no run keys tying a config to its fold/split or confirmation run, and they do not
establish whether the H3-on-H2 and H6-on-H2/H3 filter applications ever ran. No H/B run-key manifest
exists; the only one in the tree is `trials/x1-run-manifest.json`, which is not verified as H/B-specific.
Rather than guess, the gate was rebuilt to stop needing it.

**Correction, recorded because the old note was reassuring in the wrong direction.** The earlier
`N >= 470` was a **lower** bound, and the DSR null `SR0` **rises** with `N`. A low `N` made the gate
**easier**, not safer — the registered gate was optimistic, not conservative.

| `N` | DSR null `SR0` |
|---|---|
| 470 | 3.0339 |
| 1000 | 3.2551 |
| 1470 | 3.3631 |
| 5000 | 3.6877 |

(Computed from `expected_max_sharpe(n, sr_variance)` — the standard `E[max]` of `N` skill-less
Sharpes, `(1-γ)Φ⁻¹(1-1/N) + γΦ⁻¹(1-1/(Ne))`, at unit per-period Sharpe scale. Re-verified while
writing this file; reproduces to 4 dp.)

**Superseded by R2's `N_max`:** a provable **upper** bound built from the declared grid maxima —
`cells × folds × confirmations × filter applications × aborted runs` — written as arithmetic that is
recomputable from the preregistration text alone. `N_max >= true N` by construction, so the exact
`N` is no longer required and **its absence cannot weaken the gate**. The evaluator consumes `N_max`
as a single `N_TRIALS` constant and **must refuse to emit a DSR verdict when it is unset**. Refusing
is correct behaviour, not a bug to work around.

### Gate state: NO-GO

| Study | Verdict | The number |
|---|---|---|
| B4 delta-neutral basis (backtest) | **KILLED on turnover** | turnover **17.05** (`17.05060731836767` in `research/autopilot_b/state/B4.json`) against the frozen cap **12** (`research/prereg/B4-delta-neutral-basis.md`: "turnover ≤ 12×. Any miss KILLS B4"). Holdout burned. Nothing rescored. |
| B4b forward basis | **UNDERPOWERED** | **0 of 90** forward days and **0 of 20** round trips. Stopping rule in `research/prereg/B4b-forward-basis.md` needs *both*. |
| C2 XSMOM replication | **KILLED on replication** | **p = 0.080** against the preregistered bar **p ≤ 0.01** (`research/DATA_LEDGER.md`, `RESEARCH_VERDICTS.md`). Family C closed. |
| D1 open-interest flush | **UNEVALUATED** | Pending forward data; prereg still a draft (#29). |

B4b's cost model, unchanged: 49 bps round trip plus `0.5·σ·√(Q/ADV20)` impact per fill.
A 90-day look can only **KILL**: the ≥2-positive-calendar-years gate needs 121 forward days
(2027-03-01), so PASS is impossible before then.

### Recorder (owner's Mac, read-only check 2026-10-25 07:42Z)

- Exactly **one** recorder: pid **91414**, launchd job `com.cryptobot.recorder`, plus its
  `caffeinate` wrapper (pid 91416). Budget `--disk-budget-mb 4096`.
- `heartbeat_age_s` **0.0156**; free **12,295 MB** against the **4,096 MB** floor; runway **166.7 h**.
- `c2fwd` days_behind **0**, **1** row booked; `stop_file` **false**; data volume **11.8 GiB** available.
- Re-checked minutes later while writing this: heartbeat advancing (chunk `rec-000424-…T075325Z`),
  still one pid, but free space had fallen to **9,463 MB** — other sessions' checkouts are what move
  this number, so treat the 166.7 h runway as a snapshot and re-read it, do not plan against it.

### The recorder stream gap (measured, not inferred)

For the whole 18–25 Oct run the recorder subscribed to five Binance streams and wrote only some.
Chunk `rec-000417-20261025T071824Z` holds **96,273** `book_ticker`, **5,874** `depth`, **10**
`open_interest`, **10** `premium_index`, **10** `depth_snapshot`, and **ZERO** `trade`, mark-price or
liquidation records (counted from the sealed chunk while writing this file — the totals reconcile
exactly with the per-symbol split: 39,637 BTC + 56,636 ETH bookTicker).

Cause: `aggTrade`, `markPrice@1s` and `forceOrder` complete the handshake and then **send zero bytes,
silently** — no close, no error, no timeout. Fix in **#33**: per-second `trade_agg` buckets instead of
raw prints (raw prints do not fit the 4 GB budget), a sealed chunk now raises a **stream-silent alert
naming any subscribed stream that produced no record**, and mark price continues to come from the 60 s
REST `premiumIndex` poll. **Nothing here was a disk-budget or priority cut** — do not "fix" it by
raising the budget.

## 6. Standing safety rules

- **Never start a second recorder.** Check first:
  `ps -axo pid,command | grep 'cryptobot.cli recorder' | grep -v grep` and
  `~/Code/cryto-bot-edge/data/recorder/recorder.pid`. It must keep running.
- **The sealed holdout stays sealed.** No rescoring, no peeking, no "just one diagnostic" read.
- **API keys are trade-only, withdrawals disabled.** Agents never place orders and never read API keys.
- **The live switch is the owner's**, via `cryptobot owner` — and nothing else.
- **Gate is NO-GO.** Absent proof, it stays NO-GO; no manual override, no threshold edits.
- **Keep this file committed** after every milestone.
- **Binance cannot be reached from Reason Cloud.** `api.binance.com/api/v3/ping` returns HTTP 451 and
  `fapi.binance.com/fapi/v1/premiumIndex` returns "Service unavailable from a restricted location
  according to 'b. Eligibility'"; direct socket DNS fails too. So **no live API call, order or
  market-data session runs on Reason Cloud** — anything touching the exchange runs on the owner's Mac.
- **The public archive *is* reachable from cloud:** `https://data.binance.vision/` returns HTTP 200
  and a ranged klines zip fetch returns 206. Historical backfill for research comes from those static
  zips, never from the REST API.
- **Never run full test suites on the owner's Mac** — one `pytest tests/unit` run wrote 1.2–2.1 GB of
  scratch and nearly filled the disk. Test in CI.

## Environment notes that still bite

- `ruff check src tests` is the CI lint scope (ruff 0.17.1, blocking). `tools/` is not linted by CI.
- CI installs `uv sync --locked --extra dev` and calls `.venv/bin/pytest`; `uv run pytest` fails
  (`Failed to spawn: pytest`). CI pins Python 3.12; a bare `uv sync` on 3.15 cannot build `nautilus-trader`.
- The recorder runs from the separate edge tree (`~/Code/cryto-bot-edge`, `PYTHONPATH` pointed at it)
  with the main checkout's venv python. Do not `uv sync`, `pip`, or rebuild that venv while it runs.
- Mutations are the test of a test: for every guard, delete it and confirm a named test fails.
