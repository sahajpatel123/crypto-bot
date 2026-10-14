"""X1 bench-vehicle bridge (ruled vehicle adapter, pre-outcome).

The freeze's selection/economics tools read backtest comparison +
run-dir files; the ruled bench_run vehicle emits bench reports +
checkpoint dirs instead. This bridge MECHANICALLY reshapes bench
outputs into the frozen input shapes WITHOUT changing any rule:
no selection logic, no economics logic, no thresholds here.

Per manifest cell it writes, under --out:
  <tag>/<config>_<split>.comparison.json  (one cell, frozen shape)
  <tag>/<config>_<split>.rundir/report.json   (ledger nets + costs)
  <tag>/<config>_<split>.rundir/fills.jsonl   (journal fills, exact)
  <tag>/coverage.json  (ingested vs frozen split totals, exposure)

Nets are bench booked.equity_close minus the TOML paper capital
(same capital every cell; x1_select re-verifies single opening).
Closed positions derive from journal fills (execution_ids must be
unique or the bridge BLOCKS). Reject histograms are unavailable
from bench checkpoints and record as {} with a vehicle note (they
are diagnostic; selection never reads them).

The run manifest (--manifest) is written BEFORE any round cell
runs; the bridge refuses unknown cells and run-id mismatches.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tomllib
from pathlib import Path


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _toml_value(toml_path: str, key: str) -> float:
    doc = tomllib.load(open(toml_path, "rb"))
    if key == "paper_capital_usdt":
        return float(doc["paper"]["capital_usdt"])
    if key == "taker_bps":
        return float(doc["fees"]["taker_bps"])
    raise KeyError(key)


def _extract_fills(journal_path: Path) -> list[dict]:
    """Journal fill records -> fills rows (exact, order-preserving)."""
    fills = []
    if not journal_path.exists():
        return fills
    for line in journal_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("event") != "fill":
            continue
        fills.append({
            "execution_id": record["exec_id"],
            "client_order_id": record.get("client_id"),
            "instrument": record.get("symbol"),
            "side": record.get("venue_side"),
            "qty": float(record["qty"]),
            "price": float(record["price"]),
            "fee": float(record.get("fee", 0.0)),
            "ts_utc": record.get("ts_utc"),
        })
    return fills


def _intents_count(store_path: Path, run_id: str) -> int:
    if not store_path.exists():
        return 0
    db = sqlite3.connect(f"file:{store_path}?mode=ro", uri=True)
    try:
        return db.execute(
            "SELECT COUNT(*) FROM intents WHERE run_id=?",
            (run_id,)).fetchone()[0]
    finally:
        db.close()


def _split_event_totals(splits_path: str, split: str) -> dict[str, int]:
    """Frozen per-channel row totals for a split (trades + marks)."""
    doc = tomllib.load(open(splits_path, "rb"))
    roles = {"dev": "dev", "validation": "val"}
    want = roles[split]
    totals: dict[str, int] = {}
    n_days = 0
    for entry in doc.get("split", []):
        if entry.get("role") != want:
            continue
        n_days += 1
        for cell in entry.get("coverage", []):
            if cell.get("symbol") not in ("BTCUSDT", "ETHUSDT"):
                continue
            key = str(cell.get("channel"))
            totals[key] = totals.get(key, 0) + int(cell.get("rows", 0))
    totals["days"] = n_days
    return totals


def bridge_cell(cell: dict, out_dir: Path, splits_path: str) -> dict:
    """Bridge one manifest cell; returns its coverage record."""
    for job in cell["jobs"]:
        if not Path(job["report"]).exists():
            raise ValueError(f"missing job report {job['report']}")
    reports = [_load(job["report"]) for job in cell["jobs"]]
    run_ids = {r["run_id"] for r in reports}
    if len(run_ids) != 1:
        raise ValueError(f"run-id mismatch in chain: {sorted(run_ids)}")
    run_id = next(iter(run_ids))
    final = reports[-1]
    ckpt_dir = Path(cell["ckpt_dir"])
    ckpt_file = ckpt_dir / "bench_checkpoint.json"
    if not ckpt_file.exists():
        raise ValueError(f"missing checkpoint {ckpt_file}")
    ckpt = _load(str(ckpt_file))
    if ckpt.get("run_id") != run_id:
        raise ValueError("checkpoint run-id mismatch")
    opening = _toml_value(cell["toml"], "paper_capital_usdt")
    closing = float(final["booked"]["equity_close"])
    fills = _extract_fills(ckpt_dir / "work" / "engine_journal.jsonl")
    exec_ids = [f["execution_id"] for f in fills]
    if len(set(exec_ids)) != len(exec_ids):
        raise ValueError("duplicate execution_ids in journal fills")
    rundir = out_dir / f"{cell['config_id']}_{cell['split']}.rundir"
    rundir.mkdir(parents=True, exist_ok=True)
    (rundir / "fills.jsonl").write_text(
        "".join(json.dumps(f) + "\n" for f in fills), encoding="utf-8")
    report = {
        "opening_equity": opening,
        "closing_equity": closing,
        "net_return_pct": (closing / opening - 1) * 100,
        "paid_costs": float(final["booked"]["commissions"]),
        "funding_net": float(final["booked"]["funding"]),
        "realised": float(final["booked"]["realised"]),
        "intents_admitted": _intents_count(
            ckpt_dir / "store.db", run_id),
        "reject_counts": {},
        "reject_counts_note": "unavailable from bench checkpoints "
                              "(vehicle limitation; diagnostic only)",
        "fee_schedule": {"taker_bps": _toml_value(cell["toml"],
                                                  "taker_bps")},
        "config_fingerprint": ckpt["identity"]["config_fingerprint"],
        "bridge": {"tool": "tools/x1_bench_bridge.py",
                   "bench_reports": [job["report"] for job in cell["jobs"]],
                   "bench_run_id": run_id,
                   "final_status": final["status"]},
    }
    (rundir / "report.json").write_text(
        json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    key = f"{cell['arm']}|{cell['split']}"
    comparison = {
        "dataset_manifest_sha": ckpt["identity"]["dataset"][
            "manifest_sha"],
        "splits": [cell["split"]],
        "cells": {key: {"closing_equity": closing,
                        "run_dir": str(rundir)}},
    }
    comp_path = out_dir / f"{cell['config_id']}_{cell['split']}.comparison.json"
    comp_path.write_text(
        json.dumps(comparison, indent=1, sort_keys=True) + "\n",
        encoding="utf-8")
    ingested = sum(r["events"]["ingested"] for r in reports)
    skipped = sum(r["events"].get("skipped_window", 0) for r in reports)
    totals = _split_event_totals(splits_path, cell["split"])
    denom = sum(v for k, v in totals.items() if k != "days") or 1
    exposed = bool((ckpt.get("engine") or {}).get("position")) or bool(
        (ckpt.get("engine") or {}).get("reservations"))
    return {
        "config_id": cell["config_id"], "split": cell["split"],
        "ingested_total": ingested, "skipped_window_total": skipped,
        "split_event_total": denom, "split_days": totals["days"],
        "coverage_frac": ingested / denom,
        "final_status": final["status"],
        "exposed_at_cap": exposed,
        "fills": len(fills),
    }


def bridge(manifest_path: str, out_root: str, splits_path: str) -> dict:
    manifest = _load(manifest_path)
    seen = set()
    summary: dict[str, list] = {}
    for cell in manifest["cells"]:
        key = (cell["tag"], cell["config_id"], cell["split"])
        if key in seen:
            raise ValueError(f"duplicate manifest cell {key}")
        seen.add(key)
        out_dir = Path(out_root) / cell["tag"]
        out_dir.mkdir(parents=True, exist_ok=True)
        record = bridge_cell(cell, out_dir, splits_path)
        summary.setdefault(cell["tag"], []).append(record)
    for tag, records in summary.items():
        (Path(out_root) / tag / "coverage.json").write_text(
            json.dumps({"tag": tag, "rule": "X1.md section 11",
                        "cells": sorted(records, key=lambda r: (
                            r["config_id"], r["split"]))},
                       indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return {"tags": sorted(summary),
            "cells": sum(len(v) for v in summary.values())}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--splits", required=True,
                        help="frozen splits_deep.toml (coverage totals)")
    args = parser.parse_args(argv)
    try:
        result = bridge(args.manifest, args.out, args.splits)
    except (ValueError, KeyError, FileNotFoundError) as exc:
        print(f"BLOCKED: {exc}")
        return 3
    print(f"bridged {result['cells']} cells tags={result['tags']} "
          f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
