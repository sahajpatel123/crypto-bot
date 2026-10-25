# RESUME — crypto-bot state

Snapshot: **2026-10-25 11:00Z**, base `origin/live/hardening` @ `59a34c0` (#52).
`origin/release/v1` (the tree the recorder actually runs) is **`ef744a2`** — #44 + #45 merged there —
and it is now **deployed in the edge tree with exactly one controlled restart done**: the recorder
stream fix is **live**. The 10:00Z header this replaces ("no restart has been performed") was true when
it was written; §8 carries both, and §5 carries the post-restart chunk counts.
Gate: **NO-GO**, unchanged. Holdout sealed. No orders, no API-key reads, no live money.
Read this file, then `git log --oneline -5 origin/live/hardening`, then the PR list. That is the whole
handover — do not re-derive anything below.

## 1. Current state

The system is in **NO-GO** and no strategy has passed: Family B is closed (B1–B7 killed on frozen
gates), Family C is closed (C2 killed on replication), D1 is unevaluated for lack of forward data, and
the only live experiment is the C2-FWD forward recorder booking its first rows. Five things changed
this milestone. **DSR is formally unevaluable and the gate now fails closed**: `N_TRIALS` stays
`None`, no finite upper bound can be proven, and the evaluator must refuse to emit a DSR verdict while
it is unset — so D1 cannot PASS (§5). The **recorder stream gap** was found, fixed in code, and is now
**live**: for the whole 18–25 Oct run the recorder silently discarded three of its five subscribed
streams; `release/v1` `ef744a2` was deployed to the edge tree and the recorder restarted **exactly
once** (§8), and the first closed chunk after it holds **559 `trade_agg`** in five minutes (§5).
Liquidations are still **not** recorded — `forceOrder` never delivers — and that stays an open gap,
not a fix (§5). **Binance is not geo-blocked from the Mac** — Reliance Jio's
DNS sinkholes it, and the opt-in DoH fallback for that is merged as #26. The recorder is running on
the owner's Mac (one pid, heartbeat fresh) and is the single point of failure for every forward
verdict; nothing that touches the exchange can run on Reason Cloud (§6). The fifth: **D1's evaluator
is now on the release branch** — #43 re-landed it against `live/hardening` and merged as `6d76902`,
so D1 has one executable command (`research d1-eval`). It still cannot PASS: `N_TRIALS` is unset,
so no DSR is emitted (§3, §5). Landing the evaluator changed no verdict. After it, **#50 closed the
last argument path into the DSR gate**: a caller can no longer hand the gate a trial count of its own
choosing, at the library level or from a shell (§5).

**This file was refreshed against `4b57100`, and it corrects three things the previous version got
wrong at that commit.** It quoted the D1 file hashes #43 landed as if they were the branch's (a later
commit, #50, rewrote all three); it said every merged row had a green `test` job when #42's landed run
is red; and its snapshot base was `6d76902`, three merges behind. §2, §3 and §5 carry the corrected
values and name the commit each was read at.

## 2. Done and merged into `live/hardening`

Read from GitHub while writing this file, not from notes.

| PR | Title | Head SHA | Landed |
|---|---|---|---|
| #23 | B4b forward test + two statistics repairs | `64d5989` | merge `9dc49f9` |
| #27 | docs(research): record Family B diagnostic archive touch | `3c111fa` | squash `8f0f106` |
| #28 | tests: stop pytest scratch filling laptop disks | `3461180` | squash `fc92c45` |
| #26 | feat(net): netguard — opt-in DoH fallback for the ISP DNS sinkhole | `4c9a992` | squash `a635315` |
| #35 | docs: refresh RESUME after netguard merge | `065375e` | squash `d950d78` |
| #33 | fix(recorder): record trade flow, fail loudly on a silent stream | `5b1688d` | squash `a2acaba` |
| #29 | research(prereg): D1 OI-flush reversal + amendment 3 (fail-closed trial bound) | `4e7d37b` | squash `315bdc0a` |
| #36 | fix(recorder): alert per silent stream, not per silent symbol | `94cb1c6` | squash `6e39cba` |
| #30 | research: audit C2-FWD booking and scoring integrity | `376aa13` | squash `2ac3b23` |
| #31 | [G1] audit gate statistics on synthetic data | `cc6c1bf` | squash `7582fce` |
| #32 | fix(e1): complete emulator rehearsal and safety rails | `dc41e54` | squash `856c0b9` |
| #38 | B4b: make the frozen forward verdict executable as one command | `a0acd92` | squash `5eed674` |
| #39 | docs(resume): this file's refresh (stale PR rows) | `fe3ce0e` | squash `fcad78f` |
| #43 | research(d1): forward evaluator with the frozen universe, cutoff and fail-closed DSR | `1bdf675` | squash `6d76902` |
| #46 | docs(resume): the recorder fix is now on release/v1 (#45), and needed #44 to run | `c3f900d` | squash `8961364` |
| #42 | fix(research): harden C2-FWD booking and scoring | `8585b25` | squash `6aad6b3` |
| #50 | research(d1): close the DSR trial-count argument path and test the funding clock | `75c25bf` | squash `544888d` |
| #51 | docs(resume): D1's evaluator is on the release branch, and blocked on two recorder inputs | `a25cf3c` | squash `4b57100` |

CI, re-read on each landed commit for this refresh — not carried from the previous version of this
file, and the `test` job is **not** green everywhere:

- **#43, run 239 on `6d76902` — green.** Unit **1976 passed, 3 skipped** (1339 s) and acceptance
  **180 passed**, against **1935 passed** in run 229 on the pre-merge base `2120a9f`: a delta of
  exactly **41**, the D1 suite's own size then, so the evaluator's tests ran in CI and passed.
- **#46, run 244 on `8961364` — green.**
- **#42, run 249 on `6aad6b3` — RED in acceptance.** `lint` and `typecheck` passed; the `test` job
  failed at `tests/acceptance/test_rel_integrated_challenge.py::test_rel_crash_boundaries_resume_complete`
  with `FileNotFoundError: .../crash/res/rep.json` — its *reference* bench subprocess exited without
  writing a report (`1 failed, 179 passed in 33.78s`). #42 touches only `tools/forward_c2.py`,
  `tests/unit/test_forward_c2*.py` and three markdown files, and that test passes at `4b57100` in this
  file's checkout (`1 passed in 8.78s`), so it reads as a runner/harness failure rather than a
  regression — but **do not treat `6aad6b3` as a green commit** and do not cite it as one.
- **#50 (run 254) and #51 (run 257)** were still running when this file was written; read their
  conclusion from GitHub rather than from here. Rows before #43 are inherited from the previous
  refresh and were not re-read.

After #50, the D1 unit file holds **44** tests, not 41 (`44 passed in 16.23s` at `4b57100`).

`research/prereg/D1-amendment-3.md` is on the base and is the **sole source** for `N_TRIALS` (§5).
**#36 supersedes #33's alert granularity**: it now alerts per silent *stream*, not per silent *symbol*.

## 3. In progress — evaluator landed; the open D1 item is #49

Read from GitHub while writing this file: **no D1 pull request is open**. #42 (C2-FWD booking/scoring
hardening) merged as `6aad6b3` and does not touch D1. The open D1 item is issue **#49** — the two
recorder inputs below. Do not trust an older note for a head SHA.

