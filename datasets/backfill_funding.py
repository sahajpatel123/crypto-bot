"""Backfill funding-rate months from the public REST history (W2, 24H).

Fills months the vision archive has not published yet (e.g. the current
month) from GET /fapi/v1/fundingRate (no auth). Output matches the vision
raw layout (``{SYM}/funding/{SYM}-fundingRate-{YYYY-MM}.zip`` with a
``calc_time,funding_interval_hours,last_funding_rate`` CSV) so a re-freeze
consumes it unchanged; every file carries a ``.provenance.json`` sidecar
naming the endpoint, parameters, fetch times, and response hashes.

Honesty rules:
- Each claimed row traces to an HTTP 200 response record (row provenance
  embedded per file); nothing is invented or interpolated.
- A month file holds ONLY settlements whose fundingTime falls in that
  month — never borrowed across months, so future settlements cannot
  leak into earlier predictions through the file layout.
- The vision ``calc_time`` convention is verified empirically on overlap
  months: each vision row must match exactly one REST settlement within
  60 s, and rates must agree exactly (the measured fundingTime-vs-calc
  latency range is recorded in provenance).
- Availability is verified per symbol (no gap > 2x interval, range
  endpoints covered) before success is claimed; violations fail loudly.

Usage:
    python datasets/backfill_funding.py --symbols BTCUSDT,ETHUSDT \\
        --start 2026-09-01 --end 2026-10-12 --out /tmp/funding-backfill \\
        --vision-raw /path/to/data/bench30d/raw
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

REST_BASE = "https://fapi.binance.com"
_FUNDING_PATH = "fapi/v1/fundingRate"
_INFO_PATH = "fapi/v1/fundingInfo"
_PAGE_LIMIT = 1000
_POLITE_S = 0.25
_MAX_RETRIES = 5

__all__ = [
    "fetch_funding_history",
    "fetch_interval_hours",
    "month_of",
    "reconcile_month",
    "vision_latency_range_ms",
    "write_month_zip",
]


def _get_json(url: str) -> tuple[object, str]:
    """GET with backoff on 429/418/5xx; returns (payload, sha256 of body)."""
    last: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "cryptobot-backfill/0.1"})
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                body = resp.read()
            return json.loads(body.decode("utf-8")), hashlib.sha256(body).hexdigest()
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in (418, 429, 500, 502, 503, 504):
                raise
        except (OSError, ValueError) as exc:
            last = exc
        time.sleep(2.0 ** attempt)
    raise RuntimeError(f"GET failed after {_MAX_RETRIES} retries: {url} ({last})")


def fetch_funding_history(symbol: str, start_ms: int,
                          end_ms: int) -> tuple[list[dict], list[str]]:
    """All settlements in [start_ms, end_ms]; returns (rows, body_shas)."""
    rows: list[dict] = []
    shas: list[str] = []
    cursor = start_ms
    while True:
        params = urllib.parse.urlencode({
            "symbol": symbol, "startTime": cursor, "endTime": end_ms,
            "limit": _PAGE_LIMIT})
        payload, sha = _get_json(f"{REST_BASE}/{_FUNDING_PATH}?{params}")
        shas.append(sha)
        if not isinstance(payload, list):
            raise RuntimeError(f"unexpected fundingRate payload: {payload!r}"[:200])
        fresh = [r for r in payload if int(r["fundingTime"]) >= cursor]
        if not fresh:
            break
        rows.extend(fresh)
        if len(payload) < _PAGE_LIMIT:
            break
        cursor = int(fresh[-1]["fundingTime"]) + 1
        if cursor > end_ms:
            break
        time.sleep(_POLITE_S)
    rows.sort(key=lambda r: int(r["fundingTime"]))
    return rows, shas


def fetch_interval_hours(symbol: str) -> tuple[int, str]:
    """Current fundingIntervalHours for symbol; returns (hours, body_sha)."""
    params = urllib.parse.urlencode({"symbol": symbol})
    payload, sha = _get_json(f"{REST_BASE}/{_INFO_PATH}?{params}")
    if not isinstance(payload, list) or not payload:
        raise RuntimeError(f"unexpected fundingInfo payload: {payload!r}"[:200])
    return int(payload[0]["fundingIntervalHours"]), sha


def month_of(funding_ms: int) -> str:
    return datetime.fromtimestamp(funding_ms / 1000,
                                  tz=timezone.utc).strftime("%Y-%m")


def _read_vision_month(path: Path) -> list[tuple[int, int, str]]:
    """Vision monthly funding CSV -> (calc_time, interval_h, rate_str)."""
    with zipfile.ZipFile(path) as zf:
        name = zf.namelist()[0]
        text = zf.read(name).decode("utf-8")
    rows = list(csv.reader(io.StringIO(text)))
    header, body = rows[0], rows[1:]
    ci, hi, ri = (header.index("calc_time"),
                  header.index("funding_interval_hours"),
                  header.index("last_funding_rate"))
    return [(int(r[ci]), int(r[hi]), r[ri]) for r in body]


_MATCH_WINDOW_MS = 60_000


def vision_latency_range_ms(rest_rows: list[dict],
                            vision_rows: list[tuple[int, int, str]]
                            ) -> tuple[int, int]:
    """Measured (min, max) of vision calc_time - REST fundingTime.

    Vision stamps each row when its calc ran (a few ms after settlement);
    the latency varies per row, so no single offset exists. Every vision
    row must match exactly one REST settlement within 60 s, else fail.
    """
    fundings = sorted(int(r["fundingTime"]) for r in rest_rows)
    latencies = set()
    for calc, _hours, _rate in vision_rows:
        near = [f for f in fundings if abs(calc - f) < _MATCH_WINDOW_MS]
        if len(near) != 1:
            raise ValueError(
                f"vision calc_time {calc} matches {len(near)} REST settlements")
        latencies.add(calc - near[0])
    if not latencies:
        raise ValueError("no vision rows to measure latency")
    return min(latencies), max(latencies)


def reconcile_month(rest_rows: list[dict],
                    vision_rows: list[tuple[int, int, str]]) -> dict:
    """Exact settlement reconciliation; mismatches is [] when clean.

    Matches each vision row to its unique REST settlement within 60 s,
    then compares rates exactly (Decimal) both directions; any unmatched
    row on either side is a mismatch.
    """
    fundings = sorted(int(r["fundingTime"]) for r in rest_rows)
    by_funding = {int(r["fundingTime"]): r for r in rest_rows}
    problems: list[str] = []
    seen: set[int] = set()
    for calc, _hours, rate in vision_rows:
        near = [f for f in fundings if abs(calc - f) < _MATCH_WINDOW_MS]
        if len(near) != 1:
            problems.append(f"vision calc_time {calc} matches "
                            f"{len(near)} REST settlements")
            continue
        funding = near[0]
        seen.add(funding)
        row = by_funding[funding]
        if Decimal(str(row["fundingRate"])) != Decimal(rate):
            problems.append(
                f"rate mismatch fundingTime {funding}: rest={row['fundingRate']} vision={rate}")
    for funding in fundings:
        if funding not in seen:
            problems.append(f"REST settlement {funding} missing from vision month")
    return {"mismatches": problems, "rest_rows": len(rest_rows),
            "vision_rows": len(vision_rows)}


def write_month_zip(dest: Path, symbol: str, month: str,
                    rows: list[dict], interval_h: int) -> tuple[int, str]:
    """Vision-layout zip for one month; returns (rows, sha256). Guards months.

    ``calc_time`` is the REST fundingTime verbatim (venue settlement time);
    vision's per-row calc latency (measured on overlap, see provenance) is
    NOT replicated — backfilled months state their convention explicitly.
    """
    for row in rows:
        if month_of(int(row["fundingTime"])) != month:
            raise ValueError(f"settlement {row['fundingTime']} outside {month}")
    inner = f"{symbol}-fundingRate-{month}.csv"
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["calc_time", "funding_interval_hours", "last_funding_rate"])
    for row in sorted(rows, key=lambda r: int(r["fundingTime"])):
        writer.writerow([int(row["fundingTime"]), interval_h,
                         str(row["fundingRate"])])
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(inner, buf.getvalue())
    with open(dest, "rb") as fh:
        return len(rows), hashlib.sha256(fh.read()).hexdigest()


def _verify_coverage(symbol: str, rows: list[dict], start_ms: int,
                     end_ms: int, interval_h: int,
                     now_ms: int | None = None) -> list[str]:
    """Availability proof: endpoints covered, no gap > 2x interval.

    The trailing edge clamps to now: settlements in the future cannot
    exist yet, so only elapsed time must be covered.
    """
    gaps: list[str] = []
    if not rows:
        return [f"{symbol}: zero settlements in range (venue returned none)"]
    if now_ms is None:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    times = sorted(int(r["fundingTime"]) for r in rows)
    step = interval_h * 3_600_000
    if times[0] - start_ms > step:
        gaps.append(f"{symbol}: first settlement {times[0]} >1 interval after start")
    horizon = min(end_ms, now_ms)
    if horizon - times[-1] > step:
        gaps.append(f"{symbol}: last settlement {times[-1]} >1 interval "
                    f"before elapsed horizon {horizon}")
    for prev, cur in zip(times, times[1:]):
        if cur - prev > 2 * step:
            gaps.append(f"{symbol}: gap {prev} -> {cur} ({(cur - prev) // 3_600_000}h)")
    return gaps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", required=True,
                        help="comma-separated, e.g. BTCUSDT,ETHUSDT")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD (UTC, incl.)")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD (UTC, incl.)")
    parser.add_argument("--out", required=True, help="output dir (raw layout)")
    parser.add_argument("--vision-raw", default="",
                        help="vision raw dir for overlap reconcile (optional)")
    args = parser.parse_args(argv)
    start_ms = int(datetime.strptime(args.start, "%Y-%m-%d").replace(
        tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = (int(datetime.strptime(args.end, "%Y-%m-%d").replace(
        tzinfo=timezone.utc).timestamp() * 1000) + 86_400_000 - 1)
    out = Path(args.out)
    vision_raw = Path(args.vision_raw) if args.vision_raw else None

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    fetched_at = datetime.now(timezone.utc).isoformat()
    report: dict = {"fetched_at": fetched_at, "start": args.start,
                    "end": args.end, "symbols": {}, "reconcile": {},
                    "coverage_gaps": [], "files": []}
    failures: list[str] = []
    for symbol in symbols:
        try:
            interval_h, info_sha = fetch_interval_hours(symbol)
            rows, body_shas = fetch_funding_history(symbol, start_ms, end_ms)
        except Exception as exc:  # noqa: BLE001 - report, fail loudly below.
            failures.append(f"{symbol}: {type(exc).__name__}: {exc}")
            continue
        report["symbols"][symbol] = {
            "interval_h": interval_h, "interval_src": "rest:v1/fundingInfo",
            "interval_sha": info_sha, "settlements": len(rows),
            "first_funding_ms": int(rows[0]["fundingTime"]) if rows else None,
            "last_funding_ms": int(rows[-1]["fundingTime"]) if rows else None,
            "body_shas": body_shas}
        report["coverage_gaps"].extend(
            _verify_coverage(symbol, rows, start_ms, end_ms, interval_h))
        by_month: dict[str, list[dict]] = {}
        for row in rows:
            by_month.setdefault(month_of(int(row["fundingTime"])), []).append(row)
        # Latency range + reconcile on overlap months before writing new ones.
        latency: tuple[int, int] | None = None
        for month in sorted(by_month):
            vision_zip = (vision_raw / symbol / "funding" /
                          f"{symbol}-fundingRate-{month}.zip") if vision_raw else None
            if vision_zip is not None and vision_zip.exists():
                vision_rows = _read_vision_month(vision_zip)
                if [t for t, _, _ in vision_rows] != sorted(
                        t for t, _, _ in vision_rows):
                    failures.append(f"{symbol} {month}: vision month unsorted")
                    continue
                month_rest = [r for r in by_month[month]]
                try:
                    latency = vision_latency_range_ms(month_rest, vision_rows)
                except ValueError as exc:
                    failures.append(f"{symbol} {month}: {exc}")
                    continue
                rec = reconcile_month(month_rest, vision_rows)
                rec["vision_latency_ms"] = list(latency)
                report["reconcile"][f"{symbol}/{month}"] = rec
                if rec["mismatches"]:
                    failures.append(
                        f"{symbol} {month}: {len(rec['mismatches'])} mismatches; "
                        f"first: {rec['mismatches'][0]}")
        if latency is None:
            failures.append(
                f"{symbol}: no overlap month to verify vision convention")
            continue
        for month in sorted(by_month):
            vision_zip = (vision_raw / symbol / "funding" /
                          f"{symbol}-fundingRate-{month}.zip") if vision_raw else None
            if vision_zip is not None and vision_zip.exists():
                print(f"skip {symbol} {month}: vision month present "
                      f"(reconcile-only)", flush=True)
                continue
            dest = (out / symbol / "funding" /
                    f"{symbol}-fundingRate-{month}.zip")
            n, sha = write_month_zip(dest, symbol, month, by_month[month],
                                     interval_h)
            prov = {"endpoint": f"{REST_BASE}/{_FUNDING_PATH}",
                    "symbol": symbol, "month": month, "rows": n,
                    "sha256": sha, "fetched_at": fetched_at,
                    "calc_time_convention": "REST fundingTime verbatim "
                                            "(venue settlement time; vision adds "
                                            f"{latency[0]}..{latency[1]}ms calc latency "
                                            "measured on overlap, not replicated)",
                    "interval_h": interval_h,
                    "interval_src": "rest:v1/fundingInfo (current config)",
                    "response_shas": body_shas,
                    "settlements": [
                        {"fundingTime": int(r["fundingTime"]),
                         "fundingRate": str(r["fundingRate"]),
                         "markPrice": str(r.get("markPrice")),
                         "rateType": str(r.get("rateType"))}
                        for r in sorted(by_month[month],
                                        key=lambda r: int(r["fundingTime"]))]}
            dest.with_suffix(".zip.provenance.json").write_text(
                json.dumps(prov, indent=1), encoding="utf-8")
            report["files"].append({"local": str(dest.relative_to(out)),
                                    "sha256": sha, "rows": n})
            print(f"wrote {dest} ({n} rows)", flush=True)
    report["failures"] = failures
    (out / "backfill_report.json").write_text(json.dumps(report, indent=1),
                                              encoding="utf-8")
    for gap in report["coverage_gaps"]:
        print(f"COVERAGE-GAP: {gap}", flush=True)
    for failure in failures:
        print(f"FAILURE: {failure}", flush=True)
    if failures or report["coverage_gaps"]:
        return 1
    print("backfill verified: availability + reconcile clean", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
