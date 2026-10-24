"""Retained-data asset audit (data-use layer).

Every store kept on this machine is checked twice:

1. **Integrity** -- manifests/hash chains, file presence, optional SHA-256
   over the stored bytes.
2. **Use** -- a real read through the project's own reader (``open_dataset``,
   Parquet, gzip JSONL) and an explicit consumer path.

Holdout bytes are *never* decoded.  Campaign captures are metadata-only:
they are reserved for an exactly-once confirmation and must not be read
without the owner's release.

The audit is intentionally offline and read-only.  It writes one JSON
report; it never edits a manifest or a data file.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "audit",
    "chain_problems",
    "verify_benchmark_inputs",
]

_REPO = Path(__file__).resolve().parents[2]
_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "ZECUSDT",
            "NEARUSDT", "STRKUSDT", "XRPUSDT", "WUSDT")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def chain_problems(doc: dict[str, Any]) -> list[str]:
    """Verify the recorder/vault/lake hash-chain shape."""
    problems: list[str] = []
    prev = "genesis"
    for i, entry in enumerate(doc.get("entries", [])):
        if entry.get("prev") != prev:
            problems.append(f"entry {i}: prev mismatch")
        body = {k: v for k, v in entry.items() if k != "entry_hash"}
        digest = hashlib.sha256(
            json.dumps(body, sort_keys=True).encode()).hexdigest()
        if digest != entry.get("entry_hash"):
            problems.append(f"entry {i}: hash mismatch")
        prev = entry.get("entry_hash")
    if prev != doc.get("chain_head"):
        problems.append("chain_head does not match last entry")
    return problems


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl_sample(path: Path, n: int = 3) -> list[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    out: list[dict[str, Any]] = []
    with opener(path, "rt", encoding="utf-8") as fh:  # type: ignore[arg-type]
        for line in fh:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
            if len(out) >= n:
                break
    return out


def _jsonl_rows(path: Path) -> int:
    opener = gzip.open if path.suffix == ".gz" else open
    rows = 0
    with opener(path, "rt", encoding="utf-8") as fh:  # type: ignore[arg-type]
        for line in fh:
            if line.strip():
                rows += 1
    return rows


def _asset(name: str, path: Path, *, kind: str, consumer: str,
           status: str, details: dict[str, Any] | None = None,
           problems: list[str] | None = None,
           bytes_: int = 0, note: str = "") -> dict[str, Any]:
    return {
        "name": name,
        "path": str(path),
        "kind": kind,
        "consumer": consumer,
        "status": status,
        "bytes": int(bytes_),
        "details": details or {},
        "problems": problems or [],
        "note": note,
    }


def verify_benchmark_inputs(repo: str | Path, *, full: bool = True) -> dict[str, Any]:
    """Verify the frozen benchmark manifest + cache before an evaluation.

    This is the gate used by ``tools/eval_h123.py`` and ``tools/eval_h4.py``.
    It fails closed on missing or hash-mismatched derived files.
    """
    repo = Path(repo)
    toml = repo / "datasets/benchmark_30d.toml"
    if not toml.is_file():
        return {"ok": False, "problems": [f"missing {toml}"],
                "sources": 0, "bytes": 0, "last_date": None}
    from cryptobot.market_data.datasets import open_dataset, verify_dataset

    handle = open_dataset(toml)
    sources = handle.manifest.get("source", [])
    problems: list[str] = []
    seen: set[Path] = set()
    total = 0
    for entry in sources:
        local = entry.get("local")
        if not local:
            problems.append(f"{entry.get('symbol', '?')}: no local path")
            continue
        resolved = Path(local)
        if not resolved.is_absolute():
            resolved = toml.parent / resolved
        if resolved not in seen:
            seen.add(resolved)
            if resolved.is_file():
                total += resolved.stat().st_size
    if full:
        problems.extend(verify_dataset(handle))
    else:
        for entry in sources:
            local = entry.get("local")
            if local:
                p = Path(local)
                if not p.is_absolute():
                    p = toml.parent / p
                if not p.is_file():
                    problems.append(f"missing {local}")
    dates = sorted(p.name.split("=", 1)[1]
                   for p in (repo / "datasets/cache").glob("symbol=*/date=*")
                   if p.is_dir() and "=" in p.name)
    last_date = dates[-1] if dates else None
    # Read one real event stream: this is the "used, not just present" proof.
    sample: list[dict[str, Any]] = []
    source = next((s for s in sources
                   if s.get("day") and s.get("symbol")
                   and s.get("channel") == "aggTrade"), None)
    sample_error = ""
    if source is not None:
        try:
            for event in handle.events(str(source["symbol"]), str(source["day"])):
                if event is None:
                    continue
                sample.append({
                    "channel": event.get("channel"),
                    "symbol": event.get("symbol"),
                    "ts_ms": event.get("exchange_ts_ms"),
                })
                if len(sample) >= 3:
                    break
        except Exception as exc:  # noqa: BLE001 - report, never hide
            sample_error = f"{type(exc).__name__}: {exc}"
    if sample_error:
        problems.append(f"sample read failed: {sample_error}")
    return {
        "ok": not problems,
        "problems": problems,
        "sources": len(sources),
        "bytes": total,
        "last_date": last_date,
        "manifest_sha": handle.manifest_sha()[:16],
        "sample": sample,
    }


def _benchmark(repo: Path, *, full: bool) -> dict[str, Any]:
    result = verify_benchmark_inputs(repo, full=full)
    details = {
        "sources": result["sources"],
        "manifest_sha": result.get("manifest_sha"),
        "cache_last_date": result.get("last_date"),
        "sample_events": result.get("sample", []),
    }
    status = "OK" if result["ok"] else "FAIL"
    return _asset(
        "benchmark_30d", repo / "datasets/benchmark_30d.toml",
        kind="frozen-dataset", consumer="tools/eval_h123.py, tools/eval_h4.py",
        status=status, details=details, problems=result["problems"],
        bytes_=result["bytes"],
        note="H2/H4 read datasets/cache through open_dataset+verify_dataset",
    )


def _pilot(repo: Path, *, full: bool) -> dict[str, Any]:
    root = repo / "data/pilot"
    days = sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    problems: list[str] = []
    rows = 0
    total = 0
    sample: list[dict[str, Any]] = []
    for day in days:
        manifest_path = day / "manifest.json"
        if not manifest_path.is_file():
            problems.append(f"{day.name}: missing manifest.json")
            continue
        manifest = _read_json(manifest_path)
        if manifest.get("input_class") != "observed-public":
            problems.append(f"{day.name}: input_class is not observed-public")
        rows += int(manifest.get("events_total", 0))
        events = day / "events.jsonl.gz"
        if not events.is_file():
            problems.append(f"{day.name}: missing events.jsonl.gz")
            continue
        total += events.stat().st_size
        try:
            if not sample:
                sample = _jsonl_sample(events, 2)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{day.name}: unreadable events: {exc}")
        if full:
            recorded = manifest.get("sha256")
            if isinstance(recorded, str) and len(recorded) == 64:
                actual = _sha256(events)
                if actual != recorded:
                    problems.append(f"{day.name}: events sha256 mismatch")
    status = "OK" if not problems else "FAIL"
    return _asset(
        "pilot", root, kind="pilot-days",
        consumer="tools/family_a_dev.py (external data root)",
        status=status,
        details={"days": len(days), "events_total": rows, "sample": sample},
        problems=problems, bytes_=total,
        note="read-only Family A development days; tracked in git",
    )


def _capture(name: str, root: Path, *, repo: Path, full: bool) -> dict[str, Any]:
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return _asset(name, root, kind="capture", consumer="",
                      status="MISSING",
                      problems=[f"missing {manifest_path}"])
    manifest = _read_json(manifest_path)
    problems: list[str] = []
    details: dict[str, Any] = {
        "run_id": manifest.get("run_id"),
        "input_class": manifest.get("input_class"),
        "symbols": manifest.get("symbols"),
        "files": {},
    }
    total = 0
    for key, meta in (manifest.get("files") or {}).items():
        raw_path = str(meta.get("path", ""))
        path = Path(raw_path)
        if not path.is_absolute():
            path = repo / path
        present = path.is_file()
        size = path.stat().st_size if present else int(meta.get("bytes", 0))
        total += size if present else 0
        details["files"][key] = {
            "path": str(path), "present": present, "bytes": size,
            "sha256": meta.get("sha256"),
        }
        if not present:
            problems.append(f"missing {key}: {path}")
        elif (full and key == "depth_snapshots" and meta.get("sha256")
              and _sha256(path) != meta["sha256"]):
            problems.append(f"{key}: sha256 mismatch")
    depth = root / "depth_snapshots.jsonl"
    if not depth.is_file():
        problems.append("missing depth_snapshots.jsonl")
    else:
        try:
            details["depth_rows"] = _jsonl_rows(depth)
            details["sample"] = _jsonl_sample(depth, 1)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"unreadable depth_snapshots: {exc}")
    status = "OK" if not problems else "PARTIAL"
    details["manifest_bytes"] = sum(
        int(meta.get("bytes", 0)) for meta in (manifest.get("files") or {}).values())
    if any(d.get("present") is False for d in details["files"].values()):
        consumer = "tools/score_h1_capture.py (bulk events not retained)"
    else:
        consumer = "tools/score_h1_capture.py"
    return _asset(
        name, root, kind="book-capture", consumer=consumer, status=status,
        details=details, problems=problems, bytes_=total,
        note="depth snapshots retained; manifest may reference bulk raw/events",
    )


def _campaign(root: Path) -> dict[str, Any]:
    chunks = sorted(p for p in root.iterdir()
                    if p.is_dir() and p.name.startswith("chunk-")) if root.is_dir() else []
    settled = 0
    total = 0
    problems: list[str] = []
    for chunk in chunks:
        if (chunk / "SETTLED.json").is_file():
            settled += 1
        if not (chunk / "manifest.json").is_file():
            problems.append(f"{chunk.name}: missing manifest.json")
        for suffix in ("events.jsonl.gz", "depth_snapshots.jsonl.gz"):
            p = chunk / suffix
            if p.is_file():
                total += p.stat().st_size
    status = "OK" if chunks and not problems else "FAIL"
    return _asset(
        "confirmation_campaign", root, kind="reserved-capture",
        consumer="exactly-once confirmation (owner-release only)",
        status=status,
        details={"chunks": len(chunks), "settled": settled,
                 "files": sum(1 for _ in root.rglob("*")) if root.is_dir() else 0},
        problems=problems, bytes_=total,
        note="metadata-only audit; event payloads NOT decoded (reserved)",
    )


def _lake(edge: Path, *, full: bool) -> dict[str, Any]:
    root = edge / "data/lake/dev"
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return _asset("lake_dev", root, kind="parquet-lake", consumer="",
                      status="MISSING", problems=[f"missing {manifest_path}"])
    manifest = _read_json(manifest_path)
    problems = chain_problems(manifest)
    entries = manifest.get("entries", [])
    total = sum(int(e.get("bytes", 0)) for e in entries)
    rows = sum(int(e.get("rows", 0)) for e in entries)
    sample: dict[str, Any] = {}
    for key in ("klines/interval=1d/symbol=BTCUSDT", "funding/symbol=BTCUSDT",
                "metrics/symbol=BTCUSDT"):
        p = root / key / "data.parquet"
        if not p.is_file():
            problems.append(f"missing sample {p}")
            continue
        try:
            sample[key] = _sample_parquet(p)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"sample read failed {p}: {exc}")
    for entry in entries:
        p = root / entry["path"]
        if not p.is_file():
            problems.append(f"missing {entry['path']}")
            continue
        if full and _sha256(p) != entry.get("sha256"):
            problems.append(f"sha256 mismatch {entry['path']}")
    status = "OK" if not problems else "FAIL"
    return _asset(
        "lake_dev", root, kind="parquet-lake",
        consumer="tools/run_family_b.py, tools/lake_finalize.py",
        status=status,
        details={"parquet_files": len(entries), "rows": rows, "sample": sample},
        problems=problems, bytes_=total,
        note="DEV split only; holdout is separate and sealed",
    )


def _holdout(edge: Path, *, full: bool) -> dict[str, Any]:
    root = edge / "data/lake/holdout_raw"
    manifests = sorted(root.glob("HOLDOUT-*.manifest.json"))
    if not manifests:
        return _asset("holdout", root, kind="sealed-holdout", consumer="",
                      status="MISSING",
                      problems=[f"no HOLDOUT-*.manifest.json in {root}"])
    problems: list[str] = []
    files = 0
    total = 0
    sampled = 0
    for manifest_path in manifests:
        doc = _read_json(manifest_path)
        if doc.get("format") != "cryptobot-holdout-manifest/1":
            problems.append(f"{manifest_path.name}: wrong format")
        entries = doc.get("files", [])
        files += len(entries)
        total += sum(int(e.get("bytes", 0)) for e in entries)
        step = max(1, len(entries) // 25) if entries else 1
        for entry in entries[::step][:25]:
            p = Path(entry["path"])
            if not p.is_absolute():
                p = edge / p
            if not p.is_file():
                problems.append(f"missing {entry['path']}")
            elif full and _sha256(p) != entry.get("sha256"):
                problems.append(f"sha256 mismatch {entry['path']}")
            sampled += 1
    status = "OK" if not problems else "FAIL"
    return _asset(
        "holdout", root, kind="sealed-holdout",
        consumer="cryptobot verdict --holdout-screen, tools/holdout_reconcile.py",
        status=status,
        details={"manifests": len(manifests), "files": files,
                 "hashed_sample": sampled},
        problems=problems, bytes_=total,
        note="NO content decode; byte hash only",
    )


def _recorder(edge: Path, *, full: bool) -> dict[str, Any]:
    root = edge / "data/recorder"
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return _asset("recorder", root, kind="live-recorder", consumer="",
                      status="MISSING", problems=[f"missing {manifest_path}"])
    manifest = _read_json(manifest_path)
    problems = chain_problems(manifest)
    entries = manifest.get("entries", [])
    total = sum(int(e.get("bytes", 0)) for e in entries)
    sealed = {e.get("chunk") for e in entries}
    chunk_files = {str(p.relative_to(root))
                   for p in (root / "chunks").glob("*.jsonl.gz")}
    unsealed = sorted(chunk_files - sealed)
    sample: dict[str, Any] = {}
    for entry in (entries[:1] + entries[-1:]):
        p = root / entry["chunk"]
        if not p.is_file():
            problems.append(f"missing chunk {entry['chunk']}")
            continue
        try:
            sample[entry["chunk"]] = _jsonl_sample(p, 2)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"unreadable {entry['chunk']}: {exc}")
    for entry in entries:
        p = root / entry["chunk"]
        if not p.is_file():
            problems.append(f"missing {entry['chunk']}")
            continue
        if full and _sha256(p) != entry.get("sha256"):
            problems.append(f"sha256 mismatch {entry['chunk']}")
    if unsealed:
        problems.append(f"{len(unsealed)} unsealed chunk(s): {unsealed[:3]}")
    status = "OK" if not problems else "FAIL"
    return _asset(
        "recorder", root, kind="live-recorder",
        consumer="cryptobot compact, recorder verify, background status",
        status=status,
        details={"chunks": len(entries),
                 "records": sum(int(e.get("records", 0)) for e in entries),
                 "gaps": sum(int(e.get("gaps", 0)) for e in entries),
                 "unsealed": unsealed, "sample": sample},
        problems=problems, bytes_=total,
        note="book/depth/markPrice only; no aggTrade stream",
    )


def _vault(edge: Path, *, full: bool) -> dict[str, Any]:
    root = edge / "data/vault"
    registry_path = root / "registry.json"
    if not registry_path.is_file():
        return _asset("vault", root, kind="sealed-vault", consumer="",
                      status="MISSING", problems=[f"missing {registry_path}"])
    registry = _read_json(registry_path)
    problems = chain_problems(registry)
    entries = registry.get("entries", [])
    total = sum(int(e.get("bytes", 0)) for e in entries)
    classes: dict[str, int] = {}
    for entry in entries:
        classes[entry.get("class", "?")] = classes.get(entry.get("class", "?"), 0) + 1
        p = root / entry["file"]
        if not p.is_file():
            problems.append(f"missing {entry['file']}")
            continue
        if full and _sha256(p) != entry.get("sha256"):
            problems.append(f"sha256 mismatch {entry['file']}")
    status = "OK" if not problems else "FAIL"
    return _asset(
        "vault", root, kind="sealed-vault",
        consumer="cryptobot verdict --vault-*, tools/holdout_reconcile.py",
        status=status,
        details={"chunks": len(entries), "classes": classes,
                 "access_log": len(registry.get("access_log", [])),
                 "frozen": sorted(registry.get("frozen", {}))},
        problems=problems, bytes_=total,
        note="no decode; registry chain + chunk hashes only",
    )


def _sample_parquet(path: Path, n: int = 2) -> dict[str, Any]:
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(str(path))
    batch = next(pf.iter_batches(batch_size=n))
    rows = batch.to_pylist()
    return {"path": str(path), "columns": batch.schema.names,
            "total_rows": pf.metadata.num_rows, "sample": rows[:n]}


def _fmt_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"


def audit(repo: str | Path = _REPO, *, edge_root: str | Path | None = None,
          full: bool = True, require_edge: bool = False) -> dict[str, Any]:
    """Audit every retained store and return a machine-readable report."""
    repo = Path(repo).resolve()
    edge_env = os.environ.get("CRYPTOBOT_EDGE_ROOT")
    edge = Path(edge_root or edge_env or (repo.parent / "cryto-bot-edge")).resolve()
    assets = [
        _benchmark(repo, full=full),
        _pilot(repo, full=full),
        _capture("h1_capture", repo / "data/captures/h1-accrual-01",
                 repo=repo, full=full),
        _capture("h5_capture", repo / "data/captures/h5-accrual-01",
                 repo=repo, full=full),
        _campaign(repo / "data/captures/campaign-1day-20261017"),
    ]
    if edge.is_dir():
        assets += [
            _lake(edge, full=full),
            _holdout(edge, full=full),
            _recorder(edge, full=full),
            _vault(edge, full=full),
        ]
    else:
        status = "MISSING" if require_edge else "SKIP"
        for name, kind in (("lake_dev", "parquet-lake"),
                           ("holdout", "sealed-holdout"),
                           ("recorder", "live-recorder"),
                           ("vault", "sealed-vault")):
            assets.append(_asset(
                name, edge / "data", kind=kind, consumer="",
                status=status, problems=[f"edge root not found: {edge}"]))
    hard_fail = any(a["status"] in ("FAIL", "MISSING") for a in assets)
    partial = any(a["status"] == "PARTIAL" for a in assets)
    total = sum(int(a["bytes"]) for a in assets)
    return {
        "format": "cryptobot-data-use/1",
        "generated_utc": _utc_now(),
        "repo": str(repo),
        "edge_root": str(edge),
        "full_hash": full,
        "assets": assets,
        "summary": {
            "assets": len(assets),
            "ok": sum(a["status"] == "OK" for a in assets),
            "partial": sum(a["status"] == "PARTIAL" for a in assets),
            "failed": sum(a["status"] in ("FAIL", "MISSING") for a in assets),
            "bytes": total,
            "bytes_human": _fmt_bytes(total),
        },
        "verdict": "FAIL" if hard_fail else ("WARN" if partial else "PASS"),
    }


def print_report(report: dict[str, Any]) -> None:
    """Small terminal table for ``cryptobot data assets``."""
    print(f"{'ASSET':24} {'STATUS':8} {'SIZE':>10}  CONSUMER")
    for asset in report.get("assets", []):
        print(f"{asset['name']:24} {asset['status']:8} "
              f"{_fmt_bytes(int(asset['bytes'])):>10}  {asset['consumer']}")
        for problem in asset.get("problems", [])[:3]:
            print(f"  ! {problem}")
    summary = report.get("summary", {})
    print(f"\n{report.get('verdict')}: {summary.get('ok')}/{summary.get('assets')} "
          f"assets OK, {summary.get('partial')} partial, "
          f"{summary.get('failed')} failed, {summary.get('bytes_human')} accounted")
    print(f"report: {report.get('generated_utc')} repo={report.get('repo')}")


if __name__ == "__main__":  # pragma: no cover - CLI convenience
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else _REPO
    print(json.dumps(audit(target), indent=1, default=str))
