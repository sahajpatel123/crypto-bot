# Binance demo validation command (PREPARED — NOT EXECUTED)

Status: **BINANCE DEMO VALIDATION PENDING**. The sandbox drill
(`tools/audit/sandbox_drill.py full`) proves execution mechanics
against simulated venue responses only. This document prepares the
exact bounded live-demo command for later execution by the repo
owner with owner-supplied credentials. No demo command has been run
from this branch; no credentials exist on this branch.

## Exact command (Binance USD-M testnet/demo, bounded)

```bash
cd /Users/sahajpatel/Code/cryto-bot
PYTHONPATH=src python3 tools/run_budget.py \
  --budget-s 1500 \
  --checkpoint-dir /tmp/demo-drill-ckpt \
  --report-out /tmp/demo-drill-report.json \
  --heartbeat-s 120 \
  -- python3 tools/audit/demo_drill.py \
      --dir /tmp/demo-drill \
      preflight
```

Then, only if preflight passes:

```bash
PYTHONPATH=src python3 tools/audit/demo_drill.py \
    --dir /tmp/demo-drill \
    full
```

Bounds (hard-coded in `demo_drill.py`, not operator promises):
- single instrument BTCUSDT, one tiny IOC entry (~$6 notional),
  $25 notional exposure cap with KILL on breach;
- 20-minute entry cutoff, 25-minute close-by, 3-minute exit margin;
- failed/blocked preflight prevents entry AND adoption;
- full exits 1 on any FAIL, 2 on any BLOCKED/omitted phase.

## Credential configuration (secure)

1. Create a **Binance Futures testnet** API key with **TRADE-only**
   permission (no withdrawals, IP-allowlisted). Never use mainnet
   keys for the drill.
2. Export ONLY in the executing shell (never commit, never log):
   `export BINANCE_DEMO_KEY=... BINANCE_DEMO_SECRET=...`
3. The drill reads credentials exclusively from those two
   environment variables (see `demo_drill.py` credentials block);
   it refuses to run with placeholder or missing values and never
   writes them to evidence output. Point `--base-url` at the
   testnet USD-M endpoint for the run.

## Promotion rule

Demo PASS does not promote anything by itself. Promotion still
requires the manager's release gate (locked evaluation + 100
closed out-of-sample positions / 10-day screen or DATA BLOCKED).
