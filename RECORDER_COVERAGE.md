# Recorder coverage versus Family A

The recorder subscribes to `aggTrade`, `bookTicker`, `depth@100ms`,
`markPrice@1s`, and `forceOrder` for BTCUSDT and ETHUSDT
(`BINANCE_STREAMS` in `src/cryptobot/market_data/live_recorder.py`).

| Hypothesis | Needs | Captured now |
|---|---|---|
| H1 | top-of-book L2 depth | `depth@100ms` and `bookTicker` |
| H2 | 5-minute bars; book-walk if depth exists | trades and depth |
| H3 | funding with position timing | `markPrice` funding field, plus REST premium/funding polls |
| H4 | Binance plus Bybit and OKX books | Binance only |
| H5 | liquidation prints plus depth | `forceOrder` and depth |
| H6 | a filter on H2 and H3 | the same Binance streams |

H4's other venues are not enabled. Measured recorder use is about
58 MB/hour and about 12 days of disk before the guard
(`RECORDER_COSTS.md`), while adjudication is 90 days out. Adding
venues would spend that disk. D-046 records this as
IMPRACTICAL-BY-RESOURCE. The H4 prereg was not edited.

## Emulator coverage (never evidence)

`cryptobot emulator drill` exercises the same stream set against
MockEx over real sockets: combined `aggTrade`, `bookTicker`,
`depth@100ms`, `markPrice@1s`, `forceOrder`, plus the private user
stream and listenKey expiry. A recorder smoke test feeds those
EMULATED frames through the real recorder into a chunk stamped
SYNTHETIC. Neither drill nor smoke can satisfy `gate`'s demo-drill
or any verdict requirement.
