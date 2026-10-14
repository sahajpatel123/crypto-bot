# REV2 R5 — H-R2 causal correction (FINAL)

Branch `worker4/rev2-research`, base `rev2/integration` @ `006fca9`.
Tool `tools/hr2_diagnostic.py` rewritten (v2) under corrected semantics;
v1 figures archived to `outputs/hr2/superseded/` (never citable).
Recomputed ONCE: one budgeted job, 89.1s elapsed, CHILD_EXIT rc=0.

## Corrected rules (all timestamps exchange-time)

| rule | v1 (defective) | v2 (corrected, source) |
|------|----------------|------------------------|
| arrival | first book ≥ evidence_ts (fills 1.58s med. BEFORE decision) | first book ≥ decision+100ms (R01 submit 50 + fill 50); asserted per row |
| quote age | none | latest book/trade ≤ decision within 1000ms (quote_max_age_s), else unscorable |
| stop/target exit | triggering print px = fill | trigger + first book ≥ trigger+100ms, exit-side touch; none → unscorable |
| time exit | touch at t_exit | first book ≥ t_exit+100ms, exit-side touch |
| markouts | last mark carried forward | mark ≤5s old + book/trade coverage within 5s of horizon, else unscorable |
| funding | excluded + invented ≤0.01bp bound | engine rule: settle iff sourced next_funding_ms in (fill, exit]; none → 0 with provenance; no marks → unknown |
| size/expiry | unit $20, IOC cap, expiry | unchanged (kept) |
| trigger/fill order | prints ≥ arrival book ts | prints strictly AFTER fill_ts (same-ms unorderable, excluded) |

## Recompute results (61/61 accounted, development data)

- Entry: 60 filled, 1 unfilled(unmarketable). No stale-at-decision, no
  zero-size, no expiries.
- Exit: 50 stop, 4 target, 6 time (executable touches, not triggers).
- Net: 60 nets, mean −13.42 bps (v1: −13.04). Direction unchanged
  (negative); magnitudes corrected, not profitability either way.
- Markouts: 2/244 legs unscorable(unsupported-horizon) (v1: 0 —
  carried stale marks).
- Funding: zero(no-settlement-boundary-in-hold) on all 60 (holds
  ≤300s vs 8h settlements; no invented bound).
- Corrected H-R2 null verdict: the floor-correctly-rejects null is
  NOT rejected — counterfactual mean net remains negative under
  causal execution. (Diagnostic only; not a strategy result.)
- Portfolio overlay (diagnostic): 6 admitted on decision-ts ordering,
  mean −15.02 bps.

## v1 → v2 movement audit

60/61 fill timestamps moved later (causal); 51/61 exit prices changed
(trigger→touch + latency); 2 markout legs newly unscorable. Ref set
identical (61/61). v1 = 60/60 fills before decision; v2 = 0.

## Causality audit (machine, fails loud)

`hr2_diagnostic.py audit`: 61 rows, ref set exact; checks fill ≥
decision+100ms, exit ≥ fill, trigger > fill. Verdict: CAUSAL,
0 violations.

## Provenance

Frozen semantics: R01 submit/fill 50ms (configs/round01*.toml),
quote_max_age_s 1.0 (app defaults), taker IOC (paper engine),
funding boundaries (engine _settle_funding + markPrice terms).
Predeclared bounds: mark age 5s, coverage 5s (markPrice 1s cadence).
Unit $20 notional diagnostic constant retained + disclosed.
