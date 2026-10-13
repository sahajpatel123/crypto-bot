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

- W1–W4 READY branches: none on origin yet → substantive reviews owed.
- Final adversarial challenge + PASS/VETO on the integrated SHA.
- Final `coord/outbox/W5-READY.json`.

Repro: from the base tag worktree (the cdcd10c probe script is tracked
there since `db58f3b`, no copy needed):
`tools/run_budget.py --budget-s 300 --checkpoint-dir ... --report-out
... -- env PYTHONPATH=src <venv>/bin/python
/Users/sahajpatel/Code/cryto-bot/Crypto_Bot_CORR_Independent_Probes.py`
