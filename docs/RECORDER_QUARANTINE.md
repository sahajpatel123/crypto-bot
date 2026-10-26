# Recorder quarantine list (frozen archive, 18–25 Oct 2026)

Status: **record of fact**. The recorder is owner-stopped (STOP file
2026-10-25T12:41:18Z) and this archive is frozen. Nothing listed here is
deleted or renamed in place — the files stay byte-identical so every hash
ever quoted still reproduces. Consumers MUST read via `manifest.json`
entries, never by scanning the chunks directory.

Audited base: `live/n49-recorder-inputs` from `live/trade-ready` (`3968cc7`).

## 1. Orphan twins (5 sequence numbers, 10 files)

Four crash-loop restarts on 2026-10-25 each orphaned one partial chunk: a
fresh process recomputed its next index as `len(manifest entries)`, reusing
the unsealed predecessor's number. The manifest references only the fuller
second twin (all five sha256-verified OK). The first twin of each pair is an
unreferenced orphan:

| Seq | Orphan (unreferenced, ignore) | Sealed (manifest) |
|---|---|---|
| 396 | `rec-000396-20261025T051309Z.jsonl.gz` (32 KB) | `rec-000396-20261025T053320Z.jsonl.gz` (5.3 MB) |
| 401 | `rec-000401-20261025T055820Z.jsonl.gz` (8.5 KB) | `rec-000401-20261025T055822Z.jsonl.gz` (5.3 MB) |
| 404 | `rec-000404-20261025T061322Z.jsonl.gz` (0 bytes) | `rec-000404-20261025T061324Z.jsonl.gz` (3.6 MB) |
| 449 | `rec-000449-20261025T095826Z.jsonl.gz` (725 KB) | `rec-000449-20261025T095957Z.jsonl.gz` (4.3 MB) |
| 458 | `rec-000458-20261025T104458Z.jsonl.gz` (3.2 MB) | `rec-000458-20261025T111513Z.jsonl.gz` (4.5 MB) |

Manifest: 473 entries (seq 0–472), hash chain intact, 0 breaks.

## 2. Corrupt tail (1 file)

`rec-000473-20261025T123513Z.jsonl.gz` (61 KB) is a truncated gzip
(`EOFError: end-of-stream marker`) killed mid-write at the stop. It is NOT
in the manifest and must never be trusted, repaired, or sealed
retroactively — sealing it now would rewrite history under a new hash.

## 3. Going forward (P4, this branch)

`RecorderWriter` startup quarantines any `rec-*.jsonl.gz` the manifest does
not reference to `orphan-<name>` before opening a new chunk, and alerts
`orphan-quarantined` per file. Sequence numbers therefore cannot be reused
again. The quarantine only ever renames unreferenced files; sealed chunks
are immutable.

## 4. Reader rule

Any tool that reads this archive (D1 evaluator, integrity reports,
ad-hoc analysis) MUST enumerate chunks from `manifest.json` entries and
verify each file's sha256. Directory scans will double-count the five
orphan seqs and choke on the corrupt tail. `d1_eval.read_records` already
reads manifest-first and verifies digests — keep it that way.
