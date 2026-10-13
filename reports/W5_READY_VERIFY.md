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

- W1/W3 READY: not yet integrated → substantive reviews owed.
- Final adversarial challenge + PASS/VETO on the integrated SHA.
- Final `coord/outbox/W5-READY.json`.

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
