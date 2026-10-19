# CEO-review black-box regressions — record (Worker 1, Q-003 Phase 1)

Source: `Muse_Crypto_Review_and_Next_Directive.md` Sec 1 (findings) + Sec 7
(repro probe). Tests live in `tests/ceo_review/` and drive PUBLIC interfaces
only (`Ledger`, `RiskPolicy`, `SliceRisk`, `plan_size`, `OrderManager`,
`FakeVenue`, `Intent`). Every test asserts the correct BUSINESS result from
the directive — never a copy of current buggy output.

## Inventory (20 tests)

| File | Finding | Business assertion |
|---|---|---|
| `test_ceo_ledger.py` (5) | F-CEO-01 | partial reductions keep the remaining entry basis (long 16.0, short 16.0); reversals set the new basis (20.0, then 24.0); fees reduce realised exactly once |
| `test_ceo_partial_fill.py` (2) | F-CEO-02 | 50% fill gets stop/target protection sized to filled qty; post-expiry risk stays occupied (Rejected, never Approved) |
| `test_ceo_timeout.py` (1) | F-CEO-03 | reservation past TTL without reconciliation blocks the next entry (Rejected) |
| `test_ceo_sizing.py` (2) | F-CEO-04 | worst-price planned loss + stressed costs within budget, long and short |
| `test_ceo_flows.py` (3) | F-CEO-06 | deposit/withdrawal never trigger target pause or daily halt; flows never become realised P&L |
| `test_ceo_nonfinite.py` (3) | F-CEO-07 | NaN cost / NaN account / infinite fee rejected (construction ValueError or Rejected); never Approved, never NaN notional |
| `test_ceo_fill_delta.py` (3) | v0.2.0 addendum | sink exposes `note_fill_delta`; duplicate exec_id booked once (no double-charge); NaN delta rejected before booking |
| `test_ceo_partial_fill.py` +1 | F-CEO-02/03 seam | filled reservation consumed into open position; post-expiry `booked_net(rid) != 0` + `release → False` (v0.2.0 precise ruling; `unresolved_ids()` is only for live-at-expiry unknowns) |

F-CEO-05 (evidence gate) is manager-owned (MG-001) and not covered here.

## Baseline runs (pre-fix): 15 failed, 5 passed — identical on both trees

- Tree A (review baseline): detached worktree at
  `871d1043c70aa0328e7be01053d8afd71b2cafe0`, tests run read-only via
  `PYTHONPATH=<tree>/src`, tree verified pristine after.
- Tree B (Q-003 branch base): `worker1/q-003` at `ec7dd62` (+ MG-001 gate
  fix, which touches none of these modules).
- Command: `pytest -q tests/ceo_review` → `15 failed, 5 passed` on both
  (11 failed on the original 16; the 4 addendum/seam tests fail on the
  missing v0.2.0 API and the silent purge).

Each failure was cross-checked against the directive's stated symptom
(not a blind pin):

| Failing test | Observed (wrong) | Directive symptom |
|---|---|---|
| long partial reductions | realised `76.0` vs `16.0` | "realized=76 versus equity gain=16" |
| short partial reductions | realised `-56.0` vs `16.0` | basis-reset mirror |
| partial protection | `ValueError: siblings attach only to a FILLED entry` | cannot attach protective siblings |
| expiry keeps occupied | `Approved` after expiry with venue fills | approves although exposure remains |
| unresolved timeout | second `Approved r-000002` | TTL permits another Approved |
| long/short worst-price | `4.568` / `4.566` vs budget `2.5` | "approximately 4.568 versus budget=2.5" |
| deposit target | `rejected:pause:daily-target`, realised `0` | deposit triggers target pause |
| withdrawal halt | `rejected:halt:daily-loss` | withdrawal trips halt |
| NaN cost / NaN account | `Approved` with `nan` notional/qty | "NaN yields Approved" |

Already-correct guards (5 passing pre-fix): long/short reversals, fees
charged once, flows-never-P&L at ledger level, infinite fee rejected via
the minimum-notional skip.

## Fix-after runs: 20/20 PASS on integrated main `d1dff76`

V-004 (ledger/risk) + E-005 (execution) integrated with v0.2.0 Protocol
code. `pytest -q tests/ceo_review` → `20 passed`. One expectation was
corrected per the manager's precise v0.2.0 ruling (filled reservations are
consumed into open-position state; the post-expiry block rides booked
exposure: `booked_net(rid) != 0` + `release → False`); all other assertions
passed unchanged. Existing suites: 244 passed (238 base + 6 runner); M1
slice green.
