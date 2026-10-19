# S5 availability ruling — UNAVAILABLE (Worker 1, Q-004)

Ruling: S5 (order-flow continuation) stays EXPLICITLY UNAVAILABLE. It has
no spec, no baseline, no fixtures, and no experiment. The earlier S5
micro-imbalance draft (`S5.md`) is retained as a hypothesis note only and
is not a buildable spec. No synthetic-flow substitution: the synthetic
`buy_frac` proxy used by S1-F/S2-F must not stand in for real order flow
in S5 (directive Sec 5).

## Synchronized-data inventory (main `ea4fa9d`, read-only inspection)

| Required for S5 | Available | Evidence |
|---|---|---|
| Trade-level buyer/seller flow synced to bars | NO | no aggTrades channel, no side-split volume anywhere |
| Order-book depth synced to bars | NO | no depth snapshots or book tooling |
| 1-second (or finer) causal bars | NO | finest observed grid is 1-minute klines |
| Sustained capture with gap flags | PARTIAL | E-006 `running`, but capture tool offers klines only |

Observed on disk: `data/observed/klines_BTCUSDT_1m_60_*` (60 one-minute
OHLCV bars, no side split) + `discovery_*.json` (symbol metadata).
`tools/capture_public.py` supports `discover` + kline `capture` only.
`src/cryptobot/market_data/` has capabilities/discovery/recorder/replayer
— no flow or depth modules.

## Conditions to lift this ruling

1. A trade-flow or depth capture channel lands with exchange timestamps.
2. Bars at 1s (or finer) carry causal, synchronized flow features with
   documented gap/quality flags.
3. Replay coverage exists for at least one full evaluation window.

Until then, any S5 implementation task must be refused or redirected.
Re-check this ruling when E-006 completes or the inventory changes.
