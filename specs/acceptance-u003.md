# U-003 disposition: unmeasured risk defaults (V-003, v0.1.1)

Owner: Worker 3 (cool-amalthea). Disposition: **pinned as labelled
simulation defaults** (not measured — no calibrated cost/latency dataset
exists on the risk side yet). Both values are marked `U-003 SIMULATION
DEFAULT` at the definition site (`src/cryptobot/risk/types.py`), bounded by
tests (`tests/acceptance/test_risk_u003.py`), and governed by the measurement
plan below. No behaviour change to the accepted V-001 gates.

## Pinned values and rationale

- `stress_multiplier = 1.5`: uplifts the S1 per-side forecast costs
  (fee+spread+slippage+funding) before sizing. Rationale: conservative while
  fee tiers are unverified and slippage variance is unknown; the sizing test
  proves the multiplier scales only the stressed-cost term, leaves the stop
  term untouched, and shrinks notional monotonically (1.0x > 1.5x > 3.0x).
- `max_evidence_age_s = 120.0`: rejects intents whose evidence is older than
  120 s at gate time. Rationale: far above any plausible simulation
  decision-to-gate delay, far below S1 holding horizons (30–300 s), so it
  rejects genuinely stale signals without biting live ones. Boundary-tested:
  exactly 120 s passes, 121 s rejects with `stale:evidence-age`.

## Measurement plan (promotion criteria)

Neither default may be promoted to a measured value until all of the below
hold; promotion lands as a config change plus updated tests, never a silent
edit.

1. Cost inputs (stress multiplier): Worker 2 recorder/replayer exports
   realised fee bps (account fee tier lookup), touched-spread distributions,
   and slippage-vs-mid samples over >= 10k bars of real public data.
   Estimator: `stress := p99(realised_bps / forecast_bps)` per side,
   floored at 1.0, recomputed per instrument.
2. Latency inputs (evidence age): instrument decision-to-gate delay
   (strategy emit → coordinator → risk evaluate) plus feed gap/stale stats
   from the replayer over the same corpus. Estimator:
   `max_age := p99(gate_delay) + 5 * p99(inter-bar gap)`, ceiling 300 s.
3. Both estimators rerun on the validation split; promotion requires the
   validation estimate within 20% of the train estimate, else keep pinned.
4. Owner: Worker 2 produces the datasets; Worker 3 recomputes and re-tests.

## U-001 (noted, out of scope)

Cross-process reservation locking stays unbuilt: DECISIONS fixes a modular
single-process app, and `RiskPolicy.evaluate` is synchronous and atomic
within one process. If a second risk-writer process ever appears, this item
must be reopened before it runs.

## v0.1.1 wiring: integration note for the manager

`src/cryptobot/risk/slice.py::SliceRisk` is the drop-in for the slice-local
`risk_stub` in `tools/m1_vertical_slice.py` (manager-owned; not edited here):

```python
from cryptobot.risk import SliceRisk
gate = SliceRisk(state_path="reports/m1_risk_state.json",
                 day_start_equity=equity)
decision = gate.evaluate(good, (good.entry_low + good.entry_high) / 2)
ok, reason, notional = decision.ok, decision.reason, decision.notional_usdt
# after the venue fill:
gate.note_slice_fill(decision.reservation_id, "BUY", decision.qty, mid)
```

Reasons are labelled `risk-policy:approved:...` /
`risk-policy:rejected:<gate-reason>` (no `risk-stub` labelling remains).
`SliceRisk.policy` is the accepted V-001 `RiskPolicy`, already
`RiskOutcomeSink`-conformant, with duplicate-callback tolerance covered by
`tests/acceptance/test_risk_wiring.py`.
