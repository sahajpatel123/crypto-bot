# Archive freeze — crypto-bot market-data recorder

**Status: FROZEN and immutable.** The owner stopped market-data recording at
**2026-10-25T12:41:18Z**. From that moment the archive is the dataset of record and is
read-only: no chunk, no manifest entry and no manifest byte may be added, moved,
rewritten or deleted.

This document and [`archive_frozen_manifest.json`](archive_frozen_manifest.json) are the
freeze record. The manifest copy here is **byte-exact** (344,678 bytes, sha256
`a9acf666…56224`) so the integrity chain survives the machine that holds the chunks.

| Fact | Value |
|---|---|
| Archive root | `~/Code/cryto-bot-edge/data/recorder` (chunks in `chunks/`) |
| Publisher of the frozen bytes | `launchd` label `com.cryptobot.recorder`, running `caffeinate -is nice -n 10 ~/Code/cryto-bot/.venv/bin/python -m cryptobot.cli recorder start --out ~/Code/cryto-bot-edge/data/recorder --symbols BTCUSDT,ETHUSDT --chunk-seconds 300 --disk-budget-mb 4096`, cwd `~/Code/cryto-bot-edge`, `PYTHONPATH=~/.cryptobot/netshim:~/Code/cryto-bot-edge/src`, code = edge checkout `release/v1` @ `ef744a2` |
| Manifest | `cryptobot-chunk-manifest/1`, 473 entries, 344,678 bytes, sha256 `a9acf6662a61349dbb145a711bfa8d3f4a4aaf754ccdd196269311c86a656224` |
| Manifest `created_utc` / last seal | `2026-10-18T21:37:56.680273+00:00` / `2026-10-25T12:35:13.242628+00:00` |
| Chain head | `8001aad733d4a8e483e6e680fd690b2bd0b00f3f28c4fa6465c4842f6cac0c05` |
| Venue / symbols | `binance-usdm` (USD-M futures, public streams + REST), `BTCUSDT` and `ETHUSDT` |
| Chunk cadence | one `jsonl.gz` chunk per **300 s wall clock**, sealed with its own sha256 into the hash-chained manifest |
| Chunk format | `cryptobot-recorder/2` (`input_class` `observed-public`, data `class` `DEV`) |
| Inventory | **473 chunks**, **98,371,791 records**, **2,577,286,788 bytes** (2.58 GB / 2.40 GiB) |
| Time range | `2026-10-18T21:37:56.681Z` → `2026-10-25T12:35:13.240Z` (158.9 h of wall clock) |
| Actually recorded | **144,659 s = 40.18 h** of chunk windows = **25.3 %** of that span |

Recording state at freeze (verified 2026-10-25T12:59Z, read-only): launchd job
`com.cryptobot.recorder` is not loaded and is `disabled`; `refresh`, `c2fwd`,
`watchdog`, `autopilot` and `adjudicate` are `disabled`; `~/.cryptobot/STOP` exists in
the recorder directory (`Owner stopped market-data recording 2026-10-25T12:41:18Z. Do
not restart. Archive frozen; work from existing data.`); no recorder process is running
(`recorder.pid` still names pid 1169, which no longer exists).

**One supervision caveat:** the launchd job `com.cryptobot.guard` is *still loaded and
runs every 300 s*. Its log shows it honours the STOP file
(`"stopped by owner (STOP file present); not restarting"`), so it will not restart the
recorder while `STOP` exists — but the archive's immutability rests on that file. The
same guard log shows that at `2026-10-25T12:40:22Z`, before the STOP file was written,
it did issue `launchctl bootstrap` + `kickstart` for `com.cryptobot.recorder`. Anything
that removes `STOP` will let the guard re-create this job and append chunks.

---

## 1. What was recorded, and what each stream is

Every record is one JSON line with `type`, `venue`, and (for market records) `symbol` and
`event_ms` (exchange event time, ms). Stream presence is per chunk as written into the
manifest `streams` list.

