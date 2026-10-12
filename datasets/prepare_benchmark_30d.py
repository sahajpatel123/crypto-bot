#!/usr/bin/env python3
"""Freeze the 30-accounting-day vision benchmark (W2, E-008; B5).

Downloads Binance vision archives for the frozen symbol universe, verifies
each zip against its published `.CHECKSUM`, converts channels to normalized
Parquet (``cache/symbol=<S>/date=<D>/channel=<C>/part.parquet``), joins
minute marks with funding terms, inventories gaps, freezes the venue filter
profile (labeled frozen-assumed), and writes ``benchmark_30d.toml``.

Offline replay after preparation: the reader needs only this directory.

Usage:
    python prepare_benchmark_30d.py --out /path/to/bench30d
    python prepare_benchmark_30d.py --out DIR --symbols BTCUSDT,ETHUSDT --jobs 4
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import sys
import tomllib
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

VISION = "https://data.binance.vision/data/futures/um"
# Transform versions: 1 = E-008 (minute close published at minute open —
# lookahead; zero substituted for absent funding); 2 = E-009 (close at
# close availability with open/close/availability preserved; absent
# funding is NULL + status, never zero). The reader refuses v1.
TRANSFORM_VERSION = 2
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "ZECUSDT",
           "NEARUSDT", "STRKUSDT", "XRPUSDT", "WUSDT")
DAY_START = date(2026, 9, 11)   # UTC days covering 30 IST accounting days...
DAY_END = date(2026, 10, 11)    # ...2026-09-12..2026-10-11 Asia/Kolkata.
FUNDING_MONTHS = ("2026-09", "2026-10")
AGG_GAP_MS = 300_000  # idle stretches beyond this land in the gap inventory.

DAILY_CHANNELS = {
    "aggTrade": "daily/aggTrades/{s}/{s}-aggTrades-{d}.zip",
    "markKline1m": "daily/markPriceKlines/{s}/1m/{s}-1m-{d}.zip",
}
FUNDING_PATH = "monthly/fundingRate/{s}/{s}-fundingRate-{m}.zip"


def _http_get(url: str, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "cryptobot-e009-freeze"})
    last: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status} for {url}")
                return resp.read()
        except Exception as exc:  # noqa: BLE001 (transient net/HTTP)
            last = exc
    raise RuntimeError(f"GET failed: {url}: {last}")


def _published_sha(url: str) -> str | None:
    try:
        body = _http_get(url + ".CHECKSUM", timeout=30.0).decode("utf-8").strip()
    except RuntimeError:
        return None
    return body.split()[0] if body else None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _daterange(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def _fetch_verified(url: str, dest: Path) -> tuple[bytes, str, bool]:
    """Return (zip bytes, published sha, resumed); raises when unavailable."""
    published = _published_sha(url)
    if published is None:
        raise FileNotFoundError(f"no published checksum (absent upstream): {url}")
    if dest.exists():
        existing = dest.read_bytes()
        if _sha256(existing) == published:
            return existing, published, True
    data = _http_get(url)
    if _sha256(data) != published:
        raise ValueError(f"checksum mismatch for {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return data, published, False


def _csv_rows(zip_bytes: bytes) -> list[list[str]]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [n for n in zf.namelist() if n.endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"expected one csv in zip, got {names}")
        with zf.open(names[0]) as fh:
            text = io.TextIOWrapper(fh, encoding="utf-8")
            return list(csv.reader(text))


def _to_parquet(path: Path, columns: dict[str, list]) -> int:
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.table({k: pa.array(v) for k, v in columns.items()})
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, str(path), compression="zstd")
    return table.num_rows


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _convert_agg(rows: list[list[str]], dest: Path
               ) -> tuple[int, int, int, list, list]:
    header, body = rows[0], rows[1:]
    idx = {name: header.index(name) for name in (
        "agg_trade_id", "price", "quantity", "first_trade_id",
        "last_trade_id", "transact_time", "is_buyer_maker")}
    cols: dict[str, list] = {k: [] for k in (
        "ts_ms", "agg_id", "price", "qty", "first_id", "last_id", "buyer_is_maker")}
    prev_ts = -1
    disorder = 0
    for row in body:
        ts = int(row[idx["transact_time"]])
        if ts < prev_ts:
            disorder += 1
        prev_ts = max(prev_ts, ts)
        cols["ts_ms"].append(ts)
        cols["agg_id"].append(int(row[idx["agg_trade_id"]]))
        cols["price"].append(float(row[idx["price"]]))
        cols["qty"].append(float(row[idx["quantity"]]))
        cols["first_id"].append(int(row[idx["first_trade_id"]]))
        cols["last_id"].append(int(row[idx["last_trade_id"]]))
        cols["buyer_is_maker"].append(row[idx["is_buyer_maker"]].lower() == "true")
    n = _to_parquet(dest, cols)
    gaps = _idle_gaps(cols["ts_ms"], AGG_GAP_MS)
    notes = [f"disordered-rows:{disorder}"] if disorder else []
    return n, cols["ts_ms"][0], cols["ts_ms"][-1], gaps, notes


def _idle_gaps(ts_list: list[int], threshold_ms: int) -> list[tuple[int, int]]:
    gaps = []
    for prev, cur in zip(ts_list, ts_list[1:]):
        if cur - prev > threshold_ms:
            gaps.append((prev, cur))
    return gaps


def _convert_marks(rows: list[list[str]]
                 ) -> list[tuple[int, int, float, float, float, float]]:
    """Minute klines -> (open, close_avail, open_px, high, low, close) tuples.

    The close is published at its availability (close_time), never at the
    minute open — pairing open_time with close was lookahead (E-009).
    """
    header, body = rows[0], rows[1:]
    col = {name: header.index(name) for name in (
        "open_time", "open", "high", "low", "close", "close_time")}
    return [(int(row[col["open_time"]]), int(row[col["close_time"]]),
             float(row[col["open"]]), float(row[col["high"]]),
             float(row[col["low"]]), float(row[col["close"]]))
            for row in body]


def _convert_funding(rows: list[list[str]]) -> list[tuple[int, int, float]]:
    header, body = rows[0], rows[1:]
    calc_i = header.index("calc_time")
    hours_i = header.index("funding_interval_hours")
    rate_i = header.index("last_funding_rate")
    return [(int(row[calc_i]), int(row[hours_i]), float(row[rate_i]))
            for row in body]


def _join_marks(marks: list[tuple[int, int, float, float, float, float]],
                fundings: list[tuple[int, int, float]],
                dest: Path) -> tuple[int, int, int, bool]:
    """Minute marks + funding terms -> markPrice channel (causal, explicit).

    Rows publish at close availability with open/close/availability times
    preserved. A rate applies only within two funding intervals of its calc
    time; older terms yield NULL + status "absent" (unknown — the engine
    must skip settlement, never treat it as zero). Returns
    (rows, ts_min, ts_max, terms_absent).
    """
    fundings = sorted(fundings)
    cols: dict[str, list] = {k: [] for k in (
        "ts_ms", "open_time", "close_time", "mark", "open_px", "high_px",
        "low_px", "funding_rate", "funding_status", "next_funding_ms")}
    terms_absent = False
    for open_ms, avail_ms, open_px, high, low, close in sorted(marks):
        nxt = 0
        last_calc: tuple[int, int, float] | None = None
        for calc, hours, value in fundings:
            if calc <= avail_ms:
                last_calc = (calc, hours, value)
            elif nxt == 0:
                nxt = calc
        rate: float | None = None
        if last_calc is not None:
            calc, hours, value = last_calc
            if avail_ms - calc <= hours * 3_600_000 * 2:
                rate = value
        if rate is None:
            terms_absent = True
        cols["ts_ms"].append(avail_ms)
        cols["open_time"].append(open_ms)
        cols["close_time"].append(avail_ms)
        cols["mark"].append(close)
        cols["open_px"].append(open_px)
        cols["high_px"].append(high)
        cols["low_px"].append(low)
        cols["funding_rate"].append(rate)
        cols["funding_status"].append("sourced" if rate is not None else "absent")
        cols["next_funding_ms"].append(nxt)
    n = _to_parquet(dest, cols)
    return n, cols["ts_ms"][0], cols["ts_ms"][-1], terms_absent


def _missing_minutes(marks: list[tuple[int, int, float, float, float, float]],
                     day: date) -> list[int]:
    day_start = int(datetime(day.year, day.month, day.day,
                             tzinfo=timezone.utc).timestamp() * 1000)
    have = {open_ms for open_ms, _, _, _, _, _ in marks
            if day_start <= open_ms < day_start + 86_400_000}
    return [m for m in range(1440) if day_start + m * 60_000 not in have]


def _fetch_filters(symbols: tuple[str, ...]) -> tuple[dict, str]:
    url = ("https://fapi.binance.com/fapi/v1/exchangeInfo?"
           + "&".join(f"symbols={s}" for s in symbols))
    import json as _json
    try:
        payload = _json.loads(_http_get(url, timeout=30.0).decode("utf-8"))
    except RuntimeError:
        url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
        payload = _json.loads(_http_get(url, timeout=60.0).decode("utf-8"))
    out = {}
    for entry in payload.get("symbols", []):
        if entry.get("symbol") not in symbols:
            continue
        filters = {f["filterType"]: f for f in entry.get("filters", [])}
        out[entry["symbol"]] = {
            "tick": float(filters["PRICE_FILTER"]["tickSize"]),
            "step": float(filters["LOT_SIZE"]["stepSize"]),
            "min_qty": float(filters["LOT_SIZE"].get("minQty", 0.0)),
            "min_notional": float(filters.get("MIN_NOTIONAL", {}).get("notional", 0.0)),
        }
    return out, url


def _toml_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _write_manifest(path: Path, *, symbols, sources, gaps, filters, filters_url) -> None:
    lines = [
        "# Frozen 30-accounting-day benchmark (W2, E-009; B5).",
        "# Generated by prepare_benchmark_30d.py; `sha256` addresses the source",
        "# archive, `derived_sha256` the converted Parquet named by `local`.",
        "# `local` paths resolve against this file's directory.",
        "",
        "[dataset]",
        f"name = {_toml_str('benchmark-30d')}",
        f"kind = {_toml_str('vision-archive')}",
        "manifest_version = 1",
        f"transform_version = {TRANSFORM_VERSION}",
        ("transform_notes = " + _toml_str(
            "v2 causal: minute closes publish at close availability (open/close/"
            "availability preserved); absent funding is NULL + status, never "
            "zero; v1 (close-at-open lookahead) refused by the reader.")),
        f"created_utc = {_toml_str(datetime.now(timezone.utc).isoformat())}",
        f"window_utc = [{_toml_str(str(DAY_START))}, {_toml_str(str(DAY_END))}]",
        "window_ist = [\"2026-09-12\", \"2026-10-11\"]",
        f"tz_accounting = {_toml_str('Asia/Kolkata')}",
        "symbols = [{}]".format(", ".join(_toml_str(s) for s in symbols)),
        ("notes = " + _toml_str(
            "Fills: trade-cross from observed aggTrades (no archive BBO; "
            "vision bookDepth is %-band depth, not price levels, and is "
            "excluded). Marks: 1m mark closes; funding: monthly fundingRate, "
            "both sourced-vision. Book views are never-synced on this data "
            "(S5-ineligible with reasons).")),
        "",
    ]
    for entry in sources:
        lines.append("[[source]]")
        for key in ("symbol", "day", "month", "channel", "url", "sha256",
                    "local", "derived_sha256", "rows", "bytes",
                    "ts_min_ms", "ts_max_ms", "notes"):
            if key not in entry or entry[key] is None:
                continue
            value = entry[key]
            lines.append(f"{key} = {_toml_str(value)}" if isinstance(value, str)
                         else f"{key} = {value}")
        lines.append("")
    for entry in gaps:
        lines.append("[[gap]]")
        for key in ("symbol", "day", "start_ms", "end_ms", "reason"):
            value = entry[key]
            lines.append(f"{key} = {_toml_str(value)}" if isinstance(value, str)
                         else f"{key} = {value}")
        lines.append("")
    lines += [
        "[filters]",
        f"profile = {_toml_str('frozen-assumed')}",
        f"fetched_utc = {_toml_str(datetime.now(timezone.utc).isoformat())}",
        f"source = {_toml_str(filters_url)}",
        ("notes = " + _toml_str(
            "Current venue filters frozen at manifest build; the archive "
            "carries no historical filters.")),
        "",
    ]
    for symbol in symbols:
        prof = filters.get(symbol, {})
        lines.append(f"[filters.symbols.{symbol}]")
        for key in ("tick", "step", "min_qty", "min_notional"):
            lines.append(f"{key} = {prof.get(key, 0.0)}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _fetch_day(symbol: str, day: date, channel: str, raw_dir: Path) -> dict:
    iso = day.isoformat()
    url = f"{VISION}/{DAILY_CHANNELS[channel].format(s=symbol, d=iso)}"
    dest = raw_dir / symbol / day.isoformat() / Path(url).name
    try:
        data, sha, resumed = _fetch_verified(url, dest)
    except FileNotFoundError:
        return {"missing": True, "url": url}
    # NOTE: bytes are re-read from `dest` at conversion time; workers return
    # metadata only so a 500-file freeze never holds the month in RAM.
    return {"missing": False, "url": url, "sha": sha, "bytes": len(data),
            "resumed": resumed, "dest": str(dest)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="dataset directory to build")
    parser.add_argument("--symbols", default=",".join(SYMBOLS))
    parser.add_argument("--jobs", type=int, default=8)
    args = parser.parse_args()

    try:
        import pyarrow  # noqa: F401
    except ImportError:
        print("prepare needs pyarrow (project env carries it)", file=sys.stderr)
        return 2

    out = Path(args.out)
    raw_dir = out / "raw"
    cache_dir = out / "cache"
    symbols = tuple(s.strip().upper() for s in args.symbols.split(",") if s.strip())
    days = list(_daterange(DAY_START, DAY_END))
    print(f"freeze: {len(symbols)} symbols x {len(days)} days -> {out}", flush=True)

    sources: list[dict] = []
    gaps: list[dict] = []
    missing: list[str] = []

    # -- funding months first (the mark join needs them) -------------------
    funding: dict[str, list] = {s: [] for s in symbols}
    for symbol in symbols:
        for month in FUNDING_MONTHS:
            url = f"{VISION}/{FUNDING_PATH.format(s=symbol, m=month)}"
            dest = raw_dir / symbol / "funding" / Path(url).name
            try:
                data, sha, _ = _fetch_verified(url, dest)
            except FileNotFoundError:
                missing.append(url)
                continue
            rows = _convert_funding(_csv_rows(data))
            funding[symbol].extend(rows)
            parquet = cache_dir / f"symbol={symbol}" / "funding" / f"{month}.parquet"
            cols = {"ts_ms": [c for c, _, _ in rows],
                    "interval_h": [h for _, h, _ in rows],
                    "rate": [r for _, _, r in rows]}
            n = _to_parquet(parquet, cols)
            sources.append({"symbol": symbol, "month": month,
                            "channel": "fundingRate", "url": url, "sha256": sha,
                            "local": str(parquet.relative_to(out)),
                            "derived_sha256": _file_sha256(parquet),
                            "rows": n, "bytes": len(data),
                            "ts_min_ms": cols["ts_ms"][0] if n else None,
                            "ts_max_ms": cols["ts_ms"][-1] if n else None})
        print(f"  funding {symbol}: {len(funding[symbol])} terms", flush=True)

    # -- daily channels (fetched in parallel, converted serially) ----------
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {(s, d, c): pool.submit(_fetch_day, s, d, c, raw_dir)
                   for s in symbols for d in days for c in DAILY_CHANNELS}
        fetched = {key: fut.result() for key, fut in futures.items()}

    marks_by_day: dict[tuple[str, str], list] = {}
    for symbol in symbols:
        for day in days:
            iso = day.isoformat()
            agg = fetched[(symbol, day, "aggTrade")]
            mark = fetched[(symbol, day, "markKline1m")]
            if agg["missing"]:
                missing.append(agg["url"])
                gaps.append({"symbol": symbol, "day": iso, "start_ms": 0,
                             "end_ms": 0, "reason": "day-file-absent:aggTrade"})
            else:
                dest = (cache_dir / f"symbol={symbol}" / f"date={iso}"
                        / "channel=aggTrade" / "part.parquet")
                n, ts_min, ts_max, day_gaps, notes = _convert_agg(
                    _csv_rows(Path(agg["dest"]).read_bytes()), dest)
                sources.append({"symbol": symbol, "day": iso, "channel": "aggTrade",
                                "url": agg["url"], "sha256": agg["sha"],
                                "local": str(dest.relative_to(out)),
                                "derived_sha256": _file_sha256(dest),
                                "rows": n, "bytes": agg["bytes"],
                                "ts_min_ms": ts_min, "ts_max_ms": ts_max,
                                "notes": "; ".join(notes) if notes else None})
                for start, end in day_gaps:
                    gaps.append({"symbol": symbol, "day": iso, "start_ms": start,
                                 "end_ms": end, "reason": "no-trades-300s+"})
            if mark["missing"]:
                missing.append(mark["url"])
                gaps.append({"symbol": symbol, "day": iso, "start_ms": 0,
                             "end_ms": 0, "reason": "day-file-absent:markKline1m"})
            else:
                marks = _convert_marks(
                    _csv_rows(Path(mark["dest"]).read_bytes()))
                marks_by_day[(symbol, iso)] = marks
                for minute in _missing_minutes(marks, day):
                    minute_ms = (int(datetime(day.year, day.month, day.day,
                                              tzinfo=timezone.utc).timestamp() * 1000)
                                 + minute * 60_000)
                    gaps.append({"symbol": symbol, "day": iso,
                                 "start_ms": minute_ms, "end_ms": minute_ms + 60_000,
                                 "reason": "missing-mark-minute"})
                dest = (cache_dir / f"symbol={symbol}" / f"date={iso}"
                        / "channel=markPrice" / "part.parquet")
                n, ts_min, ts_max, terms_absent = _join_marks(
                    marks, funding[symbol], dest)
                sources.append({"symbol": symbol, "day": iso, "channel": "markPrice",
                                "url": mark["url"], "sha256": mark["sha"],
                                "local": str(dest.relative_to(out)),
                                "derived_sha256": _file_sha256(dest),
                                "rows": n, "bytes": mark["bytes"],
                                "ts_min_ms": ts_min, "ts_max_ms": ts_max})
                if terms_absent:
                    day_start = int(datetime(day.year, day.month, day.day,
                                             tzinfo=timezone.utc).timestamp() * 1000)
                    gaps.append({"symbol": symbol, "day": iso,
                                 "start_ms": day_start,
                                 "end_ms": day_start + 86_400_000,
                                 "reason": "funding-terms-absent"})
        print(f"  days {symbol}: done", flush=True)

    print("freezing filter profile (labeled frozen-assumed)...", flush=True)
    filters, filters_url = _fetch_filters(symbols)
    _write_manifest(out / "benchmark_30d.toml", symbols=symbols, sources=sources,
                    gaps=gaps, filters=filters, filters_url=filters_url)
    print(f"wrote {out / 'benchmark_30d.toml'}: "
          f"{len(sources)} sources, {len(gaps)} gaps, "
          f"{len(missing)} missing files", flush=True)
    for url in missing:
        print(f"  MISSING {url}", flush=True)
    # Validate the manifest parses before declaring success.
    tomllib.loads((out / "benchmark_30d.toml").read_bytes().decode("utf-8"))
    return 0 if not missing else 3


if __name__ == "__main__":
    raise SystemExit(main())
