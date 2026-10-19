# PILOT-STORAGE-2026-10-17 — pilot storage & compaction report

Owner: storage subagent findings, integrated by manager (this session).
Cap: 10GB total (raw + working) per coord/pivot/PILOT-01.json.

## Result
- 29/30 rank-ordered days built (rank #30 = 2026-10-17 skipped: today's
  archive not yet published — legitimate SKIP, rank order preserved).
- 33,880,280 events, pilot total 0.60GB — 6% of the 10GB cap.
- Average 20.7MB/day compacted (~1.17M events/day).

## Compaction rule (settled days only)
1. Build plain events.jsonl via tools/pilot_build.py; enroll-audit it.
2. `gzip -9 events.jsonl` -> events.jsonl.gz; `gzip -t` integrity check.
3. sha256 of the DECOMPRESSED stream must equal manifest sha256.events
   (byte-identical stream; schema untouched). Mismatch = rebuild, never ship.
4. Delete plain events.jsonl; write COMPACTION.json sidecar
   (method, stream_sha256, verified, timestamp).
5. Readers fall back to .gz when plain is absent: tools/pivot_enroll.py
   (storage-agent edit, kept, regression-tested), tools/pivot_study_01/02
   (manager edit, tested). Session-replay (peer-owned session.py) still
   requires plain events.jsonl — gz days are scoring/audit-ready, not
   session-replay-ready; pointer filed, no peer edit made.

Measured ratio: ~657MB plain -> ~30MB gz on the largest day (~22x).
Volatile days compress slightly worse (more unique prices); quiet days
better. Ratio holds across all 29 days (6-32MB/day).

## Source hygiene (what was deleted, what was kept)
- KEPT per day: events.jsonl.gz, funding.jsonl, manifest.json (with source
  URLs + SHA256), SOURCES.md, COMPACTION.json.
- DELETED after verified build: source .zips, unzipped CSVs, per-day REST
  funding CSVs (Oct). All rebuildable from manifest URLs (checksums pinned).
- /tmp/pilot_day/ retains 2026-09-21 sources only (rebuild provenance for
  the incident below); safe to delete after this report — manifest re-fetch
  covers rebuilds.

## Incident: 2026-09-21 directory vanished mid-session
- data/pilot/2026-09-21/ (657MB plain, pre-compaction) disappeared while the
  storage subagent was working. Both session logs (parent + child) were
  audited: NO rm/mv/rmdir by either party; the child itself was confused
  and attempted `git restore`.
- Cause UNKNOWN (possibly a peer agent or external cleanup). Stated as
  unknown; no speculation beyond evidence.
- Recovery: rebuilt via tools/pilot_build.py from /tmp/pilot_day sources:
  2,496,585 events, count-identical to the original; enroll-audit
  DEVELOPMENT-ONLY (expected 1d-caveat verdict). Then compacted normally.
- Prevention: build loop compacts each day immediately after audit (small
  plain window); manifests pin checksums so any future loss is a re-fetch,
  not a data-integrity question.

## Headroom & recommendation
- 0.60GB of 10GB used. The full 30-day volatile set fits at ~0.65GB.
- Remaining ~9.4GB could hold: quote-channel days (bookTicker daily, P1
  evaluation), a second symbol, or the live 10-day campaign working set.
- Do NOT backfill quiet/sideways days into the pilot: selection stays
  frozen per PILOT-01 (re-picking after scores = data-snooping).