| `type` / stream | What it is | Cadence / volume | Chunks |
|---|---|---|---|
| `header` | per-chunk metadata (`chunk`, `format`, `started_utc`, `symbols`, `venues`, `input_class`) | 1 per chunk | 473 |
| `book_ticker` — `btcusdt@bookTicker`, `ethusdt@bookTicker` | top of book: best `bid`/`bid_qty`, `ask`/`ask_qty`, `update_id`, `event_ms` | push, bursts of hundreds per second (2,307,724 records in the 17-chunk trade window alone ≈ 452/s) | 430 |
| `depth` — `btcusdt@depth@100ms`, `ethusdt@depth@100ms` | L2 diff updates: `first_id`/`final_id`/`prev_final_id`, `bids`/`asks` level arrays | push, 100 ms | 430 |
| `depth_snapshot` | REST `depth?limit=1000`: full book snapshot, 1000 levels per side + `last_update_id` | ~30 s | 471 |
| `open_interest` | REST `openInterest` for the symbol | ~30 s | 472 |
| `premium_index` | REST premium index: `markPrice`, `indexPrice`, `lastFundingRate`, `nextFundingTime` | ~30 s | 472 |
| `trade_agg` — `btcusdt@trade`, `ethusdt@trade` | **1-second trade bucket**, not raw prints: `bucket_ms`, `trades`, `buy_qty`, `sell_qty`, `notional`, `vwap`, `first_trade_id`, `last_trade_id`, `gap`, `out_of_order` | 1 s buckets from `aggTrade` | **17** |
| `mark` (`markPrice@1s`), `liquidation` (`forceOrder`) | requested by the code's stream list; **zero bytes ever delivered** | — | **0** |

Absent from all 473 chunks: `markPrice@1s` pushes (mark price exists only as the 30 s
REST `premium_index` poll), and `forceOrder` liquidations — the stream that hypothesis
H5 needs. Bybit/OKX (H4) plugins were never enabled, so the archive is single-venue.

## 2. Why trade data covers only the last 17 chunks

* The archive's trade coverage is chunks **449–465**: `2026-10-25T09:59:57Z` →
  `2026-10-25T11:55:55Z` (1 h 56 min), 9,144 one-second buckets carrying **219,169
  underlying aggTrades** with aggregate trade-id range `8,202,807,235` →
  `8,894,348,592` and 549,752,143 notional (buy 70,198.542 / sell 52,284.939, summed
  base units over both symbols — the sum mixes BTC and ETH, so it is a volume check, not
  a market statistic), 2,414,847 records, 70,623,732 bytes.
* Trade recording is a **code change, not a change of heart**: `BINANCE_STREAMS` became
  `("trade", "bookTicker", "depth@100ms")` with 1 s bucketing in the edge checkout's
  `fbce1ab fix(recorder): record trade flow, and fail loudly when a stream is silent
  (#33)` (plus `ecd7467`, per-stream silence alerts). The live process only picked it up
  when it restarted into chunk 449 — the chunk boundary at 09:59:57Z after a 90 s quiet
  gap.
* Before that restart the running process subscribed to `aggTrade`, `markPrice@1s` and
  `forceOrder` and received **no bytes at all** for them; only `bookTicker`, `depth` and
  the REST pollers ever produced records. That is why the first 449 chunks have no trade
  prints even though the stream was requested.
* After `2026-10-25T11:55:55Z` the websocket streams went silent again (chunks 466–472
  contain only the REST pollers), so trade recording ends 46 minutes before the owner's
  stop. The archive therefore holds trade flow for **17 chunks out of 473 (3.6 %)** and
  never at raw-print resolution.

## 3. Holes

### 3.1 Inter-chunk holes (no chunk covers the interval)

