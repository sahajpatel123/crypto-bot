# Capture report cap-30min

Window (UTC): 2026-10-11T21:43:58.688145+00:00..2026-10-11T22:13:59.301922+00:00 — stop: duration-reached
Symbols: BTCUSDT, ETHUSDT (top-2 by 24h quoteVolume among 525 TRADING USDT-perp symbols from live discovery (recomputed per run))
Events: 1129445 total, 0 malformed; dup 0, ooo 0; gaps {'natural': 0, 'injected': 1}; disconnects {'natural': 0, 'injected': 1} (1 reconnects); depth resyncs 0.

## event_age_ms (n=1129445, sampled=20000)

exchange event time -> local wall-clock receipt (uncorrected for clock offset; see clock_offset_start/end for the measured offset and RTT uncertainty). Includes venue fan-out + network transit; NOT order latency.

p50 74 ms; p95 132 ms; p99 576 ms; max 1232 ms.
Method: bounded uniform reservoir (Vitter R, cap 20000); nearest-rank percentiles.

## decision_latency_ms (n=1129445, sampled=20000)

local receipt -> finished processing one event, monotonic clock (parse + book/bar update + write buffering). Local pipeline cost only.

p50 0.021375 ms; p95 0.143334 ms; p99 0.406917 ms; max 2.116083 ms.
Method: bounded uniform reservoir (Vitter R, cap 20000); nearest-rank percentiles.

## Claim boundary

REST RTT, event age, and decision latency are distinguished above. NOTHING in this report measures order execution/ack latency, which a public-only collector cannot observe.
