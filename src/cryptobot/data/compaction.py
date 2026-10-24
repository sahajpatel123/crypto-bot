"""Zstd Parquet compaction for sealed recorder chunks.

Equivalence is proven before any byte is treated as redundant: row
count and a canonical SHA-256 over every record must match the raw
gzip source. Proofs land in an append-only hash chain next to the
recorder manifest.

Raw deletion is deliberately NOT automatic. The recorder manifest is
append-only and hashes each raw chunk, so deleting a referenced chunk
would break `recorder verify` and the vault import. A future manifest
schema (v2) can record compaction in-chain; until that is reviewed,
pruning stays an explicit owner action on a copy.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

FORMAT = "cryptobot-compaction-proof/1"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _canonical(line: str) -> str:
    return json.dumps(json.loads(line), sort_keys=True, separators=(",", ":"))


def _chain_digest(rows: list[str]) -> tuple[str, int]:
    h = hashlib.sha256()
    for row in rows:
        h.update(row.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest(), len(rows)


def _load_proof(path: Path) -> dict:
    if not path.exists():
        return {"format": FORMAT, "chain_head": "genesis", "entries": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_proof(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, path)


def _append_proof(path: Path, body: dict) -> dict:
    doc = _load_proof(path)
    entry = {**body, "ts_utc": datetime.now(UTC).isoformat(),
             "prev": doc["chain_head"]}
    entry["entry_hash"] = hashlib.sha256(
        json.dumps(entry, sort_keys=True).encode()).hexdigest()
    doc["entries"].append(entry)
    doc["chain_head"] = entry["entry_hash"]
    doc["format"] = FORMAT
    _save_proof(path, doc)
    return entry


def verify_proof(path: Path) -> list[str]:
    doc = _load_proof(path)
    if doc.get("format") != FORMAT:
        return ["compaction proof missing or wrong format"]
    prev = "genesis"
    problems = []
    for i, entry in enumerate(doc.get("entries", [])):
        if entry.get("prev") != prev:
            problems.append(f"entry {i}: prev mismatch")
        body = {k: v for k, v in entry.items() if k != "entry_hash"}
        if hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest() \
                != entry.get("entry_hash"):
            problems.append(f"entry {i}: hash mismatch")
        prev = entry.get("entry_hash")
    if prev != doc.get("chain_head"):
        problems.append("chain_head mismatch")
    return problems


def compact_chunk(raw: Path, out: Path) -> dict:
    """Write a zstd Parquet copy and prove row/hash equivalence."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    with gzip.open(raw, "rt", encoding="utf-8") as fh:
        lines = [line.rstrip("\n") for line in fh if line.strip()]
    canonical = [_canonical(line) for line in lines]
    raw_digest, rows = _chain_digest(canonical)
    table = pa.table({"record": pa.array(canonical, type=pa.string())})
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    pq.write_table(table, tmp, compression="zstd")
    os.replace(tmp, out)
    back = pq.read_table(out, columns=["record"]).column("record").to_pylist()
    parquet_digest, parquet_rows = _chain_digest(
        [_canonical(row) for row in back])
    if parquet_rows != rows or parquet_digest != raw_digest:
        raise ValueError(
            f"compaction equivalence failed for {raw}: "
            f"rows {rows}->{parquet_rows}, hash {raw_digest}->{parquet_digest}")
    return {"raw": raw.name, "parquet": out.name, "rows": rows,
            "canonical_sha256": raw_digest,
            "raw_sha256": _sha256_file(raw),
            "parquet_sha256": _sha256_file(out),
            "raw_bytes": raw.stat().st_size, "parquet_bytes": out.stat().st_size}


def compact_root(root: str | Path, *, limit: int | None = None) -> dict:
    root = Path(root)
    manifest = root / "manifest.json"
    chunks = sorted((root / "chunks").glob("*.jsonl.gz"))
    if limit is not None:
        chunks = chunks[:limit]
    proof_path = root / "compaction-manifest.json"
    done = []
    for raw in chunks:
        out = raw.with_suffix(".parquet")
        info = compact_chunk(raw, out)
        recorder_head = ""
        if manifest.exists():
            try:
                recorder_head = json.loads(
                    manifest.read_text(encoding="utf-8")).get(
                        "chain_head", "")
            except ValueError:
                recorder_head = ""
        info["recorder_chain_head"] = recorder_head
        _append_proof(proof_path, info)
        done.append({k: info[k] for k in (
            "raw", "parquet", "rows", "raw_bytes", "parquet_bytes")})
    problems = verify_proof(proof_path) if done else []
    saved = sum(d["raw_bytes"] - d["parquet_bytes"] for d in done)
    return {"format": "cryptobot-compaction-report/1",
            "root": str(root), "chunks": len(done),
            "raw_bytes": sum(d["raw_bytes"] for d in done),
            "parquet_bytes": sum(d["parquet_bytes"] for d in done),
            "saved_bytes": saved,
            "proof_problems": problems, "chunks_detail": done,
            "verdict": "PASS" if not problems else "FAIL"}


__all__ = ["compact_chunk", "compact_root", "verify_proof"]
