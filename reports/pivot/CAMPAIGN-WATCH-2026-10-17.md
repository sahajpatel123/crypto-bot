# Campaign watch — 10-day BTC capture (2026-10-17, read-only)

The peer's campaign (`data/captures/campaign-20261016`, BTCUSDT, 1h
chunks, lean500) is running (supervisor alive). Nothing in the
campaign dir was touched; all checks below are reads plus my own
report files.

## Chunk-000 audit: HEALTHY on every per-chunk check

Audited via `tools/pivot_enroll.py` on a /tmp decompression
(originals untouched): 43,954 events, seq monotonic (0 disordered),
channels aggTrade 38,427 + depth 3,714 + markPrice 1,813, mark max
gap 1,017ms (floor: ≤5,000ms). The only floor failures are the
expected ones: 0.03d span (it is one hourly chunk of a 240-chunk
campaign) and no funding settlements (see below). The campaign
design captures enrollment-grade data when the connection holds.

## Flags for the campaign owner (not fixed here)

1. **chunk-002 settled nearly empty**: `events_total: 194` for a full
   hour (vs 43,954 in chunk-000), `stop_reason: duration-reached`,
   no error. A dead hour inside the campaign span.
2. **Chunks ~4h apart, not 1h**: 15:16Z → 19:11Z → 23:52Z → 04:35Z
   for chunks 0–3. Either long stalls between chunks or the
   supervisor clock/dating needs a look.
3. **Funding settlements still missing**: marks carry funding *rates*
   (1,813 observations), which the floor explicitly does not accept
   as settlements. `reports/pivot/funding-campaign-seed.jsonl`
   (10 settlements, recorded just now, my file) seeds provenance;
   recommend the campaign adopt `tools/pivot_funding_capture.py
   --mode watch` alongside capture so the sidecar grows with the
   chunks — otherwise the full 10 days still cannot enroll.

## Campaign-mode audit (same day)

`tools/pivot_enroll.py --campaign` (new: streams settled chunks
straight from `.gz`, resets seq/mark tracking at chunk boundaries,
flags unsettled or near-empty chunks; 3 new tests) run read-only
over the live campaign: 119,326 events across 3 settled chunks,
DEVELOPMENT-ONLY with 4 failures — the known empty chunk-002
(194 events), 0.36d span (campaign in progress), no funding
settlements, and one new find: a **718s intra-chunk mark gap**,
i.e. a ~12-minute stall inside a settled chunk, distinct from the
between-chunk spacing. Localized: chunk-001, exchange window
1792182459–1792183177, with ZERO events on any channel
(aggTrade/depth/markPrice all silent) — a full connection stall, the
same lossy-host signature seen in the paper runs, not a
stream-specific dropout. Chunk-000 max gap 1.0s; chunk-002 max gap
1.0s (but only 45 marks total). If stalls like this recur across the
240 chunks, the campaign owner will need a gap policy (re-capture
vs accept) before enrollment, since the floor's mark-cadence check
fails any chunk containing one.

## Progress log (campaign-mode audits, read-only)

| Settled | Events | Span | Healthy | Verdict |
|---|---|---|---|---|
| 4 | 149,117 | 0.60d | 3/4 | DEVELOPMENT-ONLY, 4 failures |
| 5 | 178,176 | 0.64d | 4/5 | same 4 failures |
| 6 | 210,943 | 0.68d | 5/6 | same 4 failures |
| 7 | 242,194 | 0.72d | 6/7 | same 4 failures |
| 8 | 267,696 | 0.76d | 7/8 | same 4 failures |
| 9 | 287,375 | 0.81d | 8/9 | same 4 failures |

Pace recovered to hourly since chunk-003. The 4 standing failures:
empty chunk-002, span, the chunk-001 718s stall, funding sidecar.

## What this unblocks

If the campaign completes with healthy chunks, Z1 flips: the first
real enrollment audit becomes possible and PIVOT-01 families can be
scored on fresh data. Until then, no verdict changes.
