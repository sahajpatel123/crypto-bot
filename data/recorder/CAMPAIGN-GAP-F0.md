# F3.4 — Campaign gap note (F0 re-entry, no campaign access)

## Why this note exists instead of a campaign read

F3.4 asks to read the running campaign's manifest metadata and record
what it lacks. In THIS worktree the campaign does not exist:
`data/captures/` is gitignored (see `.gitignore`: `data/captures/`)
and the worktree `data/` holds only `keydata/`, `observed/`,
`README.md`. The live campaign
(`data/captures/campaign-1day-20261017`) runs in the MAIN checkout's
working directory only.

Hard rule 3 forbids reading uncommitted files in the main checkout;
that rule dominates F3.4's read permission (a manifest in the main
checkout IS an uncommitted file there). The campaign was therefore
not read, listed, duplicated, or disturbed in any way. No
`data/captures` path was opened from this worktree.

## What the campaign presumably lacks (from the E-006 collector spec)

The campaign runs on `tools/capture_stream.py` + the E-006 supervised
collector (`src/cryptobot/market_data/collector.py`: market route
aggTrade + markPrice@1s, public route bookTicker + depth@100ms, diff
resync, heartbeat, manifest, bounded storage). Verified by grep on the
committed collector: it has fsync-on-write (`collector.py:311`) but

- NO `forceOrder` (liquidation) stream,
- NO REST polling for openInterest / fundingRate / premiumIndex,
- NO USDC-margined perp check,
- NO hourly chunk rotation, NO compression (gzip),
- NO hash-chained manifests (run manifest exists, not hash-chained),
- NO Parquet compaction, NO daily integrity report (gap rate,
  trade-ID continuity, timestamp monotonicity, depth-chain breaks),
- NO venue plugins (Bybit/OKX),
- NO disk-budget monitor with alerts (bounded storage stops cleanly,
  no alert sink),
- writer durability is synchronous per-event, not the F3 writer
  thread with bounded buffer + overflow gap-flagging.

These gaps are exactly the F3.1–F3.3 build scope owned by the
`src/cryptobot/recorder/` package (writer, streams, plugins,
integrity, service) in this worktree. When the owner starts the F3
recorder on the capture host, it supersedes the campaign collector;
until then the campaign continues untouched.

## Reconciliation path (owner, credentialed host only)

On the host that runs the campaign (NOT from this worktree):

```sh
cat data/captures/campaign-1day-*/manifest.json  # metadata only
cat data/captures/campaign-1day-*/heartbeat.json
ls data/captures/campaign-1day-*/               # file list, no event reads
```

Compare the manifest's stream list against F3.1; any stream above
that the manifest lacks confirms this note. Never open event files.
