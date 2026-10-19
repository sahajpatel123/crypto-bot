# Binance Vision (UM Futures) — Data Inventory

Measured inventory of `data.binance.vision` USD-M futures public data for the edge-sprint pull plan.
**Every number below comes from tool output** (S3 listings + 4 tiny probes, ~7 KB downloaded total).
No bulk downloads were performed.

- Generator: `tools/vision_inventory.py` (stdlib only: `urllib`, `xml.etree`, `json`, `argparse`, + `zipfile`/`io` for probes; ~4 req/s, retry/backoff, 30 s timeout)
- Command: `cd /Users/sahajpatel/Code/cryto-bot-edge && /Users/sahajpatel/Code/cryto-bot/.venv/bin/python tools/vision_inventory.py --out /tmp/vision-inventory.json`
- Raw JSON cache: `/tmp/vision-inventory.json` (+ `/tmp/vision-supplement.json` for daily-only datasets `metrics`/`bookDepth`, same S3 API, same politeness)
- Generated: 2026-10-18T09:38 UTC; full run 1844.6 s (mostly ~4 req/s delimiter listings). Cadence boundary observed: monthly leg ends **2026-09**, daily leg ends **2026-10-17**.

## 1. Dataset table (UM futures)

| Dataset | Monthly symbols | Daily symbols | BTC range observed | Notes |
|---|---|---|---|---|
| klines | 1056 | 1066 | monthly 2020-01 → 2026-09 (81 files); daily 2019-12-31 → 2026-10-17 (2483 files) | Full per-symbol start/end measured for 1d/1h/1m (§3) |
| markPriceKlines | 1039 | 1054 | monthly 2020-01 → 2026-09 (BTC all-interval: 1098 files, 155,417,960 B) | Same 15-interval layout as klines |
| premiumIndexKlines | 982 | 996 | monthly 2020-01 → 2026-09 (BTC all-interval: 1098 files, 115,708,879 B) | Same 15-interval layout |
| indexPriceKlines | 979 | 993 | monthly 2020-01 → 2026-09 (BTC all-interval: 1097 files, 166,797,234 B) | Same 15-interval layout |
| fundingRate | 988 | — (no daily leg) | monthly 2020-01 → 2026-09 (81 files, 71,993 B) | Monthly only. Columns §5 |
| aggTrades | 1044 | 1049 | monthly 2020-01 → 2026-09 (82 files, 44,896,516,031 B ≈ 44.9 GB for BTC alone) | Huge; newest file uses sharded `part-*.zip` naming |
| trades | 1044 | 1052 | monthly 2019-09 → 2026-09 (85 files, 70,158,811,164 B ≈ 70.2 GB for BTC alone) | Earliest UM data seen (2019-09, predates klines) |
| bookTicker | 315 | 315 | monthly 2023-05 → 2024-04 (12 files, 53,552,474,764 B); daily 2023-05-16 → 2024-03-30 (320 files, 52,578,851,529 B) | **Discontinued ~2024-04** — all 10 sampled symbols end 2024-04/2024-03-30 |
| bookDepth | — (no monthly leg) | 1008 | daily 2023-01-01 → 2026-10-17 (1382 files, 649,865,886 B ≈ 650 MB for BTC) | Daily only; files directly under symbol |
| metrics | — (no monthly leg) | 1038 | daily 2020-09-01 → 2026-10-17 (2238 files, 25,893,120 B ≈ 25.9 MB for BTC) | Daily only; OI + L/S ratios. Columns §5 |

Not present: `BVOLIndex` (neither monthly nor daily), monthly `metrics`, monthly `bookDepth`, daily `fundingRate`.
Monthly cadence set: `aggTrades, bookTicker, fundingRate, indexPriceKlines, klines, markPriceKlines, premiumIndexKlines, trades` (8).
Daily cadence set: monthly 8 minus `fundingRate`, plus `bookDepth, metrics` (9).

## 2. Klines interval table (monthly, all symbols)

All 1056 monthly klines symbols carry the 12 core intervals. `1w`/`3d`/`1mo` are partial; **`1M` does not exist** (`1mo` is the monthly-interval name, 280 symbols).

| Interval | Symbols (of 1056) | Monthly zip bytes, all symbols |
|---|---|---|
| 1m | 1056 | 32,172,676,339 (≈ 32.2 GB) |
| 3m | 1056 | 11,925,907,476 (≈ 11.9 GB) |
| 5m | 1056 | 7,264,803,292 (≈ 7.3 GB) |
| 15m | 1056 | 2,625,653,882 (≈ 2.6 GB) |
| 30m | 1056 | 1,367,042,135 (≈ 1.4 GB) |
| 1h | 1056 | 712,183,446 (≈ 0.71 GB) |
| 2h | 1056 | 375,036,511 |
| 4h | 1056 | 198,998,184 |
| 6h | 1056 | 137,420,368 |
| 8h | 1056 | 106,000,619 |
| 12h | 1056 | 74,278,332 |
| 1d | 1056 | 41,717,628 |
| 3d | 346 | 4,395,633 |
| 1w | 346 | 2,652,785 |
| 1mo | 280 | 1,690,302 |

