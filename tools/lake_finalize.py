#!/usr/bin/env python3
"""E1.3/E2.2: lake DQ report, DEV-only scope lists, holdout sealing.

Subcommands (run AFTER the pass-1 pull completes):
  dq           --lake DIR --out report.json   (DEV parquet quality report)
  scope        --lake DIR --out-dir DIR       (1m top-20 + metrics symbols,
                                              DEV-only volumes, frozen lists)
  seal-holdout --holdout DIR --vault-root DIR (byte-hash manifests + seal;
                                              NEVER decodes content)

scope lists are computed from DEV data only (SPLIT.md). seal-holdout
hashes raw bytes; any decode here would poison CONFIRM eligibility.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def cmd_dq(args) -> int:
    import pandas as pd

    from cryptobot.research.lake import data_quality_report, load_dev_frames

    lake = Path(args.lake)
    syms = sorted(p.name.split("=", 1)[1] for p in
                  (lake / "klines" / "interval=1d").glob("symbol=*"))
    frames = load_dev_frames(lake, "klines", syms, interval="1d")
    rep = data_quality_report(frames, interval="1d")
    wicks = sorted(((s, r["outliers"]) for s, r in rep.items()),
                   key=lambda t: -t[1])[:20]
    gaps = sorted(((s, r["gaps"]) for s, r in rep.items()),
                  key=lambda t: -t[1])[:20]
    doc = {"report": "lake-dq/1", "generated_utc": _utc_now(),
           "symbols": len(rep),
           "total_rows": sum(r["rows"] for r in rep.values()),
           "total_gaps": sum(r["gaps"] for r in rep.values()),
           "total_outliers": sum(r["outliers"] for r in rep.values()),
           "total_dupes": sum(r["dupes_removed"] for r in rep.values()),
           "worst_gaps": gaps, "worst_outliers": wicks, "per_symbol": rep}
    Path(args.out).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in doc.items() if k != "per_symbol"},
                     indent=1))
    return 0


def cmd_scope(args) -> int:
    from cryptobot.research.lake import load_dev_frames
    from cryptobot.research.universe import eligible_universe, liquidity_table

    lake = Path(args.lake)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    syms = sorted(p.name.split("=", 1)[1] for p in
                  (lake / "klines" / "interval=1d").glob("symbol=*"))
    frames = load_dev_frames(lake, "klines", syms, interval="1d")
    liq = liquidity_table(frames)
    top20 = sorted(liq, key=lambda s: (-liq[s], s))[:20]
    (out / "m1-top20.txt").write_text("\n".join(top20) + "\n")
    # Metrics symbols: any symbol ever in the trailing top-30 during DEV
    # (weekly sampling; DEV data only).
    import pandas as pd

    all_dates = sorted({t for df in frames.values() for t in df["open_time"]})
    mondays = [d for d in all_dates if d.weekday() == 0]
    members: set[str] = set()
    for d in mondays:
        members.update(eligible_universe(d, frames, top_n=30,
                                         min_listing_age_days=90,
                                         min_quote_volume_30d=1e7))
    metrics_syms = sorted(members)
    (out / "metrics-symbols.txt").write_text("\n".join(metrics_syms) + "\n")
    doc = {"scope": "lake-scope/1", "generated_utc": _utc_now(),
           "rule": "DEV-only trailing volumes (SPLIT.md)",
           "m1_top20": top20, "n_metrics_symbols": len(metrics_syms)}
    (out / "scope.json").write_text(json.dumps(doc, indent=1) + "\n")
    print(json.dumps(doc, indent=1))
    return 0


def cmd_seal_holdout(args) -> int:
    from cryptobot.data.vault import Vault, build_holdout_manifest

    hold = Path(args.holdout)
    vault = Vault(args.vault_root)
    legs = ["klines", "markPriceKlines", "premiumIndexKlines", "fundingRate",
            "metrics", "spot", "rest_tail"]
    sealed = []
    for leg in legs:
        base = hold / leg
        if not base.exists():
            continue
        files = sorted(p for p in base.rglob("*") if p.is_file()
                       and not p.name.endswith(".tmp"))
        if not files:
            continue
        manifest = build_holdout_manifest(
            files, hold / f"HOLDOUT-{leg}.manifest.json")
        chunk = vault.seal_chunk(manifest["manifest_path"], class_="HOLDOUT",
                                 input_class="OBSERVED_PUBLIC")
        sealed.append({"leg": leg, "chunk_id": chunk.chunk_id,
                       "files": len(files), "sha256": chunk.sha256})
        print(f"sealed {leg}: {chunk.chunk_id} ({len(files)} files)")
    print(json.dumps({"sealed": sealed}, indent=1))
    return 0 if sealed else 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="lake_finalize")
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("dq")
    q.add_argument("--lake", required=True)
    q.add_argument("--out", required=True)
    q.set_defaults(func=cmd_dq)
    q = sub.add_parser("scope")
    q.add_argument("--lake", required=True)
    q.add_argument("--out-dir", required=True)
    q.set_defaults(func=cmd_scope)
    q = sub.add_parser("seal-holdout")
    q.add_argument("--holdout", required=True)
    q.add_argument("--vault-root", required=True)
    q.set_defaults(func=cmd_seal_holdout)
    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
