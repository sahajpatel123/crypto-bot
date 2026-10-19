"""Daily integrity report over a recorder run directory (F3 data engine).

Pure functions over chunk files (``.jsonl`` and ``.jsonl.gz``): no network,
no writer dependency. Checks:

* gap_rate — manifest intervals flagged GAPPED / total intervals
* trade-ID continuity — per-symbol aggTrade id gaps (ranges listed)
* timestamp monotonicity — exchange + local regressions in file order
* depth-chain breaks — per-symbol updateId (prev_last_update) discontinuities
"""
from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

__all__ = [
    "iter_chunk_events",
    "read_manifest_gaps",
    "check_trade_continuity",
    "check_monotonicity",
    "check_depth_chain",
    "build_report",
    "render_markdown",
]

_MAX_DETAIL = 100  # cap listed violations; totals always count everything.


def _open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def iter_chunk_events(run_dir: str | Path) -> Iterator[tuple[str, int, dict[str, Any]]]:
    """Yield (filename, lineno, record) for every JSON line in every chunk.

    Files are visited in sorted-name order; the manifest is never treated as
    a chunk. Malformed lines are skipped here (counted by build_report).
    """
    run_dir = Path(run_dir)
    files = sorted(p for p in run_dir.rglob("*.jsonl*")
                   if p.is_file() and p.name != "manifest.jsonl" and ".jsonl" in p.suffixes)
    for path in files:
        try:
            fh = _open_text(path)
        except OSError:
            continue
        with fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict):
                    yield path.name, lineno, record


def _chunk_files(run_dir: Path) -> list[Path]:
    return sorted(p for p in run_dir.rglob("*.jsonl*")
                  if p.is_file() and p.name != "manifest.jsonl" and ".jsonl" in p.suffixes)


def read_manifest_gaps(run_dir: str | Path) -> dict[str, Any]:
    """Gap stats from manifest.jsonl: total intervals, flagged, gap_rate."""
    manifest = Path(run_dir) / "manifest.jsonl"
    if not manifest.exists():
        return {"present": False, "total": 0, "flagged": 0, "gap_rate": None}
    total, flagged = 0, 0
    with manifest.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            total += 1
            if isinstance(entry, dict) and entry.get("gapped"):
                flagged += 1
    return {"present": True, "total": total, "flagged": flagged,
            "gap_rate": (flagged / total) if total else 0.0}