Requested-interval check: 1m ✓, 5m ✓, 15m ✓, 1h ✓, 4h ✓, 1d ✓ (all 1056/1056); 1w partial (346/1056); 1M ✗ absent (use `1mo`, 280/1056).
mark/premium/index BTCUSDT expose the identical 15-interval list.

## 3. Symbol start/end summary (klines monthly)

Total: **1056 symbols** (1d, 1h, 1m each cover all 1056; 24,443 monthly zip files per interval).
Daily leg has 1066 symbols — 10 daily-only names with no monthly file yet, all new listings:
`AKAMUSDT, CTUSDT, MCDUSDT, MDTUSDTSETTLED, MSTUUSDT, RDWUSDT, SNPSUSDT, USDEXUSDT, VKTXUSDT, ZCSHUSDT`.

Oldest 10 by 1d start (all start 2020-01): `ADAUSDT, BCHUSDT, BTCUSDT, EOSUSDT, ETCUSDT, ETHUSDT, LINKUSDT, LTCUSDT, TRXUSDT, XLMUSDT`.
Newest 10 by 1d start (all start 2026-09, 1 file each): `哈基米USDT, ZSUSDT, XOMUSDT, USDBRLUSDT, UNHUSDT, TWSTUSDT, TSLLUSDT, TEAMUSDT, SECZUSDT, RUMUSDT` (includes TradFi trackers and one CJK-named perp).

End-date distribution (1d): 920/1056 symbols end 2026-09 (current); 81 ended before 2024; daily files extend beyond the last monthly file for 922/1056 symbols (the 134 non-extending are stale/delisted/settled names, e.g. `EOSUSDT, LUNAUSDT, BZRXUSDT, MATICUSDT, SRMUSDT, HNTUSDT`).

## 4. Delisted-symbol evidence (vision retains history)

| Symbol | 1d monthly range | Files | Note |
|---|---|---|---|
| LENDUSDT | 2020-07 → 2020-11 | 5 | Delisted 2020 (Aave migration); still listed |
| LUNAUSDT | 2021-01 → 2022-05 | 17 | Terra collapse May-2022; frozen at crash month |
| ANCUSDT | 2022-03 → 2022-05 | 3 | Terra-ecosystem delist, same freeze point |
| BTTUSDT (old) | 2021-04 → 2022-01 | 10 | Pre-redenomination contract |
| BZRXUSDT | 2020-09 → 2021-12 | 16 | Delisted 2021 |
| EOSUSDT | 2020-01 → 2025-05 | 65 | Ends 2025-05 (Vaulta swap era) |
| BTCUSDT_210326 / ETHUSDT_210326 | 2021-02 → 2021-03 | 2 each | Expired quarterly futures, retained |
| BTCBUSD_210129 / BTCBUSD_210226 | 2021-01 → 2021-01 | 1 each | Expired BUSD-margined quarterlies |

Related: `USTCUSDT` exists (2023-11 → 2026-09, 35 files); `1000LUNCUSDT` and `LUNA2USDT` exist (2022-09 → 2026-09). `FTTUSDT` klines run to 2026-09 (last monthly file current).

## 5. Observed column formats (tiny probes, <5 MB budget; used ~7 KB)

- **fundingRate** (`BTCUSDT-fundingRate-2023-11.csv`, 696 B zip): `calc_time,funding_interval_hours,last_funding_rate`, e.g. `1698796800000,8,0.00010000` (8-hourly rows).
- **metrics** (`BTCUSDT-metrics-2021-06-22.csv`, 5456 B zip): `create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio`, e.g. `2021-06-22 00:00:00,BTCUSDT,50992.83…,1612196410.82…,2.02087449,1.09736304,1.98130866,1.21439472`. So: open interest (+notional) ✓, top-trader L/S (count + position) ✓, global account L/S ✓, taker buy/sell volume ratio ✓ — one row per 5 min (288 rows/day implied by ~11 KB/day zips).
- **klines**: 12-column format per task brief (not re-probed; Range-probe confirmed zip magic `504b0304`).
- **Checksum**: every `.zip` has a sibling `.zip.CHECKSUM` (1:1 in all samples, e.g. BTC 1d monthly 81/81), content `"<sha256>  <filename>\n"` (observed 89 B: `83f80bb8…8268  BTCUSDT-1d-2020-01.zip`).

