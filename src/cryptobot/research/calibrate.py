"""Versioned cost-model calibration (F2.2).

Ingests realized-slippage observations (demo-drill/live attribution,
F5.4 schema) and paper fills_drift rows (dispatch latency +
predicted drift): fits slippage_bps := p90(realized) and
latency_ms_p95 := p95(latency); writes a hash-chained versioned cost
model whose params load via PaperFillParams.from_dict.

Honesty rules (machine-enforced):
- Paper predicted drift NEVER fits realized slippage (the sim has no
  adverse selection); paper rows feed latency only.
- Auto-update only TIGHTENS (per-leg max with current). Relaxing any
  leg requires allow_relax + a recorded reason (the F5 gate audits
  the reason against a fresh verdict run).
- Machine-written only; versions chain via prev_sha256.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from cryptobot.execution.fill_realism import PaperFillParams

GENESIS_SHA = "0" * 64


def _read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _quantile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        raise ValueError("no observations")
    idx = min(len(sorted_values) - 1, int(math.ceil(pct * len(sorted_values))) - 1)
    return sorted_values[max(0, idx)]


def fit_cost_model(observation_files: list[str | Path],
                   drift_files: list[str | Path], *,
                   current: dict[str, Any] | None = None,
                   allow_relax: bool = False,
                   relax_reason: str | None = None,
                   now_utc: str) -> dict[str, Any]:
    """Fit a new cost-model version (pure; CLI wraps IO)."""
    realized: list[float] = []
    latencies: list[float] = []
    sources: set[str] = set()
    for path in observation_files:
        for row in _read_jsonl(path):
            try:
                realized.append(float(row["realized_slip_bps"]))
            except (KeyError, TypeError, ValueError):
                continue
            sources.add(str(row.get("source", "unknown")))
            try:
                latencies.append(float(row["latency_ms"]))
            except (KeyError, TypeError, ValueError):
                continue
    n_drift = 0
    for path in drift_files:
        for row in _read_jsonl(path):
            n_drift += 1
            sources.add("paper:fills_drift")
            try:
                value = row.get("dispatch_ms")
                if value is not None:
                    latencies.append(float(value))
            except (TypeError, ValueError):
                continue
    base = PaperFillParams.default_pessimistic().to_dict()
    if current is not None:
        base.update({k: v for k, v in dict(current.get("params", {})).items()
                     if k in base})
    stats: dict[str, Any] = {
        "n_realized": len(realized), "n_latency": len(latencies),
        "n_drift_rows": n_drift, "sources": sorted(sources)}
    fitted = dict(base)
    if realized:
        realized.sort()
        p90 = _quantile(realized, 0.90)
        stats["p90_realized_slip_bps"] = p90
        fitted["slippage_bps"] = p90
    if latencies:
        latencies.sort()
        p95 = _quantile(latencies, 0.95)
        stats["p95_latency_ms"] = p95
        fitted["latency_ms_p95"] = int(round(p95))
    relax_refused: list[str] = []
    if current is not None and not allow_relax:
        previous = dict(current.get("params", {}))
        for leg in ("spread_bps", "slippage_bps", "latency_ms_p95",
                    "latency_bps", "empty_book_bps"):
            if float(fitted.get(leg, 0.0)) < float(previous.get(leg, 0.0)):
                fitted[leg] = previous[leg]
                relax_refused.append(leg)
    if allow_relax and not relax_reason:
        raise ValueError("allow_relax requires relax_reason")
    version = int(current.get("version", 0)) + 1 if current else 1
    prev_sha = str(current.get("document_sha256", GENESIS_SHA)) \
        if current else GENESIS_SHA
    fitted["provenance"] = "MEASURED"
    fitted["source"] = ",".join(sorted(sources)) or "none"
    fitted["asof_utc"] = now_utc
    # Validate the fitted params load (fail closed on bad shapes).
    PaperFillParams.from_dict(dict(fitted))
    doc: dict[str, Any] = {
        "tool": "calibrate", "version": version, "prev_sha256": prev_sha,
        "params": fitted, "fit_stats": stats,
        "relax_refused": relax_refused, "asof_utc": now_utc}
    if allow_relax:
        doc["relax_reason"] = relax_reason
    doc["document_sha256"] = hashlib.sha256(
        json.dumps(doc, sort_keys=True).encode()).hexdigest()
    return doc
