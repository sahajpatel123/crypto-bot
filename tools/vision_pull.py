#!/usr/bin/env python3
"""E1.2: resumable, checksummed pull of Binance Vision UM public data.

Subcommands:
  plan   --datasets ... --out plan.json [--symbols-file ...]
  pull   --plan plan.json --dev-dir data/lake/raw --holdout-dir \
         data/lake/holdout_raw --workers 8 --disk-floor-gb 10 \
         --state pull-state.json
  verify --state pull-state.json
  report --plan plan.json --state pull-state.json --out report.json
  rest-tail --symbols ... --out-dir data/lake/holdout_raw/rest_tail

Split rule (SPLIT.md, filename dates only, no content decode):
  monthly YYYY-MM < 2024-01 -> dev, else holdout
  daily   YYYY-MM-DD < 2024-01-01 -> dev, else holdout
  1m leg is DEV-only (holdout months skipped, never downloaded).

Every zip is verified against its sibling .CHECKSUM (sha256) before it
is moved into place. Failures are recorded, never silent. Downloads
resume from the state file. A disk floor stops the pull cleanly.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import io
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

VISION = "https://data.binance.vision"
S3LIST = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
FAPI = "https://fapi.binance.com"
CUTOFF_MONTH = "2024-01"
CUTOFF_DAY = "2024-01-01"

MONTH_RE = re.compile(r"(\d{4}-\d{2})(?:\.zip)?$")
DAY_RE = re.compile(r"(\d{4}-\d{2}-\d{2})(?:\.zip)?$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# -- split (pure, tested) ----------------------------------------------------
def split_of(filename: str, *, dev_only: bool = False) -> str:
    """SPLIT.md assignment from filename date. Never reads content."""
    m = DAY_RE.search(filename)
    if m:
        side = "dev" if m.group(1) < CUTOFF_DAY else "holdout"
    else:
        m = MONTH_RE.search(filename)
        if not m:
            raise ValueError(f"no YYYY-MM[-DD] date in {filename!r}")
        side = "dev" if m.group(1) < CUTOFF_MONTH else "holdout"
    if side == "holdout" and dev_only:
        return "skip"
    return side


# -- S3 listing ----------------------------------------------------------------
def _http_get(url: str, timeout: float = 30.0,
              retries: int = 3) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "cryptobot-edge-pull/1"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001 — retry then raise
            last = exc
            time.sleep(min(2.0 ** attempt, 8.0) * (0.5 + attempt * 0.25))
    assert last is not None
    raise last


def s3_list_keys(prefix: str, *, delimiter: str | None = None,
                 max_keys: int = 1000) -> tuple[list[dict], list[str]]:
    """(contents[{Key,Size}], prefixes[]) for an S3 prefix, paginated."""
    contents: list[dict] = []
    prefixes: list[str] = []
    token: str | None = None
    while True:
        q = {"list-type": "2", "prefix": prefix, "max-keys": str(max_keys)}
        if delimiter:
            q["delimiter"] = delimiter
        if token:
            q["continuation-token"] = token
        url = S3LIST + "?" + urllib.parse.urlencode(q)
        root = ET.fromstring(_http_get(url))
        ns = "{http://s3.amazonaws.com/doc/2006-03-01/}"
        for c in root.findall(f"{ns}Contents"):
            key = c.findtext(f"{ns}Key") or ""
            size = int(c.findtext(f"{ns}Size") or "0")
            contents.append({"Key": key, "Size": size})
        for p in root.findall(f"{ns}CommonPrefixes"):
            prefixes.append(p.findtext(f"{ns}Prefix") or "")
        if (root.findtext(f"{ns}IsTruncated") or "").lower() != "true":
            break
        token = root.findtext(f"{ns}NextContinuationToken")
        if not token:
            break
    return contents, prefixes


def list_symbols(dataset: str, cadence: str = "monthly") -> list[str]:
    """Symbols under data/futures/um/<cadence>/<dataset>/ (delimiter walk)."""
    _, prefixes = s3_list_keys(f"data/futures/um/{cadence}/{dataset}/",
                               delimiter="/")
    out = []
    for p in prefixes:
        seg = p.rstrip("/").rsplit("/", 1)[-1]
        if seg:
            out.append(seg)
    return sorted(set(out))


# -- plan ----------------------------------------------------------------------
DATASETS = ("klines", "markPriceKlines", "premiumIndexKlines", "fundingRate",
            "metrics")


def build_plan(datasets: list[str], *, symbols_file: str | None = None,
               intervals: dict[str, list[str]] | None = None,
               metrics_symbols: list[str] | None = None) -> dict:
    """Enumerate exact file keys via S3 listings (never assume filenames)."""
    sym_filter: set[str] | None = None
    if symbols_file:
        sym_filter = {ln.strip() for ln in Path(symbols_file).read_text().splitlines()
                      if ln.strip() and not ln.startswith("#")}
    intervals = intervals or {"klines": ["1d", "1h"],
                              "markPriceKlines": ["1d", "1h"],
                              "premiumIndexKlines": ["1d", "1h"]}
    jobs: list[dict] = []
    for ds in datasets:
        if ds == "fundingRate":
            syms = list_symbols("fundingRate")
            if sym_filter:
                syms = [s for s in syms if s in sym_filter]
            for sym in syms:
                contents, _ = s3_list_keys(
                    f"data/futures/um/monthly/fundingRate/{sym}/")
                for c in contents:
                    if c["Key"].endswith(".zip") and ".CHECKSUM" not in c["Key"]:
                        jobs.append(_job(ds, sym, None, c))
        elif ds == "metrics":
            syms = metrics_symbols or list_symbols("metrics", "daily")
            if sym_filter:
                syms = [s for s in syms if s in sym_filter]
            for sym in syms:
                contents, _ = s3_list_keys(
                    f"data/futures/um/daily/metrics/{sym}/")
                for c in contents:
                    if c["Key"].endswith(".zip") and ".CHECKSUM" not in c["Key"]:
                        jobs.append(_job(ds, sym, None, c))
        else:
            for iv in intervals.get(ds, ["1d"]):
                syms = list_symbols(ds)
                if sym_filter:
                    syms = [s for s in syms if s in sym_filter]
                dev_only = (ds == "klines" and iv == "1m")
                for sym in syms:
                    contents, _ = s3_list_keys(
                        f"data/futures/um/monthly/{ds}/{sym}/{iv}/")
                    for c in contents:
                        if c["Key"].endswith(".zip") and ".CHECKSUM" not in c["Key"]:
                            jobs.append(_job(ds, sym, iv, c,
                                            dev_only=dev_only))
    return {"format": "cryptobot-vision-plan/1", "created_utc": _utc_now(),
            "cutoff_month": CUTOFF_MONTH, "cutoff_day": CUTOFF_DAY,
            "jobs": jobs,
            "total_bytes": sum(j["bytes"] for j in jobs)}


def _job(ds: str, sym: str, iv: str | None, c: dict, *,
         dev_only: bool = False) -> dict:
    key = c["Key"]
    name = key.rsplit("/", 1)[-1]
    return {"key": key, "url": f"{VISION}/{key}",
            "checksum_url": f"{VISION}/{key}.CHECKSUM",
            "dataset": ds, "symbol": sym, "interval": iv,
            "filename": name, "bytes": c["Size"],
            "split": split_of(name, dev_only=dev_only)}


# -- pull ----------------------------------------------------------------------
class PullState:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.lock = threading.Lock()
        if self.path.exists():
            self.doc = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.doc = {"format": "cryptobot-vision-pull-state/1",
                        "files": {}, "failures": {}}

    def save(self) -> None:
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.doc, sort_keys=True) + "\n")
        os.replace(tmp, self.path)

    def done(self, key: str) -> bool:
        with self.lock:
            return self.doc["files"].get(key, {}).get("status") == "ok"

    def record(self, key: str, rec: dict) -> None:
        with self.lock:
            if rec.get("status") == "ok":
                self.doc["files"][key] = rec
                self.doc["failures"].pop(key, None)
            else:
                self.doc["failures"][key] = rec


def _disk_free_gb(path: Path) -> float:
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize / 1e9


def _fetch_text(url: str) -> str:
    return _http_get(url).decode("utf-8")


def _fetch_file(url: str, dest_tmp: Path) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": "cryptobot-edge-pull/1"})
    total = 0
    with urllib.request.urlopen(req, timeout=120) as resp, \
            dest_tmp.open("wb") as fh:
        while True:
            block = resp.read(1 << 20)
            if not block:
                break
            fh.write(block)
            total += len(block)
    return total


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def pull_job(job: dict, *, dev_dir: Path, holdout_dir: Path) -> dict:
    if job["split"] == "skip":
        return {"status": "skipped", "reason": "dev-only leg"}
    base = dev_dir if job["split"] == "dev" else holdout_dir
    dest = base / job["dataset"] / (job["interval"] or "na") / job["symbol"] / job["filename"]
    if dest.exists():
        return {"status": "ok", "path": str(dest), "resumed": True,
                "bytes": dest.stat().st_size}
    last_err = ""
    for attempt in range(2):
        try:
            want = _fetch_text(job["checksum_url"]).split()[0]
            tmp = dest.parent / (job["filename"] + f".part{os.getpid()}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            _fetch_file(job["url"], tmp)
            got = _sha256_file(tmp)
            if got != want:
                tmp.unlink(missing_ok=True)
                raise ValueError(f"checksum mismatch want={want[:16]} got={got[:16]}")
            os.replace(tmp, dest)
            return {"status": "ok", "path": str(dest), "bytes": dest.stat().st_size,
                    "sha256": got, "attempts": attempt + 1}
        except Exception as exc:  # noqa: BLE001 — recorded, retried once
            last_err = f"{type(exc).__name__}: {exc}"
            time.sleep(1.0 + attempt * 2.0)
    return {"status": "failed", "error": last_err}


def cmd_pull(args: argparse.Namespace) -> int:
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    state = PullState(args.state)
    dev_dir = Path(args.dev_dir)
    holdout_dir = Path(args.holdout_dir)
    dev_dir.mkdir(parents=True, exist_ok=True)
    holdout_dir.mkdir(parents=True, exist_ok=True)
    jobs = [j for j in plan["jobs"] if not state.done(j["key"])]
    print(f"pull: {len(jobs)} pending / {len(plan['jobs'])} planned "
          f"({plan['total_bytes'] / 1e9:.2f} GB listed)")
    floor = float(args.disk_floor_gb)
    stop = threading.Event()
    done = failed = skipped = 0
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=int(args.workers)) as pool:
        futs = {pool.submit(pull_job, j, dev_dir=dev_dir,
                            holdout_dir=holdout_dir): j for j in jobs}
        for n, fut in enumerate(concurrent.futures.as_completed(futs), 1):
            if stop.is_set():
                break
            job = futs[fut]
            try:
                rec = fut.result()
            except Exception as exc:  # noqa: BLE001 — never lose a job
                rec = {"status": "failed", "error": f"worker: {exc!r}"}
            rec["finished_utc"] = _utc_now()
            state.record(job["key"], rec)
            if rec["status"] == "ok":
                done += 1
            elif rec["status"] == "skipped":
                skipped += 1
            else:
                failed += 1
            if n % 50 == 0:
                state.save()
                free = _disk_free_gb(dev_dir)
                el = time.time() - t0
                print(f"pull: {n}/{len(jobs)} ok={done} fail={failed} "
                      f"skip={skipped} free={free:.1f}GB elapsed={el:.0f}s",
                      flush=True)
                if free < floor:
                    print(f"pull: STOP disk floor {floor}GB reached "
                          f"(free={free:.1f}GB)", flush=True)
                    stop.set()
    state.save()
    print(json.dumps({"pending": len(jobs), "ok": done, "failed": failed,
                      "skipped": skipped,
                      "failures": state.doc["failures"]}, indent=1)[:4000])
    return 0 if failed == 0 else 2


def cmd_verify(args: argparse.Namespace) -> int:
    state = PullState(args.state)
    bad: list[str] = []
    checked = 0
    for key, rec in state.doc.get("files", {}).items():
        if rec.get("status") != "ok" or "path" not in rec:
            continue
        p = Path(rec["path"])
        checked += 1
        if not p.exists() or ("sha256" in rec
                              and _sha256_file(p) != rec["sha256"]):
            bad.append(key)
    print(json.dumps({"checked": checked, "bad": bad,
                      "ok": not bad}, indent=1))
    return 0 if not bad else 2


def cmd_report(args: argparse.Namespace) -> int:
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    state = PullState(args.state)
    by_symbol: dict[str, dict] = {}
    for job in plan["jobs"]:
        if job["split"] == "skip":
            continue
        cell = by_symbol.setdefault(
            f"{job['dataset']}/{job['interval']}/{job['symbol']}",
            {"expected": 0, "ok": 0, "failed": 0, "missing": []})
        cell["expected"] += 1
        rec = state.doc["files"].get(job["key"])
        if rec is not None:
            cell["ok"] += 1
        elif job["key"] in state.doc.get("failures", {}):
            cell["failed"] += 1
        else:
            cell["missing"].append(job["filename"])
    gaps = {k: v for k, v in by_symbol.items()
            if v["failed"] or v["missing"]}
    doc = {"report": "vision-pull/1", "generated_utc": _utc_now(),
           "symbols": len(by_symbol),
           "expected_files": sum(v["expected"] for v in by_symbol.values()),
           "ok_files": sum(v["ok"] for v in by_symbol.values()),
           "symbols_with_gaps": len(gaps), "gaps": gaps}
    Path(args.out).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in doc.items() if k != "gaps"}, indent=1))
    return 0


# -- REST tail (public, no keys) -------------------------------------------------
def _rest_json(url: str) -> object:
    return json.loads(_http_get(url).decode("utf-8"))


def cmd_rest_tail(args: argparse.Namespace) -> int:
    """October-2026 tail (past the monthly leg) via public REST klines."""
    syms = [s.strip().upper() for s in Path(args.symbols).read_text().splitlines()
            if s.strip() and not s.startswith("#")]
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    start_ms = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(datetime(2026, 10, 17, 23, 59, 59, tzinfo=timezone.utc).timestamp() * 1000)
    legs = {"klines_1d": "/fapi/v1/klines?interval=1d",
            "klines_1h": "/fapi/v1/klines?interval=1h",
            "mark_1d": "/fapi/v1/markPriceKlines?interval=1d",
            "mark_1h": "/fapi/v1/markPriceKlines?interval=1h",
            "premium_1d": "/fapi/v1/premiumIndexKlines?interval=1d",
            "premium_1h": "/fapi/v1/premiumIndexKlines?interval=1h"}
    meta: dict[str, dict] = {}
    for sym in syms:
        row: dict[str, object] = {}
        for leg, path in legs.items():
            url = (f"{FAPI}{path}&symbol={sym}&startTime={start_ms}"
                   f"&endTime={end_ms}&limit=1000")
            try:
                data = _rest_json(url)
                assert isinstance(data, list)
                dest = out / leg / f"{sym}.csv"
                dest.parent.mkdir(parents=True, exist_ok=True)
                with dest.open("w", newline="") as fh:
                    w = csv.writer(fh)
                    w.writerows(data)
                row[leg] = len(data)
            except Exception as exc:  # noqa: BLE001 — per-leg record
                row[leg] = f"FAILED: {type(exc).__name__}: {exc}"
            time.sleep(float(args.delay_s))
        # Funding tail (8h rows; ~51 rows, one page).
        try:
            url = (f"{FAPI}/fapi/v1/fundingRate?symbol={sym}"
                   f"&startTime={start_ms}&endTime={end_ms}&limit=1000")
            data = _rest_json(url)
            assert isinstance(data, list)
            dest = out / "funding" / f"{sym}.csv"
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["symbol", "fundingTime", "fundingRate"])
                for r in data:
                    w.writerow([r.get("symbol"), r.get("fundingTime"),
                                r.get("fundingRate")])
            row["funding"] = len(data)
        except Exception as exc:  # noqa: BLE001
            row["funding"] = f"FAILED: {type(exc).__name__}: {exc}"
        time.sleep(float(args.delay_s))
        meta[sym] = row
        if len(meta) % 25 == 0:
            print(f"rest-tail: {len(meta)}/{len(syms)}", flush=True)
    (out / "fetch_meta.json").write_text(json.dumps(
        {"fetched_utc": _utc_now(), "start": "2026-10-01",
         "end": "2026-10-17", "symbols": meta}, indent=1, sort_keys=True))
    fails = sum(1 for r in meta.values()
                for v in r.values() if str(v).startswith("FAILED"))
    print(json.dumps({"symbols": len(meta), "failed_legs": fails}))
    return 0 if fails == 0 else 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vision_pull",
                                description="Binance Vision UM pull (E1.2)")
    sub = p.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("plan")
    q.add_argument("--datasets", nargs="+", default=["klines"],
                   choices=list(DATASETS))
    q.add_argument("--intervals", nargs="*", default=[],
                   help="DATASET:IV[,IV] overrides, e.g. klines:1d,1h,1m")
    q.add_argument("--symbols-file", default=None)
    q.add_argument("--metrics-symbols", default=None,
                   help="file with metrics symbol list (daily leg)")
    q.add_argument("--out", required=True)
    q.set_defaults(func=lambda a: _cmd_plan(a))
    q = sub.add_parser("pull")
    q.add_argument("--plan", required=True)
    q.add_argument("--dev-dir", required=True)
    q.add_argument("--holdout-dir", required=True)
    q.add_argument("--workers", type=int, default=8)
    q.add_argument("--disk-floor-gb", type=float, default=10.0)
    q.add_argument("--state", required=True)
    q.set_defaults(func=cmd_pull)
    q = sub.add_parser("verify")
    q.add_argument("--state", required=True)
    q.set_defaults(func=cmd_verify)
    q = sub.add_parser("report")
    q.add_argument("--plan", required=True)
    q.add_argument("--state", required=True)
    q.add_argument("--out", required=True)
    q.set_defaults(func=cmd_report)
    q = sub.add_parser("rest-tail")
    q.add_argument("--symbols", required=True)
    q.add_argument("--out-dir", required=True)
    q.add_argument("--delay-s", type=float, default=0.2)
    q.set_defaults(func=cmd_rest_tail)
    return p


def _cmd_plan(args: argparse.Namespace) -> int:
    intervals: dict[str, list[str]] = {}
    for spec in args.intervals:
        ds, _, ivs = spec.partition(":")
        intervals[ds] = [i.strip() for i in ivs.split(",") if i.strip()]
    metrics_syms = None
    if args.metrics_symbols:
        metrics_syms = [ln.strip() for ln in
                        Path(args.metrics_symbols).read_text().splitlines()
                        if ln.strip() and not ln.startswith("#")]
    plan = build_plan(args.datasets, symbols_file=args.symbols_file,
                      intervals=intervals or None,
                      metrics_symbols=metrics_syms)
    Path(args.out).write_text(json.dumps(plan, indent=1, sort_keys=True) + "\n")
    n_dev = sum(1 for j in plan["jobs"] if j["split"] == "dev")
    n_hold = sum(1 for j in plan["jobs"] if j["split"] == "holdout")
    n_skip = sum(1 for j in plan["jobs"] if j["split"] == "skip")
    print(json.dumps({"jobs": len(plan["jobs"]), "dev": n_dev,
                      "holdout": n_hold, "skipped": n_skip,
                      "gb": round(plan["total_bytes"] / 1e9, 2)}))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
