# RESUME — crypto-bot state

Snapshot: **2026-10-25 10:10Z**, base `origin/live/hardening` @ `8961364` (#46).
`origin/release/v1` (the tree the recorder actually runs) is **`ef744a2`** — #44 + #45 merged there —
and it is now **deployed in the edge tree with exactly one controlled restart done**: the recorder
stream fix is **live**. The 10:00Z line this replaces ("no restart has been performed") was true when
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
is not on the release branch** — #37 merged into a stale stacked branch, so D1 has no executable path
and the D1 owner is re-landing it (§3). That is a deployment gap, not a result.

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
| #39 | docs(resume): this file's refresh (stale PR rows) | `fe3ce0e` | squash `fcad78f` = **current base** |

All thirteen merged with `lint` + `typecheck` + `test` green. `research/prereg/D1-amendment-3.md` is on
the base and is the **sole source** for `N_TRIALS` (§5). **#36 supersedes #33's alert granularity**: it
now alerts per silent *stream*, not per silent *symbol*.

## 3. In progress — nothing is open, except the D1 evaluator gap

Read from GitHub at 2026-10-25 10:10Z: **no pull request is open** — #30 through #39 are all merged. Do
not trust an older note for a head SHA.

**The one open piece of work is the D1 evaluator, and it is not on the release branch.** #37
("research(d1): single-command forward evaluator that reads the frozen prereg") merged with its base set
to **`reason/r2-family-d-prereg-oi-fl-134e1b4c`, a stale stacked branch**, not to `live/hardening`.
Verified with git against `live/hardening` @ `fcad78f0`:

- `src/cryptobot/research/d1_eval.py` — **absent**
- `src/cryptobot/research/d1_trials.py` — **absent**
- `tests/unit/test_d1_eval.py` — **absent**
- #37's head `6f4ea0a` is **not an ancestor** of the base.

So the evaluator is **not deployed**. D1 status: **prereg text merged (#29), evaluator being re-landed on
`live/hardening` by the D1 evaluator's owner, `N_TRIALS` still unset.** Nothing here changes a gate
verdict, a prereg threshold, a holdout file or CI; when it does land it must keep the fail-closed rule
below (refuse a DSR verdict while `N_TRIALS` is unset).

## 4. Next steps, in priority order

1. **The recorder deploy is done (§8); the open gap is liquidations.** Trade flow, depth and the REST
   mark price are recorded; `forceOrder` still delivers nothing, so **there is no liquidation history
   at all**. Decide whether to record it another way or accept it — that is a scope decision to
   record in this file, not an agent's quiet fix.
2. **Prune finished session workspaces** before the disk drives the recorder into its 4,096 MB floor.
   Each Reason child session leaves ~1.2 GB under `~/.reason/workspace/sessions/`; there were six at
   08:11Z (≈7.2 GB) and guard's free-space samples swung 12,632 → 9,906 MB inside ten minutes. Never
   delete the folder of a session with a turn running.
3. **Re-land the D1 evaluator on `live/hardening`.** #37 went to a stale stacked branch, so
   `d1_eval.py`, `d1_trials.py` and `test_d1_eval.py` are not on the base (§3). That is the only open
   code work; it must keep the fail-closed rule — no DSR verdict, and no D1 PASS, while `N_TRIALS` is
   unset.
4. **Deploy verification is complete for the stream fix — do not redo it as if it were pending.**
   Closed chunk `rec-000449-20261025T095957Z` holds **559 `trade_agg`**, so the deploy took. The
   per-stream silent alert (#36) was **not** exercised on the live deploy; that one part of the check
   is still outstanding. Chunks sealed before the deploy keep their gap — that is history, not a
   regression.
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

### D1 evaluator: merged to the wrong branch

#37's evaluator files are not on `live/hardening` (§3). Until its owner re-lands them there, D1 has no
executable path at all — that is a *deployment* gap, not an evaluation result, and it must not be read as
evidence for or against D1. The one command that exists is `tools/forward_b4b.py` for B4b (#38); do not
point it at D1's prereg.

**So, the rule to follow.** `N_TRIALS` remains `None`. **Do not compute or emit a DSR verdict, and do
not allow a D1 PASS while it is unset.** The evaluator must fail closed when the constant is unset —
refusing is correct behaviour, not a bug to work around.

### Gate: NO-GO

| Study | Verdict | The number |
|---|---|---|
| B4 delta-neutral basis (backtest) | **KILLED on turnover** | turnover **17.05** (`17.05060731836767`, `research/autopilot_b/state/B4.json`) against the frozen cap **12** (`research/prereg/B4-delta-neutral-basis.md`: "turnover ≤ 12×. Any miss KILLS B4"). Holdout burned; nothing rescored. |
| B4b forward basis | **UNDERPOWERED** | **0 of 90** forward days, **0 of 20** round trips (`research/prereg/B4b-forward-basis.md` requires both). Forward clock starts 2026-11-01. |
| C2 XSMOM replication | **KILLED on replication** | replication **p = 0.080** against the bar **p ≤ 0.01** (holdout p = 0.154). `research/DATA_LEDGER.md`, `RESEARCH_VERDICTS.md`. Family C closed. |
| D1 open-interest flush | **UNEVALUATED** | Prereg + amendment 3 merged (#29); **evaluator not on the release branch** (#37 landed on a stale stacked branch, §3). `N_TRIALS` unset, so DSR cannot be emitted. |

B4b costs, unchanged: 49 bps round trip plus `0.5·σ·√(Q/ADV20)` impact per fill.
**A 90-day look can only KILL**: the ≥2-positive-calendar-years gate needs 121 forward days, so
earliest possible PASS is 2027-03-01.

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
with rollback to `6ad62b4`. **No restart has been performed.**

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
