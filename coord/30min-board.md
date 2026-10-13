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

## 30MIN status 2026-10-13 ~04:40Z (manager)
- main @ 25c6cb7: W5 IOC probes (61d4c04) + W5 cost/control probes (91d74ad)
  + W4 funnel/ROUND-01 (25c6cb7, via worker4/30min-research). Suite: 968
  passed, 1 skipped, 10 xfailed (4 IOC + 3 cost + 3 controls, all owned).
- W4-30MIN filed COMPLETE (funnel slice: 253 intents -> 2 filled + 8
  IOC-cancelled; ROUND-01 frozen 04:34:54Z, 11 configs, S5 excluded).
- In flight: W1 IOC arrival fix (paper_engine + test_ioc_arrival.py),
  W2 cost contract (costs.py + bench_run.py + test_costs.py),
  W3 runtime (session/producer/config + binance_live).
- Routing notes: cost reds -> cloud-vega (W2); control reds + missing-ts
  KeyError crash -> cool-amalthea (W3); W5 session name = crystal-parallax
  (bright-pegasus stale). One misroute to white-aldebaran bounced+fixed.
- W5-30MIN filed COMPLETE (branch worker5/30min-verify @cb358b6): 18
  probes (8 green, 10 red xfail, session-name owners), demo drill
  runner + procedure integrated (154102b, 890de6b) with safe paths
  manager-verified (no-creds full -> 0+4 BLOCKEDs; non-demo refused).
  W5 review: W4 batch PASS; W1/W2/W3 pending. IOC owner confirmed =
  whisper-redshift. Review note to W5: Phase-3 cids unasserted (fixed 66e8877).
- W1-30MIN filed COMPLETE + integrated (f11e899 + fdad744): arrival gate
  + remainder sweep, relabel superseded, 12 new tests. Manager repairs:
  attach_protection/order_status honor arrival-cancelled IOCs (ValueError
  refuse / CANCELED). Suite: 981 passed, 1 skipped, 9 xfailed.
  Price-band red GREEN/unmarked. 3 IOC reds await W5 probe updates
  (stale ioc_maker_relabeled key x2; marketable needs an arrival tick).
  Follow-up: Session._flatten off submit_immediate (manager-owned).