| # | From chunk | To chunk | Quiet from (UTC) | Quiet to (UTC) | Duration |
|---|---|---|---|---|---|
| 1 | 000187 | 000188 | 2026-10-19T13:54:13Z | 2026-10-19T13:56:24Z | 2.2 min |
| 2 | 000211 | 000212 | 2026-10-19T15:58:37Z | 2026-10-19T15:59:39Z | 1.0 min |
| 3 | 000394 | 000395 | 2026-10-20T07:14:46Z | 2026-10-25T05:05:38Z | **117.85 h (4.91 d)** |
| 4 | 000395 | 000396 | 2026-10-25T05:13:09Z | 2026-10-25T05:33:20Z | 20.2 min |
| 5 | 000400 | 000401 | 2026-10-25T05:58:20Z | 2026-10-25T05:58:22Z | 1.8 s |
| 6 | 000403 | 000404 | 2026-10-25T06:13:22Z | 2026-10-25T06:13:24Z | 1.9 s |
| 7 | 000448 | 000449 | 2026-10-25T09:58:26Z | 2026-10-25T09:59:57Z | 1.5 min |
| 8 | 000457 | 000458 | 2026-10-25T10:44:58Z | 2026-10-25T11:15:13Z | 30.3 min |
| 9 | 000464 | 000465 | 2026-10-25T11:50:14Z | 2026-10-25T11:50:15Z | 1.3 s |

Total unrecorded inter-chunk time: 118.77 h, of which 117.85 h is hole 3.

Attribution, from evidence that survives on the machine:

* **Hole 3 (4.91 d)** — after chunk 394 sealed at `2026-10-20T07:16:38Z` nothing was
  written for 4.91 days; recording resumed cold at `2026-10-25T05:05:38Z` with a chunk
  that holds 2 records. The cause is **not recoverable from the surviving logs**: the
  guard's own log begins only at `2026-10-25T05:56:58Z` (so nothing was supervising the
  recorder during the outage) and `~/Library/Logs/cryptobot/recorder.log` is empty from
  19 Oct. Treat it as an unattributed stop, not as a network gap.
* **Holes 7, 8** — crash/reset boundaries on 25 Oct (see §5): the recorder died mid-chunk,
  a fresh chunk was opened after the restart.
* **Holes 4, 5, 6** — 25 Oct restart cycles (05:05 cold start, two sub-2 s reconnects).
* **Holes 1, 2** — 19 Oct reconnect cycles.

### 3.2 Stream-level holes inside sealed chunks

These intervals *are* covered by chunks but contain only REST records, so the tick
streams (`bookTicker`, `depth`, `trade`) are absent for them:

| Chunks | Quiet from (UTC) | Quiet to (UTC) | Duration | Records present |
|---|---|---|---|---|
| 165–187 (23 chunks) | 2026-10-19T11:37:07Z | 2026-10-19T13:54:13Z | **137.1 min** | 689 |
| 200–211 (12 chunks) | 2026-10-19T14:56:57Z | 2026-10-19T15:58:37Z | **61.7 min** | 372 |
| 395 (1 chunk) | 2026-10-25T05:05:38Z | 2026-10-25T05:13:09Z | 7.5 min | 2 |
| 466–472 (7 chunks) | 2026-10-25T11:55:55Z | 2026-10-25T12:35:13Z | **39.3 min** | 204 |

42 of the 473 chunks (8.9 %) are REST-only. Together with holes 1–9 this means no
top-of-book, no L2 diff and no trade flow for **~4.9 days + ~4.0 h** of the nominal
week, and the last 39 minutes of the archive hold funding/OI/book snapshots only.

### 3.3 Chunk cadence irregularities

The nominal cadence held: 427 of 473 chunks are 300.0 s (±0.5 s). 32 run 301–325 s and
11 run 333–360 s (the seal clock follows the last record written). Three are markedly
longer: chunk 164 (1,146 s), 165 (1,230 s) and 395 (451 s), where the writer tolerated a
stalled tick stream before rotating. Manifest `gaps` is `0` for every entry (queue
overflow was never hit), and no chunk was sealed later than 0.27 s after its last record
— so `first_ms`/`last_ms` are trustworthy boundaries.

## 4. What the pipeline did **not** record

Consumers of this dataset of record must not assume any of the following exists:

1. **Raw trade prints.** Only 1 s aggregates (`trade_agg`), only for chunks 449–465,
   only first/last aggregate-trade id per bucket — no per-trade id, price, size or maker
   side, so no trade-level microstructure, no trade-sign classification, no per-trade
   slippage study.
