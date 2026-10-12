# 24H Execution — Outcome Board (manager, young-polaris)

Base: `3cadfca`. Checkpoint: 13 Oct 20:53 IST. Live trading: DISABLED.

## Worker status (all ACKed, all branched @3cadfca)

| Worker | Assignment | State |
|---|---|---|
| W1 whisper-redshift | Streaming Session replay + economic benchmarks | running |
| W2 cloud-vega | Snapshot causality/sync, data clocks, funding backfill | running |
| W3 cool-amalthea | Risk profile + Binance contract + restart identities | running |
| W4 white-aldebaran | Event/anomaly protection + real source freshness | running |
| W5 crystal-parallax | Test guard + verification + supervision | running |

Shared-file queue: W1 streaming patch FIRST, then risk/event method patches.
W3 risk changes need manager/W5 review; W5 metric changes need manager review.

## Manager reproductions (all 6 confirmed @3cadfca, /tmp/repro24h/probe.py)

- A1 future snapshot: bid 200 @9000ms visible to 1500ms query,
  sync_age_ms=-7500, quality=clean. REPRODUCED (runtime).
- A2 false live-sync: gap diff returns resync yet prime discards
  apply_snapshot_record's return and reports synced; note on_diff's
  resync does not flip state.synced either (caller must act). REPRODUCED.
- A3 events disabled: events_enabled default False, unset in
  paper/r2/r3.toml; anomaly policy has no runtime caller. CONFIRMED.
- A4 fixture freshness: FixtureAdapter.load stamps fetched_utc=now_utc
  with status fresh on pure local read. CONFIRMED.
- A5 cross-symbol fill loss: trade id 777 BTC+ETH adopts 1 fill.
  REPRODUCED (runtime).
- A6 unknown block lost: recover() never rebuilds _reservations, so
  _unknown_for is empty after restart and re-entry is accepted.
  CONFIRMED (code path; runtime needs transport harness — W3).

## Exact blockers

1. Disk: ~5GB free; full 30d partitions would exceed it. W1 runs
   split-sequential with partition reuse + cleanup.
2. Full-window benchmark needs W1 streaming replay first (~70.6M rows).
3. Demo credentials: owner dependency, only after endpoint config +
   test script ready (W3). Never in chat.
4. Oct funding: API availability VERIFIED by manager (Oct-1 BTC
   settlements return fundingTime/Rate/markPrice); W2 owns
   pagination + provenance + reconcile.

## Manager baselines

- Network-blocked suite @3cadfca: 825 passed in ~39s (blocker verified:
  external refused, loopback allowed). W5's guard must preserve this.

## Review references (manager, for W3 contract review)

- algoOrder migration CONFIRMED: 2025-12-09 cutover; conditional types
  moved from /fapi/v1/order to /fapi/v1/algoOrder; legacy posts get
  -4120 STOP_ORDER_SWITCH_ALGO; new shape uses algoType=CONDITIONAL,
  returns algoId/algoStatus. Sources: Binance changelog 2025-11-06
  entry (mirrored), freqtrade#12610, community -4120 guides.
- Demo/test hosts: BOTH demo-fapi.binance.com and
  testnet.binancefuture.com answer /fapi/v1/time (manager probe).
  W3 owns the in-config choice + verification.

## Evidence preserved

Prior: reports/archive/48h-baseline/, /tmp/bt48h/*comparison.json,
runs/replay-48h-90s, runs/paper-48h-120s. Do not erase; mark superseded
results explicitly when replaced.
