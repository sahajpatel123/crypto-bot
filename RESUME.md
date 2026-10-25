# RESUME — crypto-bot state

Snapshot: **2026-10-25 09:05Z**, base `origin/live/hardening` @ `8471a83e` (PR #34, this file; #33 and #29
underneath it).
Gate: **NO-GO**, unchanged. Holdout sealed. No orders, no API-key reads, no live money.
Read this file, then `git log --oneline -5 origin/live/hardening`, then the PR list. That is the whole
handover — do not re-derive anything below.

## 1. Current state

The system is in **NO-GO** and no strategy has passed: Family B is closed (B1–B7 killed on frozen
gates), Family C is closed (C2 killed on replication), D1 is unevaluated for lack of forward data, and
the only live experiment is the C2-FWD forward recorder booking its first rows. Four things changed
this milestone. **DSR is formally unevaluable and the gate now fails closed**: `N_TRIALS` stays
`None`, no finite upper bound can be proven, and the evaluator must refuse to emit a DSR verdict while
it is unset — so D1 cannot PASS (§5). The **recorder stream gap** was found and fixed in code: for the
whole 18–25 Oct run the recorder silently discarded three of its five subscribed streams, and #33 is
merged on `live/hardening` — but **the running recorder does not execute that tree**, so the fix is
not live until the owner deploys it (§8). **Binance is not geo-blocked from the Mac** — Reliance Jio's
DNS sinkholes it, and the opt-in DoH fallback for that is merged as #26. The recorder is running on
the owner's Mac (one pid, heartbeat fresh) and is the single point of failure for every forward
verdict; nothing that touches the exchange can run on Reason Cloud (§6).

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

All seven merged with `lint` + `typecheck` + `test` green. `research/prereg/D1-amendment-3.md` is on the
base and is the **sole source** for `N_TRIALS` (§5).

## 3. In progress — open PRs, by owner

Read from GitHub at 2026-10-25 08:20Z. Do not trust an older note for a head SHA.

| PR | Owner / topic | Head SHA | Checks I read |
|---|---|---|---|
| #32 | **E1** emulator recovery fault matrix | `dc41e54` | draft; `lint` + `typecheck` success, `test` in progress (earlier heads `f785df4` and `aa7e287`; both re-pushed). |
| #31 | **Gate audit (G1)** — audit gate statistics on synthetic data | `0de94ea` | draft; `lint` + `typecheck` + `test` all success, clean. G1 still running. |
| #30 | **C2-FWD** audit of booking and scoring integrity | `376aa13` | draft; all six checks success, clean — ready to mark ready for review. |
| #34 | **This file** — RESUME milestone snapshot | see PR | docs only. |

None of these is a gate verdict, and none changes a prereg threshold, a holdout file or CI.

## 4. Next steps, in priority order

1. **Deploy the recorder fix — it is an owner decision, not an agent's.** #33 is merged on
   `live/hardening`, but the running recorder executes the separate edge tree at `release/v1`
   `6ad62b4`, so **a restart alone changes nothing** (§8). Do not update the edge tree yourself.
2. **Prune finished session workspaces** before the disk drives the recorder into its 4,096 MB floor.
   Each Reason child session leaves ~1.2 GB under `~/.reason/workspace/sessions/`; there were six at
   08:11Z (≈7.2 GB) and guard's free-space samples swung 12,632 → 9,906 MB inside ten minutes. Never
   delete the folder of a session with a turn running.
3. **#32 E1.** Let the re-pushed `test` finish; if red, read the job log and fix it. Draft until green.
4. **#31, then #30.** #31 audits the gate statistics themselves, so it should land before any
   evaluator change touches DSR. Mark ready if the conclusions hold.
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

**So, the rule to follow.** `N_TRIALS` remains `None`. **Do not compute or emit a DSR verdict, and do
not allow a D1 PASS while it is unset.** The evaluator must fail closed when the constant is unset —
refusing is correct behaviour, not a bug to work around.

### Gate: NO-GO

| Study | Verdict | The number |
|---|---|---|
| B4 delta-neutral basis (backtest) | **KILLED on turnover** | turnover **17.05** (`17.05060731836767`, `research/autopilot_b/state/B4.json`) against the frozen cap **12** (`research/prereg/B4-delta-neutral-basis.md`: "turnover ≤ 12×. Any miss KILLS B4"). Holdout burned; nothing rescored. |
| B4b forward basis | **UNDERPOWERED** | **0 of 90** forward days, **0 of 20** round trips (`research/prereg/B4b-forward-basis.md` requires both). Forward clock starts 2026-11-01. |
| C2 XSMOM replication | **KILLED on replication** | replication **p = 0.080** against the bar **p ≤ 0.01** (holdout p = 0.154). `research/DATA_LEDGER.md`, `RESEARCH_VERDICTS.md`. Family C closed. |
| D1 open-interest flush | **UNEVALUATED** | Prereg + amendment 3 merged (#29). Pending forward data, and `N_TRIALS` is unset, so DSR cannot be emitted. |

B4b costs, unchanged: 49 bps round trip plus `0.5·σ·√(Q/ADV20)` impact per fill.
**A 90-day look can only KILL**: the ≥2-positive-calendar-years gate needs 121 forward days, so
earliest possible PASS is 2027-03-01.

### Recorder (owner's Mac, read-only; `guard.log` 2026-10-25T07:42:05Z and my re-read at 08:11Z)

- Exactly **one** recorder: pid **91414**, launchd `com.cryptobot.recorder`, `caffeinate` wrapper pid
  91416. `--symbols BTCUSDT,ETHUSDT --chunk-seconds 300 --disk-budget-mb 4096`.
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

- Tree `~/Code/cryto-bot-edge`, branch **`release/v1`, HEAD `6ad62b4` (2026-10-20)**.
- `WorkingDirectory = ~/Code/cryto-bot-edge`; `PYTHONPATH = ~/.cryptobot/netshim:~/Code/cryto-bot-edge/src`;
  `CRYPTOBOT_DOH=1`.
- `KeepAlive{SuccessfulExit:false}`, `ThrottleInterval 30`, so a clean stop does not restart into
  empty chunks.

So **#33 being merged on `live/hardening` changes no recorder behaviour**, and **restarting the
recorder is a no-op** until the edge tree carries the change. Landing the fix there and updating
`edge/src` is an **owner decision**; record it, do not do it. Only one controlled restart follows it,
with rollback to `6ad62b4`. **No restart has been performed.**

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
