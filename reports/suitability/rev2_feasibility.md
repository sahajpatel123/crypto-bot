# REV2 historical-data feasibility audit (R7)

Branch `worker3/rev2-data` from `rev2/integration` (`006fca9`).
Audited live 2026-10-14. New files only; `table.md`/`table.json` untouched.

## Verdict: ten new days are NOT mandatory

Free, legally accessible sources already cover the trade, funding,
mark-1m, and kline families for any day since 2019. The ONLY families
missing for new days are top-of-book and reconstructible depth, which
have TWO adequate paths — a small vendor purchase OR a fresh
self-capture ($0, license-clean, exact channel match). The untouched
tick-evaluation leg (§6 DATA BLOCKED) can be unblocked either way;
no ten-day purchase is required to proceed.

## Per-family dataset support

| family | repo captures (5) | Binance Vision (free) | Tardis (vendor) |
|---|---|---|---|
| agg/raw trades | BTC+ETH, 30s–2h windows | aggTrades+trades daily/monthly, all symbols, ms exchange ts, 0 id breaks observed | trades CSV, exchange+local µs, 0.011% ids missing in sample |
| top-of-book | bookTicker real-time, same windows | NOT AVAILABLE (no bookTicker files) | book_ticker real-time (BTC 12.8M rows/day), exact gaps ≤4.1s in sample |
| depth | depth@100ms diffs + resyncs | bookDepth = 30s AGGREGATE bands (not reconstructible L2) | book_snapshot_25 @~17/s + incremental L2 (88.9M rows/day) + generated depthSnapshot |
| mark price | markPrice@1s | markPriceKlines 1m (NO 1s for um) + premium/index 1m | derivative_ticker ~1.3/s incl mark/index/last |
| funding | ABSENT everywhere | fundingRate monthly, perfect 8h cadence, 90 rows/mo | funding_rate + predicted + funding_ts in derivative_ticker |
| klines/filters | — | 1m (verified perfect); 1s NOT offered for um | n/a (tick vendor) |
| timestamps | exchange ms + local recv + mono ns | exchange ms only (bookDepth: second strings) | exchange + local µs (skew 5–74ms by feed) |
| license | own data | CC BY-NC-SA 4.0: research/personal-backtest OK; live/commercial needs enterprise license; attribution + share-alike | commercial subscription: internal business/research use; redistribution limited to Derived Data (cl. 9.2); AI/ML training/eval needs separate written agreement — owner must read before purchase |
| cost | $0 | $0 | Solo perpetuals $700/mo (cheapest observed tier); 20 TB/mo transfer; history 4y (yearly billing); monthly-billing depth unstated — verify at purchase |

## Source audit evidence (all observed, not claimed)

Binance Vision (`data.binance.vision`, um perpetuals), checksums verified:
- `aggTrades` daily BTCUSDT 2026-10-10: 3.9 MB zip, 307,839 rows,
  full-day span, id continuity ZERO breaks, max gap 12.4s, p50 0.27s.
- `fundingRate` monthly 2026-09: 924 B, 90 rows, exact 8.0h cadence.
- `bookDepth` daily: 553 KB, 34,560 rows = 12 percentage bands × 30s
  snapshots; second-resolution; aggregate metric, NOT a book.
- `klines` 1m monthly: 1.8 MB, exactly 43,200 rows, perfect 60s cadence.
- `markPriceKlines`/`premiumIndexKlines`/`indexPriceKlines` 1m: exist
  (200); `klines` 1s: 404 for um.

Tardis (`tardis.dev`, `binance-futures`), free samples 2024-04-01,
downloaded WITHOUT auth or payment (6 files, ~860 MB):
- Metadata API: BTC+ETH full 8 data types, 2019-11 → 2026-10-14.
- trades ETH: 3.89M rows, exact max gap 5.5s, ids 99.989% continuous
  (423 missing / 350 events — consistent with the >99.9% claim).
- book_ticker BTC/ETH: 12.8M/9.4M rows, exact gaps 2.0/4.1s.
- book_snapshot_25 ETH: 1.46M rows (~17/s), 25 levels/side.
- derivative_ticker ETH: 111,932 rows; funding_rate on all rows with
  4 settlement timestamps (8h grid); predicted empty that day.
- incremental_book_L2 ETH: 88.9M rows/day, is_snapshot flags present.
- Gaps in samples are inter-message spacing; CSVs carry no venue
  sequence for book feeds, so gap-vs-quiet is indistinguishable there.

## Purchase choice (ONE, smallest adequate — owner decision, never auto-spend)

NOTHING is blocked: the audit completed on free material. If the
round needs vendor book/depth for new days:

- Choice: Tardis Solo (perpetuals), 1 month, $700/mo public pricing.
- Coverage: binance-futures CSVs, BTCUSDT+ETHUSDT, data types
  trades + book_ticker + book_snapshot_25 + derivative_ticker, for
  the needed days (≈0.5 GB gz/day for both symbols — far under the
  20 TB transfer limit; recent days expected in any billing tier,
  confirm at checkout).
- License: commercial subscription; see AI/ML + redistribution flags
  above — owner reads the ToS before paying.
- Resume after owner approval (no spend happens here):
  1. subscribe at tardis.dev, create 1 API key (Solo includes 1);
  2. `pip install tardis-dev`, download per-day CSVs for the two
     symbols × four data types above;
  3. re-run this audit's continuity checks (id continuity, exact max
     gap, funding grid) on the PAID days before use — samples do not
     certify paid-day completeness.
- Free alternative (no purchase): fresh self-capture on new days with
  the existing capture tooling — $0, own-data license, exact
  aggTrade/bookTicker/depth@100ms/markPrice@1s channel match, plus
  local timestamps the vendors approximate differently. This is the
  recommended path for the untouched tick-evaluation leg unless the
  round needs pre-October history (self-capture cannot time-travel).

## Reproducible bounded replay slices

`replay_slices.json`: 4 hash-pinned slices over existing captures
(139k / 181k / 1.13M / 13.8k events). Each entry carries symbols,
UTC window, seq range, event count, sha256, gap-row count, and the
exact byte-reproducing extract command. Cross-check: the full
cap-30min slice hash matches the manifest's recorded events sha256,
and its 1 injected-gap row is the designed chaos gap.

## What is NOT claimed

- Ten new days were not bought, downloaded, or declared necessary.
- Free-sample audits certify FORMAT and continuity method only; paid
  Tardis days need re-audit on arrival (resume step 3 above).
- Vision data must not flow into live/prod or commercial use (NC
  license); paper/research use only without an enterprise license.
