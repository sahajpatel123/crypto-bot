# 30-minute plan board

Baseline: `d733a61` (see `coord/30min-baseline.json`). Every job runs under
`tools/run_budget.py` with a declared input hash, budget, and stopping rule.

| Worker | Session | First batch | Status |
|---|---|---|---|
| W1 Execution | whisper-redshift | IOC lifecycle regression + corrected native integration | dispatched |
| W2 Runtime | cool-amalthea | Control-tick scheduler, stuck-input drill, prod preflight (orders off) | dispatched |
| W3 Strategy | white-aldebaran | Funnel + preregistered ≤12-config round | dispatched |
| W4 Data | cloud-vega | Cost contract + throughput profile + resumable CLI | dispatched |
| W5 Verification | crystal-parallax | Adversarial probes + bounded demo procedure | dispatched |

First merge: budget enforcement + execution regressions.
Second merge: corrected execution/cost contracts + reliable control ticks.
Then: economic scoring on the corrected stack.