2. **`markPrice@1s` pushes.** Mark/index price and funding exist only through the 30 s
   REST `premium_index` poll (10 samples per 5 min chunk); there is no 1 s mark path and
   no funding-rate event history beyond those polls.
3. **`forceOrder` liquidations.** Zero records in all 473 chunks, so liquidation-driven
   hypotheses (H5) have no data at all.
4. **A second venue.** Bybit/OKX plugins were never enabled (H4 has no data); the archive
   is `binance-usdm` only.
5. **Symbols other than BTCUSDT and ETHUSDT**, and no other contract types.
6. **Anything private.** No user-data stream, no orders, no fills, no balances, no keys —
   the recorder is public-market only (`input_class` `observed-public`).
7. **Continuous top-of-book.** 42 REST-only chunks plus the holes above: no continuous
   book, so any book-derived series must be gap-aware and must not interpolate across
   §3.1/§3.2.
8. **The hole windows themselves.** Chunk 458's window `10:44:58Z→11:15:13Z` and hole 4's
   `05:13:09Z→05:33:20Z` are only partially recoverable from *unregistered* partial files
   (§5), which are not part of the frozen dataset.

## 5. Unregistered files on disk (not in the manifest)

`sha256sum` over `chunks/*.jsonl.gz` found **479 files on disk for 473 manifest entries**.
Exactly **6 files are not registered**, total **4,079,445 bytes** (3.9 MiB):

| File | Bytes | mtime (UTC) | gzip | Records | Internal record range (UTC) | Content |
|---|---|---|---|---|---|---|
| `rec-000396-20261025T051309Z.jsonl.gz` | 32,003 | 2026-10-25T05:14:21Z | **truncated** (no EOS marker) | 8 | 05:13:09.550 → 05:14:21.239 | header, REST pollers |
| `rec-000401-20261025T055820Z.jsonl.gz` | 8,542 | 2026-10-25T05:58:21Z | **truncated** | 200 | 05:58:20.689 → 05:58:21.641 | `bookTicker`, `depth` |
| `rec-000404-20261025T061322Z.jsonl.gz` | 0 | 2026-10-25T06:13:22Z | empty, 0 records | 0 | — | nothing |
| `rec-000449-20261025T095826Z.jsonl.gz` | 725,608 | 2026-10-25T09:59:56Z | **truncated** | 18,600 | 09:58:26.934 → 09:59:56.615 | `bookTicker`, `depth`, REST pollers |
| `rec-000458-20261025T104458Z.jsonl.gz` | 3,252,123 | 2026-10-25T10:47:48Z | **truncated** | 115,800 | 10:44:56.000 → 10:47:48.881 | `bookTicker`, `depth`, `trade_agg` |
| `rec-000473-20261025T123513Z.jsonl.gz` | 61,169 | 2026-10-25T12:38:09Z | **truncated** | 18 | 12:35:15.482 → 12:38:09.442 | header, REST pollers |

What they are: **crash residue.** Each is a chunk the writer had opened but never sealed.
The recorder derives the next chunk index from `len(manifest.entries)`, so after the
crash it opened a *new* file with the same index — e.g. the registered
`rec-000396-20261025T053320Z` (sealed, 5,345,890 bytes) supersedes the orphan
`rec-000396-20261025T051309Z`. Five orphans therefore share a chunk index with a sealed
successor; only `rec-000473-…` (index 473) is the chunk that was in flight when the owner
stopped recording, and it is the only one with no sealed counterpart.

