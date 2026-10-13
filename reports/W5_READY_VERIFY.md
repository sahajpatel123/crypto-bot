# W5 READY-VERIFY — interim evidence (base tag probes)

Worker 5 (`crystal-parallax`), branch `worker5/ready-verify`.
Base: tag `review-0d40ad3-baseline` = `0d40ad3b671741baad7b0ced3738b8b1549e5962`.
Machine: Darwin arm64, project venv python 3.14.6, nautilus 1.231.0.
Raw JSON: `reports/w5ready-base-probes.json` (probe rc 0, 6.591s;
budgeted 300s job).

## 1. Independent probes on base — all findings REPRODUCED

Earlier corrections hold: IOC `defect_observed=false` (fill @101 at
200ms); checkpoint 135 slots/warmed → 1 feed/warmed, orphan-flat False,
changed-config False, round-trip flat True; nested 1.207s rc 124
INCOMPLETE/verified.

Session lifecycle (matches reviewer exactly):

| Tape | rc/status | fills | forgotten live legs | expiry | protection checkpoints |
|---|---|---|---|---|---|
| existing restart tape | 0/COMPLETE | 2 | 6 | 1 | 3 unverified + 2040 emergency |
| same entry, no later crossings | 124/INCOMPLETE_EXPOSURE | 2 | 6 | 1 | 3 unverified + 2916 emergency |

Booked economics are identical on both tapes (flat cash) while the
order lifecycle is unsettled on the quiet tape — deterministic
recovery does not establish a correct lifecycle. Flatten observer
capped at 20 calls (both tapes hit the cap).

Scoring (matches reviewer exactly):

- partial_close: 0.005 remaining open yet reported 1 closed trade, n=1.
- funded_ist_day: booked net 0.74 correct, but daily net 0.94 (funding
  omitted) under UTC date 2026-10-11 instead of IST 2026-10-12; trade
  net 0.94 likewise omits funding.
- two_symbols_same_second: 2 symbol-seconds reported as 1 (clock-second
  collapse).

## 2. Bad-input behavior on base (W5 extras)

- `score_cell` / `analyze_run` on empty/missing/corrupt inputs:
  `FileNotFoundError` (loud; demands `rejections.jsonl` first). No
  silent valid-flat result observed on these shapes.
- `Session._ingest`: missing/unknown channel silently ignored (None);
  string `exchange_ts_ms` drops the event (no feed; gate unknown);
  negative prices rejected by the bid>0 guard (feed without mark; gate
  unknown). All fail closed downstream.
- `Session._ingest` with `payload: None`: unhandled `TypeError`
  (`'NoneType' object is not subscriptable`). No None-guard exists in
  `session.py`. Minor observation for the Session owner (W1):
  schema-validated upstream paths may never send it, but the crash is
  unhandled at this layer.

## 3. Notes

- The base-era aggregate script's freshness leg no longer runs
  (`_quote_age_gate()` requires a symbol — the permanent CORR tests
  cover the new API). This matches the plan §8 note about the obsolete
  reviewer command; no adaptation was needed for THIS probe script,
  which ran unmodified.
- Reviewer's Linux note (§1: five deadline tests failing incl. a
  daemon-survival marker) cannot be reproduced on this Mac (no Linux
  runtime here); W3 owns the intended-OS repro per the plan. Treated
  as an open platform question, not a macOS finding; no assertions
  touched.

## 4. Pending

(none — closing filed below.)

## 8. Closing — final adversarial challenge on `e33c95d`: PASS

Challenge worktree at `e33c95d` (W1+W2+W3+W4A+drill prep+acceptance
gates merged; read-only, removed after). Before/after evidence: base
`reports/w5ready-base-probes.json` vs after-run below. Every job under
`run_budget` (all ≤1500s work).

- Independent probes: every finding fixed. Session legs COMPLETE/
  COMPLETE rc 0, forgotten 0, expiry 0, `{verified:1}` each (was 6
  legs, 2040/2916 emergency, quiet INCOMPLETE_EXPOSURE). Scoring:
  partial {closed:0,n:0}, funded 0.74/IST, symsec S1:2. Earlier
  corrections hold (nested 1.198s verified).
- Gates: READY acceptance 5/5, restart-equivalence (incl. exposed
  interrupt parity), 23 lifecycle, 12 deadline battery, budget 5,
  CORR acceptance 10, drill 9 — 56 targeted + 9 drill, all green,
  zero strays.
