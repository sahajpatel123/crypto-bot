# ARCHITECTURE

```
public venues ──► recorder (standalone, public data only)
                     │  hourly gzip chunks + SHA-256 hash-chained manifest
                     ▼
                sealed vault (DEV / CONFIRM, hash-chained access log)
                     │  CONFIRM readable only by verdict + one-shot token
                     ▼
             research autopilot (H1–H6, ≤8 budget)
   REGISTERED → DEV_EVAL → {KILLED | AWAIT_CONFIRM_DATA}
              → CONFIRM → {FAIL | PASS} → PAPER_14D → PAPER_COMPARE
              → GATE_READY
                     │
                     ▼
        verdict (hash-bound PASS/FAIL/UNDERPOWERED)
                     │
                     ▼
        gate (evidence-only, 24h expiry) ──► NO-GO by default
                     │
                     ▼
        arm (human TTY only, typed phrase, capital + daily loss)
                     │
                     ▼
        live session (one position, reduce-only exits, ladder)
```

```
data.binance.vision ──► lake pull (checksummed, filename-date split)
(public, no keys)         │  DEV zips ──► parquet (decoded, DQ'd)
                          │  HOLDOUT zips ──► sealed by byte-hash, never decoded
                          ▼
                 vault HOLDOUT manifests (verdict-only decode, access-log
                          │  eligibility: zero pre-freeze decodes)
                          ▼
          Family B backtester (59 frozen cells, dual-engine,
                          │  walk-forward OOS, DSR/PBO/reality-check)
                          ▼
          verdict --holdout-screen (exactly once per survivor,
                          │  SEALED-HOLDOUT provenance, SCREEN_PASS/FAIL)
                          ▼
          autopilot_b → FORWARD_PAPER → FORWARD_COMPARE → GATE_READY
                          │  (same gate/arm ceremony as Family A)
```

## Boundaries

- **Recorder** never imports the trading session and uses no credentials.
  It can run while the bot is stopped. Its writer is bounded; overflow is
  counted and marks the interval GAPPED. Chunks are sealed into a
  hash-chained manifest.
- **Vault** is the only research data source for confirmation. It refuses
  `CONFIRM` chunks unless the hypothesis was frozen *before* the chunk was
  sealed. `CONFIRM` reads require a one-shot token issued only to
  `verdict`. See `data/vault.py` and `tests/unit/test_vault.py`.
- **Autopilot** is idempotent: repeated `run-once` with unchanged
  artifacts performs no transition. Every transition is hash-chained.
  It never arms and never edits gate/verdict artifacts.
- **Verdict** is a pure function of trades + config/data/code hashes. It
  has no override flag.
- **Gate** requires GATE_READY, sealed provenance, a fresh calibrated cost
  model, fresh host-check, fresh demo drill, measured WS latency/drops and
  a fresh watchdog heartbeat. Missing evidence is NO-GO.
- **Arm** requires an interactive TTY, no CI environment, a GO gate that
  has not expired, a typed phrase and positive capital/daily-loss. It
  writes a record; it never submits an order.
- **Live session** is one-position, stop-first, reduce-only exits,
  fail-closed on stale/unknown venue truth, with a capital ladder and
  automatic demotion. Promotion is manual only.
- **Watchdog** is an external process: stale heartbeat + exposure triggers
  the owner-configured flatten command, never a hardcoded venue call.

## Data classes

| Class | Source | Use |
|---|---|---|
| `SYNTHETIC` | tests/acceptance | never gate/verdict; gate rejects |
| `DEV` | already-inspected dev data | research exploration only |
| `CONFIRM` | sealed after hypothesis freeze | exactly-once verdict only |
| `HOLDOUT` | sealed BEFORE any Family B freeze | verdict-only decode; eligible only with zero pre-freeze decodes |
| `OBSERVED_PUBLIC` | data.binance.vision / public REST | lake provenance (DEV decoded; HOLDOUT hashed) |

`data/pilot` and `datasets/benchmark_30d` are DEVELOPMENT data.
`data/captures/campaign-1day-*` is untouched confirmation data; this
program only read its manifest/heartbeat/status metadata.

## Key modules

- `market_data/live_recorder.py` — streams, writer, manifests, integrity.
- `data/vault.py` — sealed registry, tokens, access log.
- `research/autopilot.py`, `research/power.py`, `research/verdict.py`.
- `research/calibration.py` — monotonic cost-model updates.
- `risk/margin.py` — tiered maintenance margin + liquidation admission.
- `risk/ladder.py` — canary, demotion reasons.
- `app/session.py` — one order lifecycle, protection, flatten, safe mode.
- `adapters/binance_live.py` — signed REST/WS adapter, live-off by default.
- `research/lake.py`, `research/universe.py` — parquet lake + point-in-time universe.
- `research/family_b.py`, `research/slow_backtest.py` — frozen signals + dual-engine backtester.
- `research/slow_stats.py`, `research/family_b_driver.py` — inference + frozen evaluation runner.
- `tools/vision_pull.py`, `tools/run_family_b.py`, `tools/lake_finalize.py` — data + eval CLIs.
