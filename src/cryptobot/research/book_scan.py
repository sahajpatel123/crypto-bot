"""Top-N notional book-imbalance scan over retained depth snapshots.

The standalone recorder persists full REST ``depth_snapshot`` books every
30 s plus a diff stream.  The diff stream is deliberately labelled
``gap=depth-chain`` by the recorder when its update-id chain cannot be
proven, so this module uses only the full snapshots: they are independent,
complete, and safe to read.

This is a **diagnostic**, not a verdict.  The recorder has no aggTrade
stream, so the H1 entry/exit fill model cannot be run from it.  The scan
answers a narrower question: how often does the frozen top-5 notional
imbalance (±0.6) occur when the book is actually full-depth?
"""
from __future__ import annotations

import gzip
import json
from collections import defaultdict
from collections.abc import Iterable, Iterator
from pathlib import Path
from statistics import fmean
from typing import Any

from cryptobot.research.h1_eval import Snapshot, imbalance

__all__ = ["scan_records", "scan_recorder", "snapshot_imbalance"]

_THRESHOLDS = (0.3, 0.4, 0.5, 0.6)


def snapshot_imbalance(record: dict[str, Any], levels: int = 5) -> float | None:
    """Top-N notional imbalance from one recorder ``depth_snapshot`` record."""
    raw_bids = record.get("bids") or []
    raw_asks = record.get("asks") or []
    if not raw_bids or not raw_asks:
        return None
    bids = tuple(sorted(((float(p), float(q)) for p, q in raw_bids),
                        reverse=True)[:levels])
    asks = tuple(sorted((float(p), float(q)) for p, q in raw_asks)[:levels])
    return imbalance(Snapshot(ts_ms=int(record.get("event_ms", 0)),
                              bids=bids, asks=asks), levels=levels)


def _stats(values: list[float], threshold: float) -> dict[str, Any]:
    if not values:
        return {"n": 0, "signals": 0, "mean_abs": None,
                "min": None, "max": None, "thresholds": {}}
    abs_values = [abs(v) for v in values]
    return {
        "n": len(values),
        "signals": sum(v > threshold for v in abs_values),
        "mean_abs": round(fmean(abs_values), 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "thresholds": {
            f">{t:g}": sum(v > t for v in abs_values) for t in _THRESHOLDS
        },
    }


def scan_records(records: Iterable[dict[str, Any]], *, levels: int = 5,
                 threshold: float = 0.6) -> dict[str, Any]:
    """Summarize full-depth snapshots across symbols."""
    per_symbol: dict[str, list[float]] = defaultdict(list)
    seen = 0
    skipped = 0
    for record in records:
        if record.get("type") != "depth_snapshot":
            continue
        seen += 1
        value = snapshot_imbalance(record, levels=levels)
        if value is None:
            skipped += 1
            continue
        per_symbol[str(record.get("symbol", "?"))].append(value)
    all_values = [v for values in per_symbol.values() for v in values]
    return {
        "format": "cryptobot-book-scan/1",
        "levels": levels,
        "threshold": threshold,
        "snapshots": seen,
        "skipped": skipped,
        "per_symbol": {sym: _stats(values, threshold)
                       for sym, values in sorted(per_symbol.items())},
        "total": _stats(all_values, threshold),
    }


def scan_recorder(root: str | Path = "data/recorder", *, levels: int = 5,
                  threshold: float = 0.6, limit: int | None = None) -> dict[str, Any]:
    """Run the scan over a recorder root (default: ``data/recorder``)."""
    root = Path(root)
    chunks = sorted((root / "chunks").glob("*.jsonl.gz"))
    if limit is not None:
        chunks = chunks[:limit]

    def _records() -> Iterator[dict[str, Any]]:
        for chunk in chunks:
            with gzip.open(chunk, "rt", encoding="utf-8") as fh:
                for line in fh:
                    if '"depth_snapshot"' not in line:
                        continue
                    try:
                        yield json.loads(line)
                    except ValueError:
                        continue

    report = scan_records(_records(), levels=levels, threshold=threshold)
    report.update({
        "root": str(root),
        "chunks": len(chunks),
        "diagnostic": True,
        "not_a_verdict": True,
        "note": ("Full REST depth snapshots only. No aggTrade stream, so no "
                 "fills/verdict. The recorder marks its diff chain with "
                 "gap=depth-chain; that path is not used."),
    })
    return report
