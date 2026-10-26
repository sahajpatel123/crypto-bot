# #49 recorder inputs (P1/P2/P4) — design + scope note

Status: **implemented on `live/n49-recorder-inputs`, code only — NO deploy,
NO restart.** The edge tree, guard, STOP file, and launchd jobs are
untouched. Deploying this to `release/v1` is an owner decision with the
same single-restart discipline as #45.

Audited base: `live/trade-ready` (`3968cc7`).

## 1. What was missing (#49)

D1's evaluator (`research d1-eval`) fails closed on exactly two recorder
inputs: `funding_settlements` (no settled `fundingRate` anywhere; the 60 s
`premiumIndex` poll carries only a next-rate estimate) and
`universe_daily_klines` (no `kline_1d` records, so the frozen universe
cannot be ranked at all). A third finding from the same audit: the
module docstring claimed a `fundingRate` REST poll that never existed.
That mismatch is fixed in this branch.

## 2. Record formats (additive; FORMAT stays `cryptobot-recorder/2`)

No chunk-format, header-format, or manifest-schema change. New inputs ride
existing paths: REST records through `writer.submit()`, manifest `streams`
gains additive tokens, sealed chunks stay immutable.

**P1 — settled funding** (`_funding_sweep`, every `funding_poll_s` = 900 s):

```json
{"type": "funding_rate_settled", "stream": "funding_settlement",
 "venue": "binance", "symbol": "BTCUSDT", "event_ms": 1792934400000,
 "fundingRate": "0.00010000",
 "payload": {"fundingRate": "0.00010000", "fundingTime": 1792934400000},
 "grid_8h": true, "universe_source": "exchangeInfo"}
```

- `type` is a member of `d1_eval.FUNDING_RECORD_TYPES`; `stream` fills the
  `funding` bucket via `classify_stream`. Both sides are pinned by
  `test_n49_record_types_fill_d1_buckets` with zero evaluator changes.
- Exactly-once per settlement under restarts via `funding_state.json`
  high-water marks. Cold start seeds marks at boot: pre-boot history is
  skipped, never backfilled (stamping it could poison a chunk with
  sealed-window records). Warm restarts re-emit downtime settlements.
- Off-8h-grid rows (1h/4h funding symbols) are kept with `grid_8h: false`
  plus one alert per symbol — never dropped.

**P2 — daily klines** (`_kline_sweep`, once per UTC day after 00:05):

```json
{"type": "kline_1d", "venue": "binance", "symbol": "BTCUSDT",
 "event_ms": 1792944000000, "exchange_open_ms": 1792857600000,
 "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0,
 "close_ms": 1792943999999, "quote_volume": 123.5, "trades": 100,
 "taker_base": 5.0, "taker_quote": 61.75,
 "universe_source": "exchangeInfo", "universe_size": 412}
```

- Only completed bars (`closeTime` in the past) are emitted, so
  `quote_volume` is final. `event_ms` is the pull time (fresh, keeps chunk
  timestamp monotonicity); D1 attributes the day from `exchange_open_ms`.
- One pull per day is enforced by `kline_state.json`, and a day is marked
  pulled only when every symbol succeeds: a partial pull (any error) leaves
  the day unmarked and retries ≥30 min apart via `last_attempt_ms`, so
  failed symbols are never permanently missing (F-A). A restart mid-pull
  may re-emit a day, which D1 absorbs idempotently
  (`daily_quote_volume[day]` overwrite).

## 3. Scope decision (owner): full listing vs explicit symbols

D1's `monthly_rankings()` ranks the **candidate listing** by previous-month
`quote_volume`. Recording klines for only the two WS symbols would satisfy
the field while violating the rule — so the default is the FULL live
listing (TRADING + PERPETUAL + USDT from `/fapi/v1/exchangeInfo`,
re-discovered daily), and an explicit `--kline-symbols` subset is tagged
`universe_source: "explicit"` plus `universe_size` on every record. If live
discovery fails, the sweep degrades to the WS symbols exactly once per day
with a `universe-discovery-failed` alert and `config-fallback` provenance —
never silently. REST cost at ~400 symbols: funding ≈ 400 weight-1 calls per
15 min, klines ≈ 400 weight-2 calls per day — far under limits.

## 4. Restart hardening (P4)

- **Orphan quarantine**: startup renames any `rec-*.jsonl.gz` not referenced
  by the manifest to `orphan-*` (alert `orphan-quarantined`). The five
  historical twins could not recur; see `RECORDER_QUARANTINE.md`.
- **Loud ENOSPC**: any `OSError` in the write path (chunk bytes, seal,
  heartbeat) alerts `writer-fatal`, stops the writer, leaves the partial
  chunk unsealed (next startup quarantines it), and propagates out of
  `close()`/`run()` so the process exits nonzero. Restart pacing stays with
  the deployed launchd `ThrottleInterval` + guard restart margin.
- **Time-based heartbeat**: every `heartbeat_s` (15 s) regardless of record
  count, with `ws_alive` (frame within `ws_alive_s` = 120 s), `ws_idle_s`,
  and cumulative `records_total`. The old every-200-records heartbeat froze
  on tiny chunks and faked staleness.
- **Headers/gaps carry `event_ms`**: `d1_eval.read_records` refuses any
  record without an integer `event_ms`, headers included. New chunks comply;
  old chunk headers do not.

## 5. Known follow-ups (NOT in this branch)

- **D1 + old-chunk headers**: evaluation windows mixing pre-deploy chunks
  (headers without `event_ms`) with new chunks will hit `HoldoutRefusal`
  on the old headers once shortfalls clear. Fix belongs in D1
  (skip `header`/`gap` records in `read_records`) — flagged, not
  implemented (no evaluator changes allowed here). D1's forward clock
  starts at/after deploy, so post-deploy-only windows are unaffected.
- **Sidecar backfill (proposal only)**: funding settlements and daily
  klines are fully historical via REST. A backfill must land in a
  versioned sidecar dataset, never into sealed chunks, and needs a D1
  Store-adapter decision plus prereg review. Not implemented.
- **Deploy**: owner-only, `release/v1`, single restart, then verify a
  newly sealed chunk carries `funding_settlement` + `kline_1d` tokens and
  the silent-stream alert still fires on a deliberately silent stream.
