#!/usr/bin/env python3
"""Merge staged REST funding backfill into a benchmark freeze (W3, DEEP-D5).

Consumes ``datasets/funding_backfill/`` month zips (fetched by
``backfill_funding.py`` with reconcile + provenance) into an existing
freeze directory: verifies staged zips against ``backfill_report.json``,
writes funding parquets, re-joins the affected markPrice day parquets
with the full funding terms, drops resolved ``funding-terms-absent``
gaps, and regenerates the manifest (new sha) WITHOUT hand edits: all
conversion/join/manifest steps reuse ``prepare_benchmark_30d`` helpers.

Staged months carry ``url = rest-staged:...`` + notes pointing at the
provenance sidecars (never a fake vision URL). Symbols without staged
months keep NULL funding + status (explicit, never zero).

Usage:
    python datasets/merge_funding_backfill.py --freeze datasets
    # re-runnable: skips months already merged (derived sha match).
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tomllib
import zipfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_benchmark_30d as P  # noqa: E402


def _zip_rows(path: Path) -> list[list[str]]:
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if n.endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"expected one csv in {path}, got {names}")
        with zf.open(names[0]) as fh:
            text = io.TextIOWrapper(fh, encoding="utf-8")
            import csv
            return list(csv.reader(text))


def _read_terms(parquet: Path) -> list[tuple[int, int, float]]:
    import pyarrow.parquet as pq
    table = pq.read_table(str(parquet), columns=["ts_ms", "interval_h", "rate"])
    cols = table.to_pydict()
    return list(zip(cols["ts_ms"], cols["interval_h"], cols["rate"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", required=True,
                        help="freeze dir holding benchmark_30d.toml + cache/")
    parser.add_argument("--backfill", default=None,
                        help="staged backfill dir (default: <freeze>/../datasets/funding_backfill)")
    args = parser.parse_args()

    freeze = Path(args.freeze)
    manifest_path = freeze / "benchmark_30d.toml"
    manifest = tomllib.loads(manifest_path.read_bytes().decode("utf-8"))
    old_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    backfill = (Path(args.backfill) if args.backfill
                else Path(__file__).resolve().parent / "funding_backfill")
    report = json.loads((backfill / "backfill_report.json").read_text())
    expected = {(f["local"], f["sha256"], f["rows"]) for f in report["files"]}

    dataset = manifest["dataset"]
    symbols = list(dataset["symbols"])
    sources: list[dict] = list(manifest.get("source", []))
    gaps: list[dict] = list(manifest.get("gap", []))
    by_key = {(s.get("symbol"), s.get("day"), s.get("month"), s.get("channel")): s
              for s in sources}

    merged_months: list[str] = []
    for local, sha, rows in sorted(expected):
        staged = backfill / local
        parts = Path(local).parts  # {SYM}/funding/{SYM}-fundingRate-{YYYY-MM}.zip
        symbol, month = parts[0], parts[2].rsplit("-", 3)[-2] + "-" + parts[2].rsplit("-", 3)[-1].split(".")[0]
        got = hashlib.sha256(staged.read_bytes()).hexdigest()
        if got != sha:
            print(f"STAGED SHA MISMATCH {local}: {got} != {sha}", file=sys.stderr)
            return 2
        csv_rows = _zip_rows(staged)
        if len(csv_rows) - 1 != rows:
            print(f"STAGED ROW MISMATCH {local}: {len(csv_rows)-1} != {rows}",
                  file=sys.stderr)
            return 2
        terms = P._convert_funding(csv_rows)
        parquet = freeze / "cache" / f"symbol={symbol}" / "funding" / f"{month}.parquet"
        cols = {"ts_ms": [c for c, _, _ in terms],
                "interval_h": [h for _, h, _ in terms],
                "rate": [r for _, _, r in terms]}
        n = P._to_parquet(parquet, cols)
        key = (symbol, None, month, "fundingRate")
        entry = {"symbol": symbol, "month": month, "channel": "fundingRate",
                 "url": f"rest-staged:fapi/v1/fundingRate:{symbol}:{month}",
                 "sha256": sha,
                 "local": str(parquet.relative_to(freeze)),
                 "derived_sha256": P._file_sha256(parquet),
                 "rows": n, "bytes": staged.stat().st_size,
                 "ts_min_ms": cols["ts_ms"][0], "ts_max_ms": cols["ts_ms"][-1],
                 "notes": ("REST backfill staged " + report["fetched_at"]
                           + f"; reconcile clean; see funding_backfill/{symbol}/"
                           + "funding/*.provenance.json")}
        if key in by_key and by_key[key].get("derived_sha256") == entry["derived_sha256"]:
            print(f"  {symbol} {month}: already merged, skip")
            continue
        if key in by_key:
            sources.remove(by_key[key])
        sources.append(entry)
        by_key[key] = entry
        merged_months.append(f"{symbol}/{month}")

        # Re-join every markPrice day of this symbol with full terms.
        all_terms: list[tuple[int, int, float]] = []
        for fund_pq in sorted((freeze / "cache" / f"symbol={symbol}" / "funding").glob("*.parquet")):
            all_terms.extend(_read_terms(fund_pq))
        all_terms.sort()
        rejoined = 0
        for entry_day in [s for s in sources
                          if s.get("symbol") == symbol and s.get("channel") == "markPrice"]:
            day = entry_day["day"]
            raw_zip = freeze / "raw" / symbol / day / f"{symbol}-1m-{day}.zip"
            marks = P._convert_marks(P._csv_rows(raw_zip.read_bytes()))
            dest = freeze / entry_day["local"]
            n, ts_min, ts_max, terms_absent = P._join_marks(marks, all_terms, dest)
            entry_day["derived_sha256"] = P._file_sha256(dest)
            entry_day["rows"] = n
            entry_day["ts_min_ms"] = ts_min
            entry_day["ts_max_ms"] = ts_max
            rejoined += 1
            if not terms_absent:
                gaps = [g for g in gaps
                        if not (g.get("symbol") == symbol and g.get("day") == day
                                and g.get("reason") == "funding-terms-absent")]
        print(f"  {symbol} {month}: {len(all_terms)} terms total, "
              f"rejoined {rejoined} markPrice days")

    if not merged_months:
        print("nothing to merge (all staged months already merged)")
        return 0

    # Regenerate the manifest; preserve the frozen-assumed filter profile
    # and its fetch timestamp (filters are NOT re-fetched by a merge).
    filters_url = manifest["filters"]["source"]
    filters = {sym: dict(manifest["filters"]["symbols"].get(sym, {}))
               for sym in symbols}
    old_fetched = manifest["filters"]["fetched_utc"]
    old_created = dataset["created_utc"]
    P._write_manifest(manifest_path, symbols=tuple(symbols), sources=sources,
                      gaps=gaps, filters=filters, filters_url=filters_url)
    text = manifest_path.read_text(encoding="utf-8")
    fresh_fetched = None
    for line in text.splitlines():
        if line.startswith("fetched_utc = "):
            fresh_fetched = line
    assert fresh_fetched is not None
    text = text.replace(fresh_fetched,
                        f'fetched_utc = "{old_fetched}"  # carried (merge does not re-fetch filters)')
    manifest_path.write_text(text, encoding="utf-8")
    tomllib.loads(manifest_path.read_bytes().decode("utf-8"))
    new_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    print(f"merge: {', '.join(merged_months)}")
    print(f"manifest {old_sha[:8]} (created {old_created}) -> "
          f"{new_sha[:8]} ({manifest_path})")
    print(f"sources={len(sources)} gaps={len(gaps)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
