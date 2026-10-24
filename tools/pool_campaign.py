"""Pool settled campaign chunks into one day-capture (mechanical, read-only).

Preregistered in reports/pivot/CAMPAIGN-SCORING-PREREG-2026-10-17.md.
Concatenates chunk-*/events (.jsonl.gz preferred, plain fallback) ordered
by exchange_ts_ms with fresh sequential seq; no other transformation.
Only chunks with SETTLED.json are included; the manifest records the
chunk list, per-chunk counts, and stream sha256. Result-blind assembly:
run before any scoring on the campaign.

Exit 0 pooled; 2 input/contract error.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

EXIT_BLOCKED = 2


def _open_events(chunk: Path):
    gz = chunk / "events.jsonl.gz"
    plain = chunk / "events.jsonl"
    if gz.exists():
        return gzip.open(gz, "rt", encoding="utf-8")
    if plain.exists():
        return plain.open(encoding="utf-8")
    raise ValueError(f"{chunk.name}: events missing")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pool settled campaign chunks (read-only)")
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--min-events", type=int, default=1000)
    args = parser.parse_args()
    try:
        campaign = Path(args.campaign)
        chunks = sorted(p for p in campaign.iterdir()
                        if p.is_dir() and p.name.startswith("chunk-"))
        if not chunks:
            raise ValueError(f"{campaign}: no chunks")
        pooled: list[tuple[int, int, dict]] = []  # (ts, order, event)
        used, skipped = [], []
        order = 0
        for chunk in chunks:
            if not (chunk / "SETTLED.json").exists():
                skipped.append(f"{chunk.name}: unsettled")
                continue
            buf = []
            with _open_events(chunk) as fh:
                for line in fh:
                    try:
                        e = json.loads(line)
                        ts = int(e["exchange_ts_ms"])
                    except (ValueError, KeyError, TypeError):
                        continue
                    order += 1
                    buf.append((ts, order, e))
            if len(buf) < args.min_events:
                skipped.append(f"{chunk.name}: near-empty ({len(buf)})")
                continue
            used.append({"chunk": chunk.name, "events": len(buf)})
            pooled.extend(buf)
        if not used:
            raise ValueError("no settled non-empty chunks")
        pooled.sort(key=lambda t: (t[0], t[1]))
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        with open(out / "events.jsonl", "w", encoding="utf-8") as fh:
            for seq, (_, _, e) in enumerate(pooled, 1):
                e["seq"] = seq
                line = json.dumps(e, sort_keys=True) + "\n"
                h.update(line.encode("utf-8"))
                fh.write(line)
        manifest = {"run_id": f"pooled-{campaign.name}",
                    "input_class": "observed-public",
                    "format": "cryptobot-events/1",
                    "assembly": "time-ordered concat, fresh seq, no other edit",
                    "chunks_used": used, "chunks_skipped": skipped,
                    "events_total": len(pooled),
                    "sha256": {"events": h.hexdigest()}}
        (out / "manifest.json").write_text(json.dumps(manifest, indent=1),
                                           encoding="utf-8")
    except ValueError as exc:
        print(f"BLOCKED: {exc}")
        return EXIT_BLOCKED
    print(f"POOLED {len(pooled)} events from {len(used)} chunks "
          f"({len(skipped)} skipped) -> {args.out}")
    for s in skipped:
        print(f"  skip: {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