- Crash test: SIGKILL −9 mid-run (dirty, no flush) → `--resume` →
  COMPLETE rc 0 with fills/booked/cursor parity (seq 6240).
- Bad inputs: null/NaN payload → loud reject counter; corrupt capture
  row counted, no error; missing scoring inputs fail loudly.
- Exchange boundary: prod flatten raises
  `config:prod-submission-disabled`; drill kill-on-miss green (creds,
  host, stale, unknowns, cap, protection, exit, no-trade).
- Full suite: 1162 passed, 1 skipped, 0 failed in 331s.

No defect found that warrants a veto. All observations across the
four worker reviews are non-blocking (async-attach churn fail-closed,
registry-test discrimination, span-class overlap under total silence,
PID-reuse residual). Linux subreaper runtime proof remains the one
open item needing a Linux host (W3's dual-root fix addresses the
reviewer's daemon marker by construction; macOS behavior proven).

Verdict: PASS on `e33c95d`.

## 7. Addendum — substantive W1 review (APPROVE)

Reviewed branch `origin/worker1/ready-lifecycle` (fix `1c1ec7f`,
outbox `f1764a0`, merged as `30f9175` with all four files identical)
in a read-only scratch worktree. Every job under `run_budget`.

- Independent probes: both tapes COMPLETE rc=0, forgotten 0, expiry 0,
  protection `{verified:1}` each, fills 0.332/0.332 both tapes,
  quiet exit @100.23 via time-exit — every claimed after-value exact.
- Full suite: 1130 passed, 1 skipped in 296.5s — claim verified
  exactly. Owned 23 lifecycle tests + replay file: 67 green.
- Code line-reviewed: venue-step snap + double recheck
  (approve→executable→recorded), first-fill exposure transition
  (exec-gated, tracked-only), protection need (net + unknown-only
  remainder, terminal retires), settle/prune with seen-set
  queue-drop-vs-amnesia distinguisher, full-agreement release,
  idempotent flatten (one reduce-only exact-net close, unknown counts
  in-flight, checkpoint-on-action), null-payload loud reject,
  executable narrowing unpersisted+popped (post-restart need falls back
  to approved = conservative over-cover).
- B8 adaptation is a strengthening (legs retained + retired-with-
  cancel, 3 new asserts, rationale comment). No test removed.
- W5 adversarial extras: null + NaN payloads → loud
  `event-malformed-payload` counter, no raise (my base note folded);
  in-bracket stop-fill sweep: entry+stop filled, target cancelled,
  ZERO live orders, queues empty, position released, ledger flat.
- Observations (not blocking): async-attach pairs churn through
  replace-to-emergency (fail-closed; paper path synchronous and
  proven); `seen_ids`/`cancel_requested` sets verified never
  serialized; post-restart `_executable` absence over-covers by design.
- Scope: session.py + policy.py + lifecycle tests only; engine files
  untouched (guarded reads only).

## 6. Addendum — substantive W3 review (APPROVE)

Reviewed branch `origin/worker3/ready-data` (`808b94b`) in a read-only
scratch worktree. No W3 outbox filed; reviewed from the diff directly.
Every job under `run_budget`.

### Deadline containment — APPROVE (fixes a real hole)

- Dual-root discovery (child + wrapper self) fixes a genuine gap in the
  CORR repair: with a subreaper, orphans reparent to the WRAPPER as
  siblings of the child, which the child-rooted walk missed — this is
  the likely mechanism behind the reviewer's Linux daemon-survival
  marker. Self excluded from results and signals; wrapper spawns
  nothing else, so the wider root is safe. macOS behavior unchanged.
- `/proc`-direct enumeration on Linux (paren-safe stat parse,
  self-presence health gate, mid-scan churn tolerated) with `ps`
  fallback; transient ps PID excluded from the registry (narrows a
  PID-reuse hazard); waitpid reaping of adopted kills before the
  survivor check (zombie false-survivor fix, portable no-op on macOS);
  `CRYPTOBOT_BREAK_ENUMERATION` test hook, default off, fail-closed by
  construction; additive `enum_source` report field.
- Battery changes are NOT a weakening: the two ps-hiding tests (vacuous
  on /proc Linux) gained Linux skipifs with correct rationale, and two
  hook-based platform-neutral tests assert the identical contracts on
  all platforms. No other battery test touched.
- Observation (test strength, pre-existing): neither the original
  flaky-ps test nor the hook port isolates the birth registry —
  single-level kills succeed via {child} alone. A nested variant would
  truly discriminate registry coverage.
- Residual (pre-existing design): PID-reuse hazard for short-lived
  descendants generally (manager-approved birth-registry identity);
  W3 narrowed the ps-transient instance only.
- Tests: 12 battery + 5 budget + 7 eligibility, 24 green, no strays.

### Gap taxonomy + eligible intervals — APPROVE

- `eligibility.py` reviewed line-level: seven classes implemented as
  documented; raw single-ID skips are volume caveats only; lone
  markers exclude nothing; no forward-fill; causal exchange times;
  mechanical/market clocks separated with labeled intersection.
- Crafted-capture probe: agg jump → `missing-trade-ids` span with exact
  absent-ID range; global silence → `transport-gap` seconds;
  cadence break → `stale-executable` span; marker noted without
  exclusion; bad row counted; market intervals exact
  ((0,100),(2100,3000),(6100,7000) with fail-closed bar cuts).
- Observations (not blocking): quiet seconds inside a jump window are
  attributed to the jump (jump dominates, fail-closed); total silence
  carries both `transport-gap` and `stale-executable` classes, so "one
  class per span" holds entry-level and on the real captures (zero
  transport gaps there) but not span-level under total silence —
  intervals unaffected either way; input assumed time-ordered (no
  sortedness assertion).
