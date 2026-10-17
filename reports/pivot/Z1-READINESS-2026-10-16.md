# Z1 capture readiness — executed checklist (2026-10-16)

Runbook: `coord/pivot/CAPTURE-RUNBOOK.md` step 0 (peer-owned; executed
here read-only, no capture started per the owner's no-bulk-collection
bound).

## Results

1. Discovery: 525 USDT-perp TRADING symbols, 524 eligible — PASS.
2. Dry-run (`--top-n 2 --duration-s 60 --dry-run`): selection
   BTCUSDT+ETHUSDT, clock_offset_ms 67.2 — PASS.
3. Disk: 13GiB free on this host — FAIL for a 10-day capture
   (~186GB top-2 measured; see `reports/pivot/README.md` sizing).

## Verdict

Z1 stays RED: tooling is ready, storage is not. Proceed only on a
host (or external volume) with >=256GB free, then run the enrollment
auditor (`tools/pivot_enroll.py`, incl. `--funding-file` provenance
sidecar) before any scoring claim. No bytes captured by this check.