**The D1 evaluator is on the release branch.** #43 ("research(d1): forward evaluator with the frozen
universe, cutoff and fail-closed DSR") merged into `live/hardening` as squash **`6d76902`**, from head
`1bdf675`, and it went **straight onto `live/hardening`** — no stacked base this time. The three files
and their sha256, read with `sha256sum` **at the tip `4b57100`** while writing this file:

| Path | sha256 at `4b57100` |
|---|---|
| `src/cryptobot/research/d1_eval.py` | `65229675842bca6877fe858941ccdce981201dcc6fa9645cfb1a8fa6a2400dd1` |
| `src/cryptobot/research/d1_trials.py` | `c4ffeeedbc73062054bb8ba7f3ebac48fef1db7a50ef45673ed1f3d0d29dda72` |
| `tests/unit/test_d1_eval.py` | `90c1561de2a68eddd1bbc4806fac974ca7873c00f59c30a8e2aa1f65f0720160` |

**These are not the hashes #43 landed, and a hash is only meaningful with the commit it was read at.**
#43 landed `15bd4393…` / `974179bd…` / `46cb9e96…` at `6d76902`; #50 (`544888d`) then rewrote all
three files — the DSR guard in `d1_eval.py`, a comment recording the freeze obligation in
`d1_trials.py`, and three new tests. Quote the `4b57100` triple for the branch; quote the `6d76902`
triple only when describing what #43 landed.

