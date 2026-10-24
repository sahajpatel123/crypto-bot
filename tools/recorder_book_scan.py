#!/usr/bin/env python3
"""Scan retained recorder full-depth snapshots for H1-style imbalance.

Usage:
  .venv/bin/python tools/recorder_book_scan.py \
      --root ../cryto-bot-edge/data/recorder \
      --out reports/data-use/H1-recorder-book-scan.json

Diagnostic only: the recorder has no aggTrade stream, so this cannot
produce fills or change any hypothesis verdict.  It answers whether the
frozen top-5 notional imbalance threshold is actually rare when the book
is full-depth, which is the input the H1 capture was supposed to provide.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cryptobot.research.book_scan import scan_recorder, scan_records  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _retained(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            record.setdefault("type", "depth_snapshot")
            rows.append(record)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT.parent / "cryto-bot-edge"
                                             / "data/recorder"))
    parser.add_argument("--out", default=str(
        ROOT / "reports/data-use/H1-recorder-book-scan.json"))
    parser.add_argument("--levels", type=int, default=5)
    parser.add_argument("--threshold", type=float, default=0.6)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    report = scan_recorder(args.root, levels=args.levels,
                           threshold=args.threshold, limit=args.limit)
    report["generated_utc"] = datetime.now(UTC).isoformat()
    report["consumer"] = "H1/H5 signal-frequency diagnostic (not a verdict)"
    report["retained_snapshots"] = {}
    for name in ("h1-accrual-01", "h5-accrual-01"):
        path = ROOT / "data/captures" / name / "depth_snapshots.jsonl"
        rows = _retained(path)
        if rows:
            report["retained_snapshots"][name] = scan_records(
                rows, levels=args.levels, threshold=args.threshold)["total"]
    report["interpretation"] = (
        "The recorder's 30 s full-depth books are not the H1 capture's 1 s "
        "event-book samples. A high signal rate here means the frozen "
        "threshold is not rare on a full book; it does not produce fills "
        "or overturn the H1 verdict, which remains UNDERPOWERED.")
    report["recommendation"] = (
        "Keep H1 UNDERPOWERED. The 7/5,962 breach count reflects the H1 "
        "capture's shallow event book, not full-depth market behavior. A "
        "future H1 re-run needs a capture that maintains full depth AND "
        "aggTrade prints; the recorder alone cannot supply fills.")
    h1_report = ROOT / "reports/hypotheses/H1.json"
    if h1_report.is_file():
        h1 = json.loads(h1_report.read_text(encoding="utf-8"))
        report["h1_verdict_reference"] = {
            "verdict": h1.get("verdict"),
            "document_sha256": h1.get("document_sha256"),
        }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, sort_keys=True, default=str)
                   + "\n")
    total = report["total"]
    print(f"book scan: chunks={report['chunks']} snapshots={total['n']} "
          f"signals>{args.threshold:g}={total['signals']} "
          f"mean_abs={total['mean_abs']}")
    for symbol, stats in report["per_symbol"].items():
        print(f"  {symbol}: n={stats['n']} signals={stats['signals']} "
              f"mean_abs={stats['mean_abs']}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
