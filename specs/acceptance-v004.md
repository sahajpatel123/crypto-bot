# V-004 invariant report: ledger + risk corrections (CEO Sec-7 probe)

Owner: Worker 3 (cool-amalthea). Base `ec7dd62` (170/170), branch
`worker3/v-004`. Verbatim probe `/tmp/v004_probe.py`; before/after outputs
kept at `/tmp/v004_probe_before.txt` / `/tmp/v004_probe_after.txt`.

## Before → after (probe evidence)

| Finding | Before | After |
|---|---|---|
| F-CEO-01 partial-close realised | 76.0 (basis reset) | 16.0; basis preserved until flat |
| F-CEO-04 adverse loss vs 2.5 budget | 4.568 over budget | 2.49999998 within budget |
| F-CEO-03 TTL without reconciliation | second Approved | Rejected `exposure:unresolved` |
| F-CEO-06 deposit-30 pause | pause with realised 0 | Approved, realised 0 |
| F-CEO-07 NaN forecast | Approved NaN/NaN | Rejected `health:nonfinite-cost` |
| F-CEO-02 partial+expiry | release → Approved, fill remains | STILL Approved: execution releases on expiry-with-fills today (E-005 owns that half; see below) |
| F-CEO-05 evidence gate | exit 1 (MG-001 fixed) | exit 1, unchanged, not my scope |

## Corrected invariants (risk/accounting side)

- L-01 Entry basis survives partial reductions (long and short); full close
  and reversal realise exact P&L less fees; funding is signed trading cash
  flow; external flows never touch realised P&L.
- L-02 Every fill/funding/flow carries a durable unique id; re-delivery is
  ignored (no double fees, no lost basis); save/load replays the ordered
  journal exactly and refuses snapshots that do not reconcile.
- R-01 First booked nonzero fill delta marks exposure; cancellation/expiry
  never proves flat; expired reservations move to `unresolved` and block
  until a sink callback reconciles them; expired-with-exposure is never
  purged.
- R-02 v0.2.0 sink: `note_fill_delta` validates all fields and books
  idempotently by exec_id; `note_fill` is the first-nonzero transition
  (never terminal-full); `release` frees only zero-booked ids (True only
  when live); `note_flat` clears only on reconciled net-zero (1e-9 dust
  tolerance, documented).
- R-03 Sizing bounds loss at the adverse permitted fill (LONG high / SHORT
  low), rounds quantity DOWN to the venue step, and rechecks budget,
  leverage, and minimum notional; never rounds up to meet a minimum.
- R-04 Configured instrument filters are mandatory per symbol with fresh
  as-of metadata; unknown/stale blocks submission (`filters:*`).
- R-05 Halt/target/floor compare flow-adjusted equity against persisted
  baselines; deposits cannot trip targets or replenish protection, and
  withdrawals cannot fake it; real losses still halt.
- R-06 Nonfinite costs/prices/accounts, bad enums, nonpositive prices,
  naive timestamps, boundary-expired intents, and future evidence beyond
  the 5 s skew allowance are rejected; invalid configs raise at
  construction.
- R-07 `check_health` latches rollover/halt/pause/floor/expiry without an
  intent; the integrated runtime drives exposure reduction off latched
  state (halt → exit-only is execution-owned).
- R-08 v1 risk state migrates explicitly to v2 (unresolved + booked +
  baselines defaulted, reconciliation forced); unknown versions raise.

## Deliberate V-001 behavior changes (mandated by the directive)

- Expired reservations are retained, not purged
  (`test_expired_reservation_retained_until_reconciled`).
- Sizing moved mid-price → adverse-price, notional-first → qty-first with
  floor rounding; `SliceDecision.qty` now forwards policy qty instead of
  recomputing over mid.
- Expiry at exactly `now` rejects (was: passes); configs validate eagerly.

## Split ownership: F-CEO-02

The probe's F-CEO-02 case still approves after expiry because the CURRENT
execution manager releases the reservation on expiry-with-fills without
sending fill deltas. The risk side is ready: any `note_fill_delta` books
exposure, `release` with nonzero booked returns False retaining the block,
and `note_flat` waits for net-zero. Full closure needs E-005 (delta
propagation, no release-with-exposure, late-fill booking). No NEW
risk↔execution interface deltas are proposed: the v0.2.0 addendum contract
suffices once E-005 calls it. True available-margin input (beyond the
notional/3 proxy) is proposed as a future addendum item, not landed.

## Compatibility notes (for manager ruling)

- `AccountSnapshot.flows_cumulative` is an OPTIONAL new field (default 0.0);
  existing constructions behave exactly as before.
- `RiskConfig` gained validated optional filter/skew fields; no existing
  construction changes meaning. `contract_version` default is now v0.1.1.
- `reconcile_day` gained an optional `flows_cumulative` parameter.

## Unresolved

- F-CEO-02 full closure pending E-005 + manager integration (risk side
  complete and tested).
- Available-margin input pending a future execution-side addendum.
- U-001 unchanged: single-process scope, no distributed locking.
