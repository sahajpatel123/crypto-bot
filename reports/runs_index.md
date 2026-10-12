# Per-run evidence index

Live run evidence is untracked under `runs/<run-id>/`. This file records the
demonstrated runs; re-run the listed command to reproduce each report.

| Run ID | Command (abridged) | Result |
|---|---|---|
| r1a-observed-400 | `run --mode replay --capture <400-event observed slice>` | 400 events, warmup-gated, 0 admitted, equity flat |
| r1b-breakout-demo | `--capture <synthetic 200-window breakout> --expect-class synthetic-test` | 1 admitted, BUY 0.679 @100.24 → SELL @100.46 (target), fees 0.0682, flat |
| r1c-resume-demo | same capture + `--crash-after 400`, then `--resume` | crash with open position → resume → identical close 120.081298937271 |
| r1d-stop-demo | `--capture <synthetic rise-then-fall>` | stop exit BUY @100.24 → SELL @100.0, loss contained, flat |

Historical frozen records (do not present as current results):

- `reports/m1_report.json` — M1 synthetic slice (superseded by the app).
- `data/observed/stream_cap-30min_report.*` — E-006 capture report; its
  `decision_latency_ms` metric is renamed to `collector_processing_latency_ms`
  in current tooling.
