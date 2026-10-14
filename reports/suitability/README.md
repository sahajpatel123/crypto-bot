# Data-suitability artifact (REL-W3-SUIT, Checkpoint-C §6)

Committed pre-round screen: coarse table + full audit verdicts.
Generated 2026-10-14 on `worker3/rel-suit` from main `ed20702`.

## Files

- `table.md` — coarse per-capture screen (Markdown).
- `table.json` — same rows as JSON.
- `audits/<capture>.json` — full `tools/audit_dataset.py` reports
  (profile `24h-1`, symbols BTCUSDT,ETHUSDT).

## Verdict mapping (coarse flag + audit verdict = claim)

| capture | coarse flag | audit verdict | claim for the next round |
|---|---|---|---|
| agreement-30s | OK | SCORABLE | scorable; short (29-30 exec s < 130 warmup bars); depth unsynced |
| cap-2h | OK | SCORABLE | scorable; exec gaps ≤8s starve admission across gaps; depth unsynced |
| cap-30min | NEEDS-AUDIT (INJECTED-GAPS=1) | SCORABLE | scorable; designed chaos gap dispositioned at warn level (exec gaps ≤4.5s); depth unsynced |
| cap-48h-90s | OK | SCORABLE | scorable; short (90 exec s < 130 warmup bars) |
| smoke-60s | OK | SCORABLE | scorable; short (59 exec s < 130 warmup bars); depth unsynced |

The table alone never certifies: every scorability claim above is
backed by its `audits/*.json` SCORABLE verdict. Warnings are quoted
from the audit reports, not paraphrased.

## Limits (binding)

- Coarse screen only; not a live-readiness claim.
- Funding rates absent on all rows: research assuming measured
  funding costs is unsuitable on every capture.
- `available UTC` = events.jsonl mtime (first availability on disk),
  distinct from the capture period.
- Prior-use = repo grep at generation time; absence means
  "not referenced", not "never used elsewhere".

## Reproduce

```sh
.venv/bin/python tools/run_budget.py --budget-s 600 \
  --checkpoint-dir /tmp/w3_suit_budget --report-out /tmp/w3_suit_budget/table.json \
  -- .venv/bin/python tools/suitability_table.py data/captures \
  --out reports/suitability/table.md --json-out reports/suitability/table.json
for c in agreement-30s cap-2h cap-30min cap-48h-90s smoke-60s; do
  .venv/bin/python tools/audit_dataset.py --capture data/captures/$c \
    --symbols BTCUSDT,ETHUSDT --out reports/suitability/audits/$c.json
done
```