def check_trade_continuity(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-symbol aggTrade id gaps. Each missing range is listed exactly once."""
    per_symbol: dict[str, set[int]] = {}
    counts: dict[str, int] = {}
    for event in events:
        if event.get("channel") != "aggTrade":
            continue
        symbol = str(event.get("symbol", ""))
        payload = event.get("payload", {})
        agg_id = payload.get("agg_id", event.get("venue_seq")) if isinstance(payload, dict) else None
        if not isinstance(agg_id, int):
            continue
        per_symbol.setdefault(symbol, set()).add(agg_id)
        counts[symbol] = counts.get(symbol, 0) + 1
    out: dict[str, Any] = {}
    for symbol in sorted(per_symbol):
        ids = sorted(per_symbol[symbol])
        gaps = []
        for prev, nxt in zip(ids, ids[1:], strict=False):
            if nxt > prev + 1:
                gaps.append({"prev": prev, "next": nxt, "missing": nxt - prev - 1})
        out[symbol] = {"events": counts[symbol], "gaps": gaps,
                       "missing_total": sum(g["missing"] for g in gaps)}
    return out


def check_monotonicity(files_events: dict[str, list[tuple[int, dict[str, Any]]]]) -> dict[str, Any]:
    """Timestamp regressions in file order (exchange_ts_ms + local_recv_ms).

    Each check is per-file in line order: a timestamp strictly less than the
    running maximum is one violation. Records lacking a field are skipped.
    """
    detail: list[dict[str, Any]] = []
    exchange_violations = 0
    local_violations = 0
    for name in sorted(files_events):
        prev_ex: int | None = None
        prev_local: int | None = None
        for lineno, event in files_events[name]:
            ext = event.get("exchange_ts_ms")
            if isinstance(ext, int):
                if prev_ex is not None and ext < prev_ex:
                    exchange_violations += 1
                    if len(detail) < _MAX_DETAIL:
                        detail.append({"file": name, "line": lineno, "field": "exchange_ts_ms",
                                       "prev_max": prev_ex, "current": ext})
                elif prev_ex is None or ext > prev_ex:
                    prev_ex = ext
            loc = event.get("local_recv_ms")
            if isinstance(loc, int):
                if prev_local is not None and loc < prev_local:
                    local_violations += 1
                    if len(detail) < _MAX_DETAIL:
                        detail.append({"file": name, "line": lineno, "field": "local_recv_ms",
                                       "prev_max": prev_local, "current": loc})
                elif prev_local is None or loc > prev_local:
                    prev_local = loc
    return {"exchange_violations": exchange_violations, "local_violations": local_violations,
            "detail": detail}


def check_depth_chain(events: list[tuple[str, int, dict[str, Any]]]) -> dict[str, Any]:
    """Per-symbol depth updateId chain breaks (prev_last_update != last seen).

    The first depth event per symbol anchors the chain (no snapshot context);
    every later event whose prev_last_update differs from the running
    last_update is one break. The scan continues from the observed IDs.
    """
    per_symbol: dict[str, list[dict[str, Any]]] = {}
    last_seen: dict[str, int] = {}
    for name, lineno, event in events:
        if event.get("channel") != "depth":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        first = payload.get("first_update")
        last = payload.get("last_update")
        prev = payload.get("prev_last_update")
        if not all(isinstance(v, int) for v in (first, last, prev)):
            continue
        symbol = str(event.get("symbol", ""))
        if symbol in last_seen and prev != last_seen[symbol]:
            per_symbol.setdefault(symbol, []).append(
                {"file": name, "line": lineno, "expected_prev": last_seen[symbol],
                 "got_prev": prev, "first_update": first, "last_update": last})
        last_seen[symbol] = last
    total = sum(len(v) for v in per_symbol.values())
    return {"breaks": per_symbol, "total": total}


def build_report(run_dir: str | Path) -> dict[str, Any]:
    """Build the integrity report dict for a run directory (pure, offline)."""
    run_dir = Path(run_dir)
    files = _chunk_files(run_dir)
    events: list[dict[str, Any]] = []
    ordered: list[tuple[str, int, dict[str, Any]]] = []
    per_file: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    malformed = 0
    for path in files:
        per_file.setdefault(path.name, [])
        try:
            fh = _open_text(path)
        except OSError:
            continue
        with fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    malformed += 1
                    continue
                if not isinstance(record, dict):
                    malformed += 1
                    continue
                events.append(record)
                ordered.append((path.name, lineno, record))
                per_file[path.name].append((lineno, record))
    mono = check_monotonicity(per_file)
    depth = check_depth_chain(ordered)
    trades = check_trade_continuity(events)
    manifest = read_manifest_gaps(run_dir)
    return {
        "run_dir": str(run_dir),
        "files": len(files),
        "events": len(events),
        "malformed_lines": malformed,
        "manifest": manifest,
        "trade_gaps": trades,
        "monotonicity": mono,
        "depth_breaks": depth,
    }


def render_markdown(report: dict[str, Any]) -> str:
    """Render a report dict as markdown."""
    lines = [
        f"# Integrity report: `{report.get('run_dir', '')}`",
        "",
        f"Files: {report.get('files', 0)} | Events: {report.get('events', 0)} "
        f"| Malformed lines: {report.get('malformed_lines', 0)}",
        "",
    ]
    manifest = report.get("manifest", {})
    if manifest.get("present"):
        rate = manifest.get("gap_rate")
        rate_s = f"{rate:.4f}" if isinstance(rate, float) else str(rate)
        lines.append(f"## Manifest gaps: {manifest.get('flagged', 0)}/"
                     f"{manifest.get('total', 0)} (gap_rate={rate_s})")
    else:
        lines.append("## Manifest gaps: no manifest.jsonl present")
    lines += ["", "## Trade-ID continuity"]
    trades = report.get("trade_gaps", {})
    if not trades:
        lines.append("No aggTrade events.")
    for symbol in sorted(trades):
        info = trades[symbol]
        lines.append(f"- {symbol}: {info['events']} events, "
                     f"{len(info['gaps'])} gap(s), {info['missing_total']} missing ids")
        for gap in info["gaps"][:_MAX_DETAIL]:
            lines.append(f"  - ids ({gap['prev']}, {gap['next']}): {gap['missing']} missing")
    mono = report.get("monotonicity", {})
    lines += ["", "## Timestamp monotonicity",
              f"exchange violations: {mono.get('exchange_violations', 0)} | "
              f"local violations: {mono.get('local_violations', 0)}"]
    for item in mono.get("detail", [])[:_MAX_DETAIL]:
        lines.append(f"- {item['file']}:{item['line']} {item['field']}: "
                     f"{item['current']} < prev max {item['prev_max']}")
    depth = report.get("depth_breaks", {})
    lines += ["", f"## Depth-chain breaks: {depth.get('total', 0)}"]
    for symbol in sorted(depth.get("breaks", {})):
        for item in depth["breaks"][symbol][:_MAX_DETAIL]:
            lines.append(f"- {symbol} {item['file']}:{item['line']}: expected prev "
                         f"{item['expected_prev']}, got {item['got_prev']}")
    lines.append("")
    return "\n".join(lines)