- Tool `eligible_intervals.py` re-ran correctly on the crafted capture;
  committed cap reports internally consistent (dense captures, zero
  ID breaks, 315 quiet seconds explained).

## 5. Addendum — substantive W2 + W4A reviews (APPROVE both)

Reviewed on main-tree integrations (manager serializes from worktrees;
no branches): W4A `624dc0a`, W2 `44387e4`. Verified in a read-only
scratch worktree at `44387e4` with `PYTHONPATH=src` pinned. Every job
under `run_budget`.

### W2 (scoring/funnel `624dc0a..44387e4`) — APPROVE

- Independent probes: all three scoring legs match W2's claimed after
  values exactly (partial {closed:0,n:0}; funded {0.74 booked/daily/
  trade, IST 2026-10-12}; symsec {S1:2}). Session legs unchanged
  (W1 territory, still broken as expected).
- Tests: owned+neighbors 87 passed (16+71, counts exact); full
  `tests/unit` 885 passed, 1 skipped in 361s — claim verified exactly.
  No test removed (2→8 scoring, 5→8 funnel); zero removed assertions.
- Code: episode linkage (open/partial/closed/orphan-exit, closed-only
  trades), equal-split funding over open-holders with day-level
  fallback, IST realized days + marked/realized split, missing-ledger
  None/False, (strategy,symbol,second) symbol-seconds with attribution
  + invalid-denominator labels, state-based watch (unreadable→unknown).
  All reviewed line-level; sound.
- Adversarial extras: orphan exit disclosed (`orphan_exit_episodes:1`
  + full list, closed 0, flat_valid False with reason) while cash
  proceeds stay in booked with reconciliation identity holding;
  pre-episode funding lands day-level with identity holding;
  missing-ledger full dir → booked None + flat False; funding-only day
  preserved with funding in daily. Consumer `score_phaseb.py` passes
  net through (null-safe).
- Scope clean: scoring.py + funnel.py + their tests only.

### W4 phase A (`442501c..624dc0a`) — APPROVE (phase A scope)

- 61 candidates (S1:16, S3:45, matching 12+45+4+0): required fields
  present, cost arithmetic exact (10+5+10+1=26bps, half-per-leg spread
  not double-booked), gap = reward−cost, all conservative-simulation
  labeled. Zero fills/P&L claims in the file.
- Export re-run byte-identical to W4's `/tmp` output (45/45 intents,
  3292/3292 rejects, identical validation + candidate payloads) and
  consistent with committed candidates.
- Hypothesis discipline: `trials/ready-01.json` frozen 17:48:56Z,
  export outputs written 17:51Z+ (filesystem mtimes) — freeze precedes
  numbers. H-R1/H-R2 + 7-config variant set + selection rule + locked-
  eval designation all frozen; H-R1 holds descriptively (0/61 within
  5bps); no threshold change, no economics run.
- Scope clean: new tool + outputs/reports/trials/coord only, no src.

Repro: from the base tag worktree (the cdcd10c probe script is tracked
there since `db58f3b`, no copy needed):
`tools/run_budget.py --budget-s 300 --checkpoint-dir ... --report-out
... -- env PYTHONPATH=src <venv>/bin/python
/Users/sahajpatel/Code/cryto-bot/Crypto_Bot_CORR_Independent_Probes.py`
