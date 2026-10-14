# H-R2 report — rejected-candidate counterfactuals (manager-executed, release §6)

Status: COMPLETE. Verdict: **H-R2 REJECTED** — rejected candidates show
no executable edge; counterfactuals are decisively negative.
Frozen design: `trials/ready-01.json`. Tool: `tools/hr2_diagnostic.py`.
Per-candidate rows: `outputs/hr2/diagnostics.json`. Windows regenerable
via `extract` (excluded from git, 4.2GB).

## Method (summary; full disclosure in the tool docstring)

- One bounded streaming pass per capture; per-candidate windows
  [evidence−5s, evidence+320s], ETHUSDT book/prints/marks only.
- Arrival = first bookTicker at/after evidence; IOC at touch inside the
  protected band; $20-notional unit qty (diagnostic constant);
  short size → partial + cancel.
- Forward exits on aggTrade prints in causal order, stop-first ties;
  time exit at adverse touch. Markouts 30/60/120/300s on marks.
- Costs: 5bps/leg labeled fees; spread/slippage ZERO added (contained
  in touch fills / implicit in arrival latency — no double charge);
  funding excluded with ≤0.01bp quantified bound.
- Portfolio overlay: time order + one-position + 300s cooldown.

## Results (all 61 accounted, zero unscorable)

| Leg | Outcome |
|---|---|
| Entry | 60 filled/partial, 1 unfilled(unmarketable), 0 unscorable |
| Exits | 50 stop / 4 target / 6 time (min lag 4.7s, p50 27.6s, no zero-lag) |
| Exit net | mean −13.04bps, **0/60 wins** |
| Markouts | 30s −11.67, 60s −13.81, 120s −8.00, 300s −12.64 (n=60 each) |
| Portfolio overlay | 5 admitted, 56 skipped (busy/cooldown), −63.49bps total |
| Brackets | 60/60 correctly placed (stop adverse, target favorable) |

Frozen-variant shortcut validated against
`selector.py:99` (`reward < round_trip * multiple`): 1.0→0, 0.75→0,
0.5→1 (S1) — matches the §6 expectation exactly.

## Interpretation

Setups lose on BOTH direction (83% stop rate, negative markouts at
every horizon) and costs (even the 4 target hits net negative: median
target 4.87bps < 10bps round-trip fees). The cost floor is not
miscalibrated — it correctly rejects edge-free setups. H-R1's
deep-rejection finding is corroborated from the outcome side.

## Limitations (stated, not hidden)

- Unit $20 qty is a diagnostic constant; impact unmodeled (small-size
  assumption, top-of-book only).
- Fees are labeled-schedule (5bps/leg), not the owner's account rates.
- Funding excluded (bounded ≤0.01bp over ≤300s holds).
- Captures are development knowledge; no locked-evaluation claim.
- Counterfactual diagnostics, never portfolio P&L or strategy trades.