## 6. Spot leg (basis work)

Available. `data/spot/monthly/` datasets: `aggTrades, klines, trades`. `data/spot/monthly/klines/BTCUSDT/1d/`: 110 files, 237,793 B, 2017-08 → 2026-09. `ETHUSDT/1d`: 110 files, 227,278 B, 2017-08 → 2026-09. BTC spot intervals include `1s` plus the same 15 UM names. Spot history predates UM by ~2.5 years — basis series can start 2020-01 (UM-bound).

## 7. URL patterns (exact, verified)

- Listing: `https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?list-type=2&prefix=<PREFIX>&delimiter=/&max-keys=1000` (+ `&continuation-token=` on truncation; `&start-after=` supported)
- Klines monthly: `https://data.binance.vision/data/futures/um/monthly/klines/<SYM>/<iv>/<SYM>-<iv>-YYYY-MM.zip`
- Klines daily: `https://data.binance.vision/data/futures/um/daily/klines/<SYM>/<iv>/<SYM>-<iv>-YYYY-MM-DD.zip`
- Mark/premium/index: same shape under `monthly|daily/markPriceKlines|premiumIndexKlines|indexPriceKlines/`
- Funding: `https://data.binance.vision/data/futures/um/monthly/fundingRate/<SYM>/<SYM>-fundingRate-YYYY-MM.zip` (monthly only)
- Metrics: `https://data.binance.vision/data/futures/um/daily/metrics/<SYM>/<SYM>-metrics-YYYY-MM-DD.zip` (daily only, single `metrics` file per symbol-day)
- bookDepth: `https://data.binance.vision/data/futures/um/daily/bookDepth/<SYM>/<SYM>-bookDepth-YYYY-MM-DD.zip` (daily only)
- Spot: `https://data.binance.vision/data/spot/monthly/klines/<SYM>/<iv>/<SYM>-<iv>-YYYY-MM.zip`
- Checksum: append `.CHECKSUM` to any file URL.
- Caveat: recent aggTrades months add sharded keys like `data/futures/um/monthly/aggTrades/BTCUSDT/part-00000-0fae7358-…-c000.zip` alongside the classic `<SYM>-aggTrades-YYYY-MM.zip` name — downloaders must list rather than assume filenames.

## 8. Size estimates for the planned pull (zipped bytes on vision)

| Leg | Bytes (zipped) | Files | Method |
|---|---|---|---|
| klines 1d, all 1056 syms, monthly | 41,717,628 (≈ 42 MB) | 24,443 | Exact (summed per-symbol listings) |
| klines 1h, all 1056 syms, monthly | 712,183,446 (≈ 712 MB) | 24,443 | Exact |
| **klines 1h+1d subtotal** | **753,901,074 (≈ 0.75 GB)** | 48,886 | Exact |
| klines 1m, top-20 syms, monthly | 2,572,226,426 (≈ 2.57 GB) | 1,605 | Exact (top-20 by 1d monthly bytes: BTC ETH XRP BCH LINK LTC BNB ETC VET ADA ATOM IOST XLM XMR ZEC TRX DOGE DASH NEO ONT) |
| fundingRate, all 988 syms, monthly | 32,909,193 (≈ 33 MB) | — | Est: mean(10-symbol sample incl BTC/ETH) × 988 |
| markPriceKlines 1d+1h, all syms, monthly | 442,488,401 (≈ 0.44 GB) | — | Est: BTC mark/klines byte ratio × klines 1d+1h exact total |
| premiumIndexKlines 1d+1h, all syms, monthly | 329,001,228 (≈ 0.33 GB) | — | Est: same BTC-ratio method |
| metrics, all 1038 syms, daily | 9,665,244,099 (≈ 9.7 GB) | — | Est: mean(10-symbol sample) × 1038 (BTC 25.9 MB / 2238 files) |
| **Planned-pull total** | **≈ 13.8 GB zipped** | — | Sum of above |
| Daily increment (all syms, ~1050) | ≈ 0.3 KB/sym 1d, 1.5 KB/sym 1h, 62 KB/sym 1m, ~11 KB/sym metrics | ~1 file/sym/day/leg | From BTC daily sizes (1d 811 KB/2483 f, 1h 3.8 MB/2483 f, 1m 155 MB/2483 f) |

Out of scope (measured for context, do NOT pull): aggTrades monthly ≈ 9.9 TB est (BTC 44.9 GB), trades monthly ≈ 17.2 TB est (BTC 70.2 GB), bookTicker ≈ 3.7 TB est but frozen at 2024-04, bookDepth daily ≈ 0.66 TB est (BTC/ETH/DOGE ≈ 650/679/656 MB each).