`cryptobot research d1-eval` is the one command (in `src/cryptobot/cli.py`, beside #38's `forward b4b`),
taking `--recorder-root`, `--prereg-dir`, `--repo-root`, `--start`, `--end`, `--json-out` and an
audit-only `--no-verify-chunks`. There is **no flag for a trial count**, by design (§5): the grid and the
penalty cannot be re-parameterised from a shell.

**Why #43 exists: #37 was reviewed and rejected, and the second landing answers the review.** The
rejections were that the frozen universe rule was parsed and echoed but never applied; that a named
guard test and its mutation harness were missing; that the holdout refusal ran after the chunk was
decompressed; that entries the prereg forbids were booked; that funding eligibility was tested against
the bar/OI/funding minimum rather than the funding window; that Stage 0 was neither first nor per the
no-overlap rule; that `INSUFFICIENT_FORWARD_DATA` stood where the prereg says `UNDERPOWERED`; that DSR
was reachable through an `--n-trials` argument; and that no code hash was bound into the output.
Re-read in the merged source, not taken from that PR body:

- **The frozen universe is real code.** `monthly_rankings()` sums `quote_volume` over the previous full
  calendar month M-1, requires **every** day of it (`if any(day not in item.daily_quote_volume ...)`),
  ranks the top `universe_size`, and applies `universe_min_age_days` plus `universe_active_hhmm`
  (`active_hour, active_minute = rules.universe_active_hhmm`). A month with no whole M-1 takes no
  signals, and `universe_shortfall()` stops the run rather than scoring whatever symbols the recorder
  happens to carry.
- **Stage 0 runs before any trade** and counts only what the no-overlap rule can enter
  (`overlap_filtered()`); `eligible_cells == 0` yields **`UNDERPOWERED`**, the prereg's own word
  (`D1-oi-flush-reversal.md`: "if no cell reaches 300 events the verdict is `UNDERPOWERED`").
  `INSUFFICIENT_FORWARD_DATA` survives only for missing recorder coverage — a stream shortfall or a
  universe shortfall — and never for a data-complete short sample.
- **`code_sha256`** hashes `d1_eval.py` and `d1_trials.py` into every output document
  (`_code_hashes()`), so a verdict is bound to the code that produced it.
- **DSR fails closed.** `N_TRIALS: int | None = None` in `d1_trials.py`; `trial_count_ready()` returns a
  refusal naming the exact missing file when the constant is unset, when the amendment is missing, or
  when the constant is set but the amendment is not there.

**#50 closed the argument path #43 left open.** In the merged #43 code, `evaluate_cells(...)` honoured
a caller's `n_trials` whenever `trial_count_trusted=True` was passed, and `evaluate_forward(...)`
hard-coded that flag while forwarding its own `n_trials` argument — so a library caller could still
reach a DSR with `N=470`. Since #50 (`544888d`): the flag is gone, `evaluate_cells` raises `D1Error`
for any count that is not exactly `d1_trials.N_TRIALS`, `evaluate_forward` has **no** trial-count
parameter at all (passing one is a `TypeError`), and the count is resolved once inside it from
`trial_count_ready()`. There is still no CLI flag. The guard's residual limit is recorded at the
constant: it cannot distinguish "read the constant" from "typed the same integer", which is
unreachable while the constant is `None`, and whoever freezes the count must edit
`research/prereg/D1-amendment-3.md` and the constant in the same commit.

**What still stops D1 is two recorder inputs, not the evaluator.** `d1-eval` reads the recorder chain and
refuses by naming what is absent. Given the stream vocabulary the deployed recorder actually writes
(`trade`, `book_ticker`, `depth`, `open_interest`, `premium_index`, `depth_snapshot`, `header`), the
merged `stream_shortfalls()` returns exactly two — reproduced by calling it with those names while
writing this file:

- **`funding_settlements`** — no settled `fundingRate` record exists anywhere. The 60 s `premiumIndex`
  poll carries a *next-rate estimate*, and the evaluator refuses it as a proxy on purpose: D1 charges
  the rate actually paid at 00:00/08:00/16:00 UTC.
- **`universe_daily_klines`** — no `kline_1d` (`quote_volume`) record exists, so the frozen universe
  cannot be ranked **at all**. `monthly_rankings()` needs every day of M-1 for the candidate listing;
  with no daily klines no month ever qualifies, so waiting does not fix it.

The exact refusal text is in **#49**, which is the open D1 work. Until settled funding and the daily
klines are recorded, D1's forward clock **has not started**: a December 2026 signal month is not
reachable by leaving the recorder running. `N_TRIALS` unset remains the third, independent guard.

## 4. Next steps, in priority order

1. **The recorder deploy is done (§8); the open gap is liquidations.** Trade flow, depth and the REST
   mark price are recorded; `forceOrder` still delivers nothing, so **there is no liquidation history
   at all**. Decide whether to record it another way or accept it — that is a scope decision to
   record in this file, not an agent's quiet fix.
2. **Prune finished session workspaces** before the disk drives the recorder into its 4,096 MB floor.
   Each Reason child session leaves ~1.2 GB under `~/.reason/workspace/sessions/`; there were six at
   08:11Z (≈7.2 GB) and guard's free-space samples swung 12,632 → 9,906 MB inside ten minutes. Never
   delete the folder of a session with a turn running.
3. **D1's evaluator is merged — the D1 blocker is data, and it is #49.** #43 is on the base as `6d76902`
   (§3), but the recorder records neither a settled funding rate nor daily klines, so `d1-eval` refuses
   with those two shortfalls named (§3). Closing them means a recorder change on the tree launchd runs,
   plus a decision on how wide the daily-kline pull has to be — the universe rule needs the candidate
   listing, not the two subscribed symbols. `N_TRIALS` frozen by its owner remains the third guard. Keep
   the fail-closed rule — no DSR verdict and no D1 PASS while `N_TRIALS` is unset.
4. **After any recorder deploy, verify it actually took:** a newly sealed chunk must contain `trade_agg`
   records, and a deliberately silent stream must raise the per-stream alert (#36). Chunks sealed before
   the deploy keep their gap — that is history, not a regression. **That check is complete for the
   2026-10-25 stream-fix deploy** — closed chunk `rec-000449-20261025T095957Z` holds **559 `trade_agg`**,
   so the deploy took; the restart did not crash-loop. The per-stream silent alert (#36) was **not**
   exercised on the live deploy, so that one part of the check is still outstanding.
5. **C2-FWD.** Leave it running; scoring reads 365/730/1095 rows only, so nothing is readable yet.
   Never look at its P&L before then.
6. **Do not re-open Family B or C and do not rescore B4.** The holdout is spent.

## 5. Key numbers

### DSR is unevaluable — and the gate now fails closed

**Exact `N` cannot be established.** The H1–H6 DEV summaries and the B1–B7 aggregates carry no run
keys tying a config to its fold/split or confirmation run, and they do not establish whether the
H3-on-H2 and H6-on-H2/H3 filter applications ever ran. No H/B run-key manifest exists; the only one
found is `trials/x1-run-manifest.json`, which is **X1-specific** and says nothing about H/B or restart
completeness. `research/prereg/D1-amendment-3.md` (merged in #29) also flags an unresolved contradiction in
H6's text — its exact rules name H1/H3 and H2/H4, its grid paragraph says H2/H3 only. That is
recorded, not silently rewritten.

**The correction that matters.** `N >= 470` was a **lower** bound, and the DSR null `SR0` **rises**
with `N`. A low `N` made the gate **easier, not safer**: the registered gate was optimistic, not
conservative.

| `N` | DSR null `SR0` |
|---|---|
| 470 | 3.0339 |
| 1000 | 3.2551 |
| 1187 | 3.3036 |
| 1470 | 3.3631 |
| 5000 | 3.6877 |

`SR0 = √V · q(N)` with `q(N) = (1-g)Φ⁻¹(1-1/N) + gΦ⁻¹(1-1/(N·e))`, `g = 0.5772156649`; both
probabilities rise with `N`, so `q(N)` is increasing and a *proven* finite upper bound would be
conservative. I re-derived the table from `q(N)` while writing this file; it reproduces to 4 dp, and
`q(1187) = 3.3035583220` matches amendment 3's figure exactly.

**No `N_max` is adopted.** An earlier plan to build a provable upper bound from the declared grid
maxima was **withdrawn**, and nothing in this file should read as licensing it. Grid maxima give a
**documented design-opportunity subtotal**, not an upper bound, because preregistrations count voided
runs but cap no number of aborted or restarted scored attempts, and a missing execution log is not
evidence an attempt did not happen. The reproducible subtotal is:

`H 937 + B 236 + amendment-1 non-H/B 230 + 3 C2-VM looks = 1406`

Amendment 3 states plainly that **1406 is not an `N_max` and must not be used by the evaluator**. It
also **rejects `N = 1187`**: the arithmetic was confirmed, but 1187 is not a provable upper bound.
Neither number is the penalty.

### D1 evaluator: merged and executable, and still unable to emit a verdict

#43's evaluator files are on `live/hardening` as `6d76902` (§3), so D1 has an executable path:
`cryptobot research d1-eval`. Merging it changed **no** verdict and is **not** evidence for or against
D1 — it is the instrument, not a reading from it. Three independent guards keep it silent: the two
recorder inputs it needs and does not have (`funding_settlements`, `universe_daily_klines` — #49); a
sample whose every cell is under the frozen event floor (`UNDERPOWERED`); and `N_TRIALS` unset, which by
itself makes any DSR verdict impossible.

**So, the rule to follow.** `N_TRIALS` remains `None`. **Do not compute or emit a DSR verdict, and do
not allow a D1 PASS while it is unset.** The evaluator fails closed when the constant is unset, and a
refusal is correct behaviour, not a bug to work around. The old `--n-trials` escape hatch is gone on
purpose: re-adding one, or reading a count out of the environment, would make the DSR bypassable again
and is the one change this section forbids outright.

### Gate: NO-GO

| Study | Verdict | The number |
|---|---|---|
| B4 delta-neutral basis (backtest) | **KILLED on turnover** | turnover **17.05** (`17.05060731836767`, `research/autopilot_b/state/B4.json`) against the frozen cap **12** (`research/prereg/B4-delta-neutral-basis.md`: "turnover ≤ 12×. Any miss KILLS B4"). Holdout burned; nothing rescored. |
| B4b forward basis | **UNDERPOWERED** | **0 of 90** forward days, **0 of 20** round trips (`research/prereg/B4b-forward-basis.md` requires both). Forward clock starts 2026-11-01. |
| C2 XSMOM replication | **KILLED on replication** | replication **p = 0.080** against the bar **p ≤ 0.01** (holdout p = 0.154). `research/DATA_LEDGER.md`, `RESEARCH_VERDICTS.md`. Family C closed. |
| D1 open-interest flush | **UNEVALUATED** | Prereg + amendment 3 merged (#29), evaluator merged (#43, `6d76902`, §3). Blocked on data, not code: the recorder carries neither a settled `fundingRate` nor `kline_1d` records, so the frozen universe cannot be ranked and funding cannot be charged (#49). `N_TRIALS` is also unset, so no DSR is emitted (§5). |

B4b costs, unchanged: 49 bps round trip plus `0.5·σ·√(Q/ADV20)` impact per fill.
**A 90-day look can only KILL**: the ≥2-positive-calendar-years gate needs 121 forward days, so
earliest possible PASS is 2027-03-01.

**PROGRAM CLOSED 2026-10-25 — `research/PROGRAM_CLOSEOUT.md`:** every gate is ruled either settled-negative (B4 on turnover, C2 on replication, C3/C4 and C1-TSMOM on DEV) or permanently undecidable in-program on the frozen archive (B4b by its own 2026-10-18..31 exclusion, C1-b4b carry's 90 forward days, C2-FWD's 365 recorded rows, D1 because `N_TRIALS` is `None`); no gate, threshold or number changed, and the holdout stays sealed.

### Recorder (owner's Mac, read-only; `guard.log` 2026-10-25T07:42:05Z and my re-read at 08:11Z)

- Exactly **one** recorder: pid **71989**, launchd `com.cryptobot.recorder`, `caffeinate` wrapper pid
  71991 (`91414`/`91416` before the 10:00Z deploy, §8). `--symbols BTCUSDT,ETHUSDT --chunk-seconds
  300 --disk-budget-mb 4096`.
- `heartbeat_age_s` **0.0156**, free **12,295 MB** against the **4,096 MB** floor, runway **166.7 h**.
- `c2fwd` days_behind **0**, **1** row booked; `stop_file` **false**; data volume **11.8 GiB** available.
- Re-read at 08:11Z: one pid, heartbeat advancing (chunk `rec-000426-20261025T080325Z`), free space
  **8,684–10,147 MB** — guard's own samples swing ~2.7 GB in ten minutes. Treat 166.7 h as a snapshot,
  re-read it, and never plan against it.

### The recorder stream gap (measured, not inferred)

For the whole 18–25 Oct run the recorder subscribed to five Binance streams and wrote only some.
Chunk `rec-000417-20261025T071824Z` holds **96,273** `book_ticker`, **5,874** `depth`, **10**
`open_interest`, **10** `premium_index`, **10** `depth_snapshot`, and **ZERO** `trade`, mark-price or
liquidation records; chunk `rec-000426-20261025T080325Z` repeats it (**93,495** bookTicker, **5,875**
depth, 10/10/10, zero trade). Both were counted from the sealed chunks while writing this file, and
the per-symbol splits reconcile exactly. Nothing about those chunks changes retroactively.

Cause: `aggTrade`, `markPrice@1s` and `forceOrder` complete the handshake and then **send zero bytes,
silently** — no close, no error, no timeout. Fix in **#33**: per-second `trade_agg` buckets instead of
raw prints (raw prints do not fit the 4 GB budget), a sealed chunk now raises a **stream-silent alert
naming any subscribed stream that produced no record**, and mark price continues from the 60 s REST
`premiumIndex` poll. **Nothing was a disk-budget or priority cut** — do not "fix" it by raising the
budget.

**UPDATE 2026-10-25 10:10Z — the gap is closed for trade prints, and the deploy is measured, not
assumed.** Chunk `rec-000448-20261025T095326Z` is the last complete chunk before the restart and holds
only `book_ticker`, `depth`, `premium_index`, `open_interest`, `depth_snapshot` and `header` — no
trades, no mark, no liquidation, exactly as above. The first closed chunk after the restart,
`rec-000449-20261025T095957Z`, holds **143,027 `book_ticker`**, **5,855 `depth`**, **559 `trade_agg`**,
**10 `premium_index`**, **10 `open_interest`**, **10 `depth_snapshot`**, **1 `header`** and **0
`liquidation`**. Those types were re-counted from the sealed `.gz` while writing this file and match to
the record.

**The honest limit — do not read this as more than it says.** `BINANCE_SILENT_STREAMS` (`aggTrade`,
`markPrice@1s`, `forceOrder`) handshake and then send **zero bytes**, so the recorder records no
mark-price and no liquidation *stream*. Mark price comes from the 60 s REST `premiumIndex` poll and
rides inside the `premium_index` records as `payload.markPrice`. **There is therefore still no recorded
liquidation (`forceOrder`) history anywhere** — a known open gap, not something this deploy fixed.
Trade prints are the only stream that closed.

## 6. Standing safety rules

- **Never start a second recorder.** Check first:
  `ps -axo pid,command | grep 'cryptobot.cli recorder' | grep -v grep` and
  `~/Code/cryto-bot-edge/data/recorder/recorder.pid`. It must keep running.
- **The sealed holdout stays sealed.** No rescoring, no peeking, no "just one diagnostic" read.
- **API keys are trade-only, withdrawals disabled.** Agents never place orders and never read API keys.
- **The live switch is the owner's**, via `cryptobot owner` — and nothing else.
- **Gate is NO-GO.** Absent proof it stays NO-GO: no manual override, no threshold edits, and no DSR
  number invented to fill the gap.
- **Keep this file committed** after every milestone.
- **Binance cannot be reached from Reason Cloud.** `api.binance.com/api/v3/ping` returns HTTP 451 and
  `fapi.binance.com/fapi/v1/premiumIndex` returns "Service unavailable from a restricted location
  according to 'b. Eligibility'"; direct socket DNS fails too. So **no live API call, order or
  market-data session runs on Reason Cloud** — anything touching the exchange runs on the owner's Mac.
- **The public archive *is* reachable from cloud:** `https://data.binance.vision/` returns HTTP 200
  and a ranged klines zip fetch returns 206. Research backfill uses those static zips, never the API.
- **Never run full test suites on the owner's Mac.** One `pytest tests/unit` run wrote 1.2–2.1 GB of
  scratch in ~25 minutes and dropped free space from 9.4 to 3.7 GiB. Test in CI.

## 7. Network: not geo-blocked on the Mac; Jio DNS sinkholes it

Verified 2026-10-25 in Ahmedabad: Reliance Jio's resolver answers `*.binance.com` and `*.okx.com` with
`49.44.79.236`, a dead host. Real addresses via DoH (`1.1.1.1` / `8.8.8.8`) work — fapi REST 200,
fstream websocket upgrade 101, demo-fapi 200 — and SNI/certificate checks are unaffected. Earlier
claims that Binance futures needed a VPN were wrong. `data.binance.vision`,
`testnet.binancefuture.com` and `api.bybit.com` are not sinkholed; the Cloud HTTP 451 is a separate geo
restriction, not this one.

The fix is opt-in `CRYPTOBOT_DOH=1`, only on a network where `cryptobot host-check` proves sinkholing;
it is off by default. The CLI and exchange-facing tools install `src/cryptobot/netguard.py`;
`tools/netshim/sitecustomize.py` is standalone for processes that cannot import `cryptobot`. See
`tools/netshim/README.md`.

## 8. Deployment reality: the running recorder is not `live/hardening`

**This is the trap that will waste a session if it is not read.** The launchd job executes the
separate edge tree, not this repo:

- Tree `~/Code/cryto-bot-edge`, branch **`release/v1`, HEAD `ef744a2`** — `6ad62b4` until the 10:10Z
deploy recorded at the end of this section.
- `WorkingDirectory = ~/Code/cryto-bot-edge`; `PYTHONPATH = ~/.cryptobot/netshim:~/Code/cryto-bot-edge/src`;
  `CRYPTOBOT_DOH=1`.
- `KeepAlive{SuccessfulExit:false}`, `ThrottleInterval 30`, so a clean stop does not restart into
  empty chunks.

So **#33 being merged on `live/hardening` changes no recorder behaviour**, and **restarting the
recorder is a no-op** until the edge tree carries the change. Landing the fix there and updating
`edge/src` is an **owner decision**; record it, do not do it. Only one controlled restart follows it,
with rollback to `6ad62b4`. **No restart had been performed when this paragraph was written** — the
2026-10-25 10:10Z update at the end of this section records the deploy that did it.

**UPDATE 2026-10-25 10:00Z — the fix is now on `release/v1`, and the edge tree still is not.** Two
pull requests were opened against `release/v1` (not `live/hardening`, and `release/v1` was **not**
fast-forwarded to `live/hardening`) and both merged:

- **#45** (`ef744a2`) cherry-picks **#33 `a2acaba`** and **#36 `6e39cba`** onto `release/v1` —
  `trade_aggregate_s`, `BINANCE_SILENT_STREAMS`, `_silent_streams`, per-second trade buckets, and
  `tests/unit/test_recorder_streams.py`. 571 insertions / 6 deletions / 3 files; `DECISIONS.md`
  resolved by union (+199, 0 removed). The default stream set becomes `trade, bookTicker,
  depth@100ms`; `aggTrade, markPrice@1s, forceOrder` are the names that handshake and then never
  deliver. One extra commit renames a loop variable that would otherwise raise ruff `F402` on
  `release/v1` only (that base still imports the unused `dataclasses.field`).
- **#44** (`4f19a45`) exists because **`ba5d555` made `release/v1` unrunnable**: the merge of
  `live/hardening` into it left a duplicated block in `app/session.py` that is a hard `SyntaxError`,
  plus nine `timezone.utc` uses whose import the same merge replaced with `UTC`. So `python -m
  cryptobot.cli` — the command launchd runs — could not be imported at all from `ba5d555`, and a
  restart would have crash-looped. #44 restores the block `6ad62b4` ships (keeping its
  `if not self._exit_only_reasons:` guard rather than `live/hardening`'s flattened form) and rewrites
  the nine call sites to `UTC`. Acceptance went 17 failed → 180 passed.

Verified at `origin/release/v1` `ef744a2`, in a clean worktree: `import cryptobot.cli` and
`import cryptobot.market_data.live_recorder` succeed, `trade_aggregate_s` is present,
`tests/unit/test_recorder_streams.py` is **14/14 green** (also 14/14 under a clean Python 3.12.13
env), and `ruff --select F821 src` is clean. The edge tree itself is **untouched at `6ad62b4`,
clean, with the recorder process still running untouched**, so the deploy remains exactly one owner action:
update `~/Code/cryto-bot-edge` to `ef744a2` (or later) and do the one controlled restart, rollback
`6ad62b4`.

`release/v1` CI does not go green from this: its `lint` job is already red at base (132 errors,
identical before and after) and ~230 pre-existing unit failures in the merged `live/hardening` code
become visible once `app/session.py` imports again. Neither is caused by #44/#45; both are recorded
here rather than left to be rediscovered.

`com.cryptobot.guard` runs every 5 minutes: it restarts only when no recorder is running, no STOP file
exists and free space is above its threshold; it prunes pytest scratch older than 6 hours only when
pytest is not running; it alerts on low runway, stale heartbeat, duplicate recorder or a C2-FWD ledger
2+ days behind. It never touches chunks, the manifest or ledgers.

The recorder measured ~1.5 GB per UTC day and **self-caps at 4096 MB** (2.2 GB used at 07:05Z, 400
sealed chunks, 0 gaps in the last three, one harmless unsealed `rec-000396-20261025T051309Z` not in
the manifest; ingress verified 05:33Z at 50,400 records in 33 s). Its own budget is not the risk — the
machine's free space is, which is what the 4,096 MB floor protects.

C2-FWD runs from `~/Code/cryto-bot-fwd` at `9dc49f9` with `CRYPTOBOT_DOH=1`, launched by
`com.cryptobot.c2fwd` four times daily (05:50/11:50/17:50/23:50 IST). Ledger
`data/forward_c2/ledger.jsonl`; first row booked 2026-10-25T05:43Z for day 2026-10-24 (universe 30, 12
positions). Preregistered scoring runs once at 365/730/1095 rows (first ≈2027-10-24); no P&L is read
before then.

**UPDATE 2026-10-25 10:10Z — the deploy is done: `ef744a2` in the edge tree, one controlled restart,
one recorder throughout.** The edge tree at `~/Code/cryto-bot-edge` was fast-forwarded `6ad62b4` →
**`ef744a2`** (clean, no rollback needed), then the recorder was restarted **exactly once**:

```
launchctl kickstart -k gui/<uid>/com.cryptobot.recorder
```

pids **91414 / 91416 → 71989 / 71991**. There was one recorder at every point of the change and never a
second instance, and the first closed chunk after it, `rec-000449-20261025T095957Z`, carries trade flow
(§5) — so the restart landed a working recorder rather than a crash loop.

**Why #44 was load-bearing, restated because it is the trap.** `release/v1` tip `ba5d555` carried a
duplicated block in `src/cryptobot/app/session.py` that is a hard `SyntaxError`, so `python -m
cryptobot.cli` — the command launchd runs — could not import at all. A restart before #44 would have
crash-looped the recorder instead of recording. #44 is what made this single restart safe.

**Known red, unchanged by this deploy — do not read it as a regression.** `release/v1` CI is red at its
base: `lint` carries **132 pre-existing errors in test files**, and the **test job cannot run at all**
because `uv.lock` fails to parse (TOML error around line 779: `version = "0.17.2"` inside an array), so
the job falls through to `.venv/bin/pytest`, which does not exist — **exit 127**. The recorder change's
tests were therefore **validated locally, not by that branch's CI**; that is a verification limit, and
`uv.lock` stays out of scope for this docs milestone.

## 9. Environment notes that still bite

- `ruff check src tests` is the CI lint scope (ruff 0.17.1, blocking). `tools/` is outside CI's lint
  scope; the standalone netshim is checked separately.
- CI installs `uv sync --locked --extra dev` then calls `.venv/bin/pytest`; `uv run pytest` fails
  (`Failed to spawn: pytest`). CI uses Python 3.12 and the repo supports 3.12–3.14; a bare sync on 3.15
  cannot build `nautilus-trader`.
- Test-job baseline on this repo: **12.1 min typical, 22.2 min worst observed** (run 40169206876). Use
  that before calling a test job hung; logs are not published mid-step.
- Do not `uv sync`, `pip` or rebuild the main checkout's venv while the recorder runs — it executes
  with that venv's python.
- Mutations are the test of a test: for every guard, delete it and confirm a named test fails.
