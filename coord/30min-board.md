# 30-minute plan board

Baseline: `d733a61` (see `coord/30min-baseline.json`). Every job runs under
`tools/run_budget.py` with a declared input hash, budget, and stopping rule.

| Worker | Session | First batch | Status |
|---|---|---|---|
| W1 Execution | whisper-redshift | IOC lifecycle regression + corrected native integration | dispatched |
| W2 Data | cloud-vega | Cost contract + throughput profile + resumable CLI | dispatched (relabeled; see misroute fix) |
| W3 Runtime | cool-amalthea | Control-tick scheduler, stuck-input drill, prod preflight (orders off) | dispatched (relabeled; see misroute fix) |
| W4 Strategy | white-aldebaran | Funnel + preregistered ≤12-config round | dispatched (relabeled; see misroute fix) |
| W5 Verification | crystal-parallax | Adversarial probes + bounded demo procedure | dispatched |

Numbering: original 24H worker numbers kept (W2=data/perf, W3=runtime,
W4=strategy research). An earlier dispatch used 30-min-table numbers and
was voided on misroute notices from cloud-vega and white-aldebaran; no
work started under the voided labels.

First merge: budget enforcement + execution regressions.
Second merge: corrected execution/cost contracts + reliable control ticks.
Then: economic scoring on the corrected stack.
