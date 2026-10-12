# Depth + trade-flow availability for runtime strategies (E-007 → Q-005 S5)

Owner: W2 (cloud-vega). Status: committed interface; shipped with E-007.
Consumers: Q-005 (`strategies/runtime.py` `MarketView.depth` / `MarketView.flow`),
manager (`app` bridge wiring).

## Verdict

**Depth and flow are AVAILABLE for S5**, under explicit sync/quality gating:

- `depth` MUST be `None` + reason whenever the symbol's book is unsynced
  (pre-snapshot, chain break, resync in flight, stale beyond tolerance).
- `flow` MUST be `None` + reason whenever the aggregation window is incomplete
  (trade-ID gap, missing book context if the feature needs it, halt interval).
- No microstructure is ever fabricated: every book/flow quantity derives only
  from observed venue fields, and missing inputs stay missing.

## Depth source (per symbol)

| Aspect | Value |
|---|---|
| Diff stream | `<sym>@depth@100ms` (full-book deltas, 100 ms batching) |
| Snapshot | REST `GET /fapi/v1/depth?symbol=&limit=` (default limit 1000) |
| Sync protocol | buffer diffs → snapshot → drop `u <= lastUpdateId` → first applied event must span `lastUpdateId+1` → strict `pu` chain; any break → resync (see `market_data/depth.py` `DepthBook`) |
| BBO cross-check | `<sym>@bookTicker` (independent `u`-sequenced top-of-book) |
| Persisted (E-007) | `depth_snapshots.jsonl`: `{symbol, last_update_id, bids, asks, rest_recv_ms, source:"binance-fapi-rest"}` — one record per installed snapshot; diffs + sync boundaries already in `events.jsonl` |
| Sync boundaries | resync requests, snapshot installs, and gap labels ride the event stream (`gap_kind`, venue `U/u/pu`); replay rebuilds the identical book from snapshot + chained diffs |

Book features computable while synced (top-N levels observed, never extrapolated):
best bid/ask + sizes, spread bps, depth notional within N levels per side,
bid/ask size imbalance at top K. Anything deeper than the observed snapshot
limit or outside the synced interval is unavailable, not zero-filled.

Reason strings (machine-readable prefix `depth:`): `depth:unsynced-no-snapshot`,
`depth:resync-in-flight`, `depth:chain-break`, `depth:stale-book`,
`depth:symbol-not-captured`.

## Trade-flow source (per symbol)

| Aspect | Value |
|---|---|
| Trade stream | `<sym>@aggTrade` with aggressor flag (`m` = buyer-is-maker), aggregate IDs (`a`, `f`, `l`), price/qty, trade time `T` |
| Signed aggregates | per 1 s causal window: buy/sell notional, buy/sell count, VWAP, trade count; `buyer_is_maker=false` ⇒ buy-side aggression |
| Gap detection | `last_id` jumps flag the spanned windows; flagged windows are `BarMissing`-equivalent for flow (kept, labeled, never interpolated) |
| BBO context | `bookTicker` gives quote sizes at trade time for spread-class features |
| Persisted | `events.jsonl` (normalized `aggTrade` records with `exchange_ts_ms`, `local_recv_ms`, `venue_seq`) + `bars1s.jsonl` (causal 1 s bars) |

Reason strings: `flow:trade-id-gap`, `flow:empty-window`, `flow:halt-interval`,
`flow:symbol-not-captured`.

## Timing, order, and quality sync

- Every record carries `exchange_ts_ms` (venue event time) AND `local_recv_ms`
  (receipt time); receipt order is preserved in the files and in replay
  (`arrival` order rebuilds byte-identical state; `exchange_ts` order is
  available for causal analysis).
- Bars are causal: a 1 s window closes only on a strictly later timestamp;
  nothing peeks past `now_utc`.
- Quality sync: collector stop reasons, disconnect/reconnect intervals, depth
  resyncs, and trade gaps are labeled in-stream, so strategy time and data
  quality share one timeline. A halt interval suppresses both depth and flow
  with reasons; terminal state never implies flat.

## Bridge API (what W1/manager code consumes)

`market_data/bridge.py` (E-007, stdlib-only; nautilus mapping is additive):

- `iter_market_stream(events_path, snapshots_path)` — yields normalized
  records in receipt order with attached sync state per symbol.
- `book_features(state, levels=10)` — synced-only book feature dict or
  `(None, reason)`.
- `flow_window(trades, window_start_ms)` — signed aggregates or `(None, reason)`.
- `to_nautilus_ticks(records, instrument_id)` — QuoteTick/TradeTick/
  OrderBookDelta objects for BacktestEngine replay and the live sandbox feed
  (requires the nautilus venv; pure mapping, no I/O).

Nautilus instrument baseline: `CryptoPerpetual` per USDT-perp symbol, venue
`BINANCE`, MARGIN/NETTING, maker 2 bps / taker 5 bps (Binance VIP0 defaults,
labeled; V-006 may tighten from live filters).

## Limits (do not design past these)

- 100 ms depth batching + REST snapshot latency: the synced book lags the
  matching engine by design; Sim fills cross the simulated book, not the
  venue's.
- diff streams carry only changed levels; full-book depth beyond the snapshot
  limit is unknown.
- mark/funding (`markPrice@1s`) feeds funding cash-flow modeling, not depth.
- Live paper path uses the Binance *data* client + sandbox *execution* client;
  no Binance live execution client is ever instantiated in paper mode.
