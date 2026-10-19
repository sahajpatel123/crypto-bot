# Recorder run layout (F3 data engine)

Long-running capture for BTC/ETH USD-M public streams. Each run writes to a
run directory (default `data/recorder/runs/<run-id>/`).

## Layout

```
<run-id>/
  chunks/
    BTCUSDT.aggTrade.20260101T00.jsonl.gz   # sealed hourly chunk (gzipped)
    BTCUSDT.depth.20260101T00.jsonl         # live hour (plain JSONL, sealed on rotation)
    ...
  manifest.jsonl                             # hash-chained chunk manifest
```

## Chunk format

One JSON object per line:

* WS events: `cryptobot-events/1` records from `events.parse_message`
  (`channel`, `symbol`, `exchange_ts_ms`, `local_recv_ms`, `venue_seq`,
  `payload`, `gap_kind`), plus `forceOrder` liquidation records
  (`route: "liquidations"`).
* REST polls: `cryptobot-rest-polls/1` records (`channel` in
  `openInterest | fundingRate | premiumIndex`, `route: "rest"`).

Chunk naming: `<SYMBOL>.<stream>.<YYYYMMDDTHH>.jsonl` (`.gz` after rotation).

## Manifest chain

Each `manifest.jsonl` line seals one chunk: file name, symbol/stream/hour,
event count, byte size, chunk SHA-256, `gapped` flag, `prev_hash`, and the
`entry_hash` chaining it to the next entry. Genesis `prev_hash` is 64 zeros.

Verify a run (tamper-evident: fails on modified chunks or broken linkage):

```bash
PYTHONPATH=src python -c "
from cryptobot.recorder import verify_manifest_chain
import json
print(json.dumps(verify_manifest_chain('data/recorder/runs/<run-id>/manifest.jsonl'), indent=2))
"
```

Daily integrity report (gap rate, trade-ID gaps, timestamp monotonicity,
depth-chain breaks):

```bash
PYTHONPATH=src python -c "
from cryptobot.recorder import build_report, render_markdown
print(render_markdown(build_report('data/recorder/runs/<run-id>')))
"
```

## Disk budget guidance

* The recorder NEVER deletes data. The disk monitor only alerts (log +
  `alert` callback) and, with `clean_stop_on_low_disk`, halts capture loops
  for a clean, fsync'd shutdown via `stop()`.
* Set `disk_min_free_bytes` to at least 2x the expected daily capture volume.
  As a starting point: 5 GiB floor for the BTC/ETH set at 100 ms depth.
* Provision: measure one full day, then size retention as
  `daily_bytes * retention_days * 1.5` headroom. Archive or move sealed
  `.jsonl.gz` chunks plus `manifest.jsonl` together — never one without the
  other, or the chain cannot verify.
* systemd: `ops/systemd/cryptobot-recorder.service` runs
  `cryptobot recorder start` with `restart=on-failure` and a
  `StartLimitBurst` crash-loop breaker (CLI wiring by owner).