Why they exist, from the guard's log: free space fell to **130 MB** at
`2026-10-25T11:02Z–11:07Z`; `recorder.err` records an
`OSError: [Errno 28] No space left on device` while writing `heartbeat.json`; the writer
died at `10:47:48Z` mid-chunk (orphan `458`), the machine rebooted (uptime 1 h 52 m at
12:59Z; the guard's recorder pid changed 71989 → 1169 at `11:15:13Z`), and recording
resumed into registered chunk 458 at `11:15:13Z`.

**They are not dataset of record.** They are unsealed, truncated, absent from the
hash chain and excluded from every count above. They are deliberately left untouched
(deleting or moving them would be an archive mutation). If anyone ever needs their
records, treat them as untrusted salvage: partial gzip streams, no seal time, no chain
link, and overlapping the holes in §3.1.

Nothing in the manifest is missing from disk: 473 registrations ↔ 473 sealed files, chunk
indices `000000`–`000472`, contiguous, no duplicates.

## 6. Integrity results

All checks run 2026-10-25T12:59Z on the live archive, read-only, one `sha256sum` pass over
the chunk files plus one pass of Python over `manifest.json`.

| Check | Method | Result |
|---|---|---|
| (a) every sealed chunk's sha256 matches its manifest entry | `shasum -a 256 chunks/*.jsonl.gz` (479 files) compared to each entry's `sha256` | **PASS — 473/473 match, 0 mismatches, 0 registered-but-absent** |
| (b) prev-chain unbroken from `genesis` to `chain_head` | walk entries: `entry[i].prev == entry[i-1].entry_hash`, first `prev == "genesis"` | **PASS — 0 `prev` mismatches over 473 links** |
| (b′) entry hashes recompute | `sha256(json.dumps(entry minus entry_hash, sort_keys=True))` for all 473 entries | **PASS — 0 mismatches** |
| (b″) `chain_head` equals last entry hash | manifest field vs recomputed chain | **PASS — `8001aad7…c0c05`** |
| (c) files on disk not registered | set difference of `chunks/` listing vs manifest `chunk` paths | **6 files, 4,079,445 bytes** — listed in §5 |
| (d) inter-chunk holes | `next.first_ms - prev.last_ms` per consecutive pair | **9 holes, 118.77 h total** — listed in §3.1 |
| gzip readability (sample) | full streaming decompress of 21 sealed chunks (0, 200, 449–465, 466, 472) | **PASS — every record parsed as JSON, no CRC/EOS error** |
| manifest bytes | `shasum -a 256 manifest.json`, `wc -c` | **PASS — 344,678 bytes, `a9acf666…56224`** |
| frozen copy in repo | `cmp` against source, then `sha256sum research/archive_frozen_manifest.json` | **PASS — byte-identical, same sha256** |

Verdict: **the frozen archive is internally consistent and tamper-evident.** Content
verification covers the chunk bytes; the chain proves no entry was edited after sealing.
These two together bound *integrity* — they cannot prove *completeness*, because nothing
in the archive records what a silent-but-connected websocket failed to deliver (§3.2).

Reproduce (stdlib only, read-only):

```bash
cd ~/Code/cryto-bot-edge/data/recorder && shasum -a 256 chunks/*.jsonl.gz > /tmp/archive_sha256.txt
python3 - <<'PY'
import hashlib, json, os
base = os.path.expanduser("~/Code/cryto-bot-edge/data/recorder")
m = json.load(open(f"{base}/manifest.json")); e = m["entries"]
actual = {p.rsplit("/", 1)[-1]: h for h, p in
          (l.rstrip("\n").split("  ", 1) for l in open("/tmp/archive_sha256.txt"))}
bad = [x["chunk"] for x in e if actual.get(x["chunk"].split("/")[-1]) != x["sha256"]]
prev, chain = "genesis", []
for x in e:
    body = {k: v for k, v in x.items() if k != "entry_hash"}
    chain.append(x["prev"] == prev and hashlib.sha256(
        json.dumps(body, sort_keys=True).encode()).hexdigest() == x["entry_hash"])
    prev = x["entry_hash"]
unreg = sorted(set(os.listdir(f"{base}/chunks")) - {x["chunk"].split("/")[-1] for x in e})
holes = [(e[i]["last_ms"], e[i+1]["first_ms"]) for i in range(len(e)-1)
         if e[i+1]["first_ms"] > e[i]["last_ms"]]
print("chunks", len(e), "sha_mismatches", len(bad), "chain_ok", all(chain),
      "head_ok", prev == m["chain_head"], "unregistered", unreg, "holes", len(holes))
PY
```

## 7. Inventory by phase

Streams change only at the boundaries below, so each phase is homogeneous.

| Phase | Chunks | Span (UTC) | Wall clock | Records | Bytes | Streams |
|---|---|---|---|---|---|---|
| P1 | 164 | rec-000000..rec-000163<br>2026-10-18T21:37:56Z → 2026-10-19T11:18:01Z | 13.7 h | 38,470,830 | 1,001,446,867 | bookTicker + depth + REST (7) |
| P2 | 1 | rec-000164..rec-000164<br>2026-10-19T11:18:01Z → 2026-10-19T11:37:07Z | 0.3 h | 18,818 | 570,884 | bookTicker + depth, no snapshot/premium (5) |
| P3 | 23 | rec-000165..rec-000187<br>2026-10-19T11:37:07Z → 2026-10-19T13:54:13Z | 2.3 h | 689 | 2,244,421 | REST only (3) |
| P4 | 12 | rec-000188..rec-000199<br>2026-10-19T13:56:24Z → 2026-10-19T14:56:57Z | 1.0 h | 6,967,291 | 163,230,909 | bookTicker + depth + REST (7) |
| P5 | 12 | rec-000200..rec-000211<br>2026-10-19T14:56:57Z → 2026-10-19T15:58:37Z | 1.0 h | 372 | 1,217,837 | REST only (3) |
| P6 | 183 | rec-000212..rec-000394<br>2026-10-19T15:59:39Z → 2026-10-20T07:14:46Z | 15.3 h | 42,269,190 | 1,098,865,181 | bookTicker + depth + REST (7) |
| P7 | 1 | rec-000395..rec-000395<br>2026-10-25T05:05:38Z → 2026-10-25T05:13:09Z | 0.1 h | 2 | 384 | premium_index only (1) |
| P8 | 53 | rec-000396..rec-000448<br>2026-10-25T05:33:20Z → 2026-10-25T09:58:26Z | 4.4 h | 8,229,548 | 238,411,937 | bookTicker + depth + REST (7) |
| P9 | 17 | rec-000449..rec-000465<br>2026-10-25T09:59:57Z → 2026-10-25T11:55:55Z | 1.9 h | 2,414,847 | 70,623,732 | bookTicker + depth + REST + trade (9) |
| P10 | 7 | rec-000466..rec-000472<br>2026-10-25T11:55:55Z → 2026-10-25T12:35:13Z | 0.7 h | 204 | 674,636 | REST only (3) |
| **Σ** | **473** | 2026-10-18T21:37:56Z → 2026-10-25T12:35:13Z | **40.2 h** | **98,371,791** | **2,577,286,788** | — |

Stream presence by chunk (a chunk may hold several): `btcusdt@bookTicker` 430,
`ethusdt@bookTicker` 430, `btcusdt@depth@100ms` 430, `ethusdt@depth@100ms` 430,
`depth_snapshot` 471, `open_interest` 472, `premium_index` 472, `btcusdt@trade` 17,
`ethusdt@trade` 17, `markPrice@1s` 0, `forceOrder` 0.

Chunk-class composition: 412 chunks with the 7-stream book set, 17 with the 9-stream set
including trade, 23 + 12 + 7 = 42 REST-only, 1 five-stream (164), 1 premium-only (395).
All 473 entries are `class` `DEV` / `input_class` `observed-public` / `venue`
`binance-usdm` / `symbol` `*` (symbols are per record).

## 8. Freeze record and disk note

* Free space on this Mac at the start of the audit: **11 GiB (94 % used)**; at the end:
  **7.6 GiB (96 % used)**. The decrease is from other Sessions running on the same
  machine, not from this audit: the audit wrote one 60 KB hash listing to `/tmp` and the
  344,678-byte manifest copy in this repository. No chunk was copied, moved, rewritten or
  deleted, no `.venv` was created, and no `uv`/`pip`/`pytest` was run.
* The archive has **no second copy**. 2.58 GB of the recorded week plus a 4.91-day
  unrecorded outage is now the whole evidence base; the only off-machine protection is a
  backup of the chunks, which this audit did not perform and which the owner would need
  to authorise (the chunks are ~2.6 GB of a disk with 7.6 GiB free).
* Do not "repair" the archive: adding a chunk, re-sealing a partial, editing a manifest
  entry or removing `STOP` all destroy the property this document attests.
