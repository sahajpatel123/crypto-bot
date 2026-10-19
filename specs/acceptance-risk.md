# Risk invariants + acceptance matrix (V-001, CONTRACTS v0.1.0)

Owner: Worker 3 (cool-amalthea). Implements the CONTRACTS.md "Risk gate
interface": `evaluate(intent, account_state) -> Approved(reserved_risk, size)
| Rejected(reason)`. All money in USDT; raw timestamps UTC; accounting day
Asia/Kolkata 00:00–24:00 (IST has no DST; fixed UTC+5:30 with zoneinfo
preferred, fixed-offset fallback — identical by construction).

Simulation defaults come from DECISIONS.md CEO section; nothing here is a
proven live setting. No live orders.

## Gate order (first failure wins, deterministic)

1. Health: `data_quality` HALT or DEGRADED → reject. Expired intent
   (`entry_expiry_utc < now`) → reject. Stale evidence
   (`now - evidence_ts_utc > max_evidence_age_s`) → reject.
2. Day rollover: a new accounting day starts `needs-reconciliation`; entries
   rejected until `reconcile_day(day_start_equity)` records the flow-adjusted
   starting marked equity ("next day needs reconciliation + healthy system").
3. Daily halt: halt flag set for today → reject. Trigger
   (`marked <= day_start * (1 - 0.01)`) engages the flag (persisted) → reject.
4. Daily target pause: `net_liq >= day_start * (1 + 0.02)` engages pause
   (persisted) → reject new entries; open exposure managed normally
   (evaluate() only gates entries, never exits).
5. Profit protection: once armed (global net realised gains >= 1% of original
   pilot equity), floor = `original + 0.70 * peak_gains`, upward-only,
   persisted across days/restarts. `marked <= floor` → reject.
6. One position: open position OR any live reservation → reject.
7. Sizing: planned-loss budget `0.25% * reconciled_equity` must cover stop
   loss plus stressed execution costs; notional `<= 3 * equity` (leverage /
   margin / exposure collapse to this one check under one-way, isolated,
   <=3x: required margin `notional/3 <= equity` is the same inequality);
   notional `< min_notional` → skip-reject (no reservation consumed).
8. Atomic reservation: Approved carries `reservation_id`; the reservation is
   persisted (tmp-file + atomic rename) before evaluate() returns.

`evaluate()` is synchronous and single-process atomic (DECISIONS: modular
single-process app). Cross-process locking is out of scope and recorded as
unresolved U-001.

## Invariants and acceptance

| ID | Invariant | Accept when | Fixture / test |
|---|---|---|---|
| R-001 | Per-trade planned loss (stop + stressed costs) <= 0.25% reconciled equity | approved notional exactly `budget/(stop_pct+stressed_pct)`; over-budget intent rejected | `risk_intents.json` canonical + `test_risk_sizing.py` |
| R-002 | Notional <= 3x equity (leverage/margin/exposure) | tiny-stop intent that implies >3x notional rejected with `leverage:*` | adversarial `tiny-stop` + sizing test |
| R-003 | Minimum-size skip consumes nothing | sub-minimum notional rejected `skip:min-notional`, no reservation left | `dust` intent + sizing test |
| R-004 | One open position globally, incl. reservations | second evaluate while reservation live rejected `exposure:one-position` | race test `test_risk_gates.py` |
| R-005 | Reservation atomicity + lifecycle | approve persists before return; release/fill/expire paths leave no orphans; restart reloads live set | crash/restart test `test_risk_halts.py` |
| R-006 | Daily 1% loss halt blocks rest of accounting day | trigger then approve-attempt rejected `halt:daily-loss` incl. after restart | `halt-day` fixtures + halts test |
| R-007 | Target pause at +2% net-liq blocks entries only | entries rejected `pause:daily-target`; exits unaffected (no exit gate exists) | target fixtures + halts test |
| R-008 | Profit protection upward-only + persistent | arm at +1% realised; floor ratchets up only; breach rejects; survives restart + day change | profit fixtures + `test_risk_profit.py` |
| R-009 | Health blocks: halt/degraded/expired/stale rejected with reason | each variant rejected with its `health:*`/`stale:*` reason | adversarial intents + gates test |
| R-010 | Ledger: flows partitioned, never profit; marked vs net-liq distinct | deposit moves equity, not P&L; close-cost projection separates the two | `risk_days.json` + `test_ledger.py` |
| R-011 | Accounting day = Asia/Kolkata; UTC raw | IST-midnight edge timestamps bucket correctly; day-start flow-adjusted | timezone fixtures + ledger test |
| R-012 | Determinism: same inputs → same decision; injected clock | repeated evaluates byte-identical; no wall-clock/randomness in policy | `test_determinism.py` |

Every invariant has a failing-then-passing fixture where runnable: acceptance
tests were written first and observed failing (missing modules) before the
policy existed, then pass after implementation.

## Repro (independent reproduction by another worker)

```sh
source .venv/bin/activate
pytest -q tests/acceptance
```

Expected: all acceptance tests pass on branch `worker3/v-001` merged over a
base containing CONTRACTS v0.1.0 + `src/cryptobot/coordination/`. No network,
no credentials, no randomness.

## Unresolved / needs manager call

- U-001: cross-process reservation locking out of scope (single-process app).
- U-002: risk→execution handoff unspecified in v0.1.0: Approved carries
  `reservation_id`, but execution `submit_entry` takes no reservation key and
  there is no fill/cancel/expire callback into risk to release it; likewise no
  defined risk-halt → execution exit-only signal. See
  `specs/acceptance-review-q001-e001.md` findings F-E001-04/F-E001-06.
- U-003: stress multiplier (1.5x forecast costs) and max evidence age (120 s)
  are simulation defaults, not measured values.
