# E-COST capture harness (measurement only)

Status: **harness + report template, synthetic receipts only.** No live/demo
calls, no holdout, no DSR. The owner runs the 30-day fills later on Binance
demo (trade-only keys) and approves any restatement adoption.

Source plan: Synapse E-COST measurement plan (measurement-only, cannot PASS
anything). This tool can only CONFIRM modeled costs or RESTATE them; costs
move in the conservative direction only.

## Usage (owner)

```sh
python tools/ecost.py template --out ecost/
# fill ecost/receipt-template.jsonl (one JSON object per line) from venue
# receipts, and ecost/config-template.json with the modeled costs + the
# filling account's fee-tier evidence (VIP level, BNB-burn, source)
python tools/ecost.py report --receipts ecost/receipts.jsonl \
  --config ecost/config.json --out ecost/
# exit 0 + ecost/ecost-report.json with verdict, or exit 2 REFUSED
```

## Receipt schema (all fields observed, none defaulted)

Fill (`kind: fill`): fill_id, venue_path (demo|sim), symbol, leg
(spot|perp), side (buy|sell), qty, notional, fill_price, signal_bar_open,
spread_bps, fee_bps, fill_time (ISO UTC, after 2026-10-17), round_trip_id,
adv20, sigma_d.

Funding (`kind: funding`): record_id, venue_path, symbol, settlement_time,
paid_rate_bp, vision_rate_bp, vision_file (monthly file strictly newer
than 2026-10 — the Oct file is holdout-dated and refused).

## Formulas (frozen in `tools/ecost.py`)

- slippage_bps = side_sign × (fill_price − signal_bar_open) / signal_bar_open
  × 1e4, side_sign +1 buy / −1 sell (positive = adverse).
- fill_cost_bps = fee_bps + slippage_bps.
- realized_RT = Σ fill_cost_bps_i × notional_i / rt_notional, rt_notional =
  earliest fill's notional in the round_trip_id group (≥2 fills required).
- modeled_impact_bps (diagnostic) = 0.5 × sigma_d × √(notional/adv20) × 1e4.
- Median = statistics.median; p90 = nearest-rank ceil(0.9n).

## Verdicts

Power gate first: ≥30 calendar days AND ≥20 fills per (symbol, leg), else
UNDERPOWERED with extend-in-30d-blocks guidance (90d max, then descriptive
statistics only). When powered, funding must reconcile to zero vs Vision
(|delta| ≤ 1e-6 bp) or the tool refuses with no verdict. Then per symbol
against config modeled_rt_bps: median > 2× modeled → COST-MODEL-KILLED;
median > modeled → RESTATE-UP (restated values = realized medians);
p90 > 2× modeled with median inside → RESTATE-UP naming the tail
(conservative extension of the draft, documented in code for review);
else CONFIRMED. Downward restatements are recorded, never adopted without
a new preregistration (there is no adoption path in this tool).

## Refusals (exit 2, fail-closed)

Missing/null/type-invalid field; mixed demo+sim venue paths; pre-window
fill_time; Oct-or-older vision month; round-trip group under 2 fills;
funding mismatch. Guard-deletion proofs in `tests/unit/test_ecost.py`
(49 tests, synthetic only).
