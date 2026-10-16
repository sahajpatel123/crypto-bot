#!/usr/bin/env python3
"""Vision archive fetcher — $0 Binance Vision monthly zips with provenance.

Follows the repo's fetch-verify pattern (datasets/prepare_benchmark_30d.py):
retry on transient errors, sha256 every artifact, record provenance JSON per
file, record absent (404) sources explicitly instead of failing silently.
Read-only market archives; no credentials, no orders.

Usage:
  python tools/vision_fetch.py --manifest reports/pivot/study03-fetch.json \
      --out data/vision
The manifest lists {name, url} entries; output is <out>/<name>.zip plus
<out>/<name>.provenance.json. Re-running skips files whose sha256 matches.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def _http_get(url: str, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": "cryptobot-study03-vision-fetch"})
    last: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status} for {url}")
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise  # absent source: recorded, not retried
            last = exc
        except Exception as exc:  # transient network — retry
            last = exc
    raise RuntimeError(f"GET failed after retries: {url}: {last}")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _csv_rows(zip_bytes: bytes) -> list[list[str]]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [n for n in zf.namelist() if n.endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"expected one csv in zip, got {names}")
        with zf.open(names[0]) as fh:
            import csv
            return list(csv.reader(io.TextIOWrapper(fh, encoding="utf-8")))


def fetch_one(name: str, url: str, out_dir: Path) -> dict:
    """Fetch one zip; return its provenance record (idempotent on sha match)."""
    dest = out_dir / f"{name}.zip"
    prov_path = out_dir / f"{name}.provenance.json"
    if dest.exists() and prov_path.exists():
        old = json.loads(prov_path.read_text())
        if old.get("status") == "present" and \
                old.get("sha256") == _sha256(dest.read_bytes()):
            return old
    record: dict = {"name": name, "url": url,
                    "fetched_utc": datetime.now(timezone.utc).isoformat()}
    try:
        body = _http_get(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            record.update(status="absent", http_status=404)
            prov_path.write_text(json.dumps(record, indent=1))
            return record
        raise
    record.update(status="present", http_status=200,
                  sha256=_sha256(body), bytes=len(body))
    try:
        record["csv_rows"] = max(0, len(_csv_rows(body)) - 1)  # minus header
    except Exception as exc:  # malformed zip: keep bytes, flag it
        record["csv_rows"] = None
        record["parse_error"] = str(exc)
    dest.write_bytes(body)
    prov_path.write_text(json.dumps(record, indent=1))
    return record


def build_manifest() -> list[dict]:
    """The frozen STUDY-03 fetch list (prereg 16c614d)."""
    FU = "https://data.binance.vision/data/futures/um"
    SP = "https://data.binance.vision/data/spot"
    months = ["2026-06", "2026-07", "2026-08"]
    armB = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ZECUSDT",
            "NEARUSDT", "STRKUSDT", "XRPUSDT", "WUSDT"]
    entries: list[dict] = []
    for m in months:
        for s in armB:
            entries.append({
                "name": f"futures-1m-{s}-{m}",
                "url": f"{FU}/monthly/klines/{s}/1m/{s}-1m-{m}.zip"})
            entries.append({
                "name": f"funding-{s}-{m}",
                "url": f"{FU}/monthly/fundingRate/{s}/{s}-fundingRate-{m}.zip"})
        for s in ("BTCUSDT", "ETHUSDT"):
            entries.append({
                "name": f"spot-1m-{s}-{m}",
                "url": f"{SP}/monthly/klines/{s}/1m/{s}-1m-{m}.zip"})
    # supplementary basis window (prior-use labeled): benchmark months
    for m in ("2026-09", "2026-10"):
        for s in ("BTCUSDT", "ETHUSDT"):
            entries.append({
                "name": f"spot-1m-{s}-{m}",
                "url": f"{SP}/monthly/klines/{s}/1m/{s}-1m-{m}.zip"})
    return entries


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path("data/vision"))
    ap.add_argument("--manifest-out", type=Path, default=None,
                    help="write the fetch report JSON here")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    report = []
    for e in build_manifest():
        rec = fetch_one(e["name"], e["url"], args.out)
        report.append(rec)
        status = rec.get("status", "?")
        rows = rec.get("csv_rows")
        print(f"{status:>8} {e['name']:>28} rows={rows}")
    if args.manifest_out:
        args.manifest_out.write_text(json.dumps({
            "fetched_utc": datetime.now(timezone.utc).isoformat(),
            "entries": report}, indent=1))
    absent = [r["name"] for r in report if r.get("status") == "absent"]
    print(f"TOTAL {len(report)} entries, {len(absent)} absent: {absent}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
