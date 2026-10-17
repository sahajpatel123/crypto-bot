"""Funding-settlement recorder for PIVOT-01 enrollment (manager-owned).

Polls the public Binance USD-M fundingRate history
(GET /fapi/v1/fundingRate, no auth) and appends settlement records in
the exact contract `tools/pivot_enroll.py --funding-file` accepts:
``{symbol, funding_ts_ms, funding_rate, source}`` (+ mark_price when
the venue returns it).

Two modes:
  once  — fetch latest history per symbol, append only settlements
          newer than the file's max ts (idempotent reruns).
  watch — repeat `once` every `--interval-s` until `--duration-s`
          elapses (for running alongside a long capture).

Never interpolates: only venue-returned settlements are written, each
with its source. Exit 0 on success; 2 on input/contract error or when
every symbol fails to fetch.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

EXIT_BLOCKED = 2
SOURCE = "GET /fapi/v1/fundingRate (public, no auth)"
BASE_URL = "https://fapi.binance.com"


def _fetch(symbol: str, limit: int, timeout_s: float,
           base_url: str = BASE_URL) -> list[dict]:
    q = urllib.parse.urlencode({"symbol": symbol, "limit": limit})
    req = urllib.request.Request(f"{base_url}/fapi/v1/fundingRate?{q}",
                                 headers={"User-Agent": "cryptobot-pivot/1"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        rows = json.loads(resp.read())
    if not isinstance(rows, list):
        raise ValueError(f"{symbol}: unexpected response shape")
    out = []
    for row in rows:
        out.append({"symbol": symbol,
                    "funding_ts_ms": int(row["fundingTime"]),
                    "funding_rate": float(row["fundingRate"]),
                    "mark_price": float(row.get("markPrice", 0.0)),
                    "source": SOURCE})
    return out


def _max_ts(path: Path) -> dict[str, int]:
    """Per-symbol max funding_ts_ms in the file ({} when absent)."""
    latest: dict[str, int] = {}
    if not path.exists():
        return latest
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            sym = str(rec["symbol"])
            latest[sym] = max(latest.get(sym, 0),
                              int(rec["funding_ts_ms"]))
    return latest


def record_once(symbols: list[str], out: Path, limit: int = 10,
                timeout_s: float = 30.0,
                base_url: str = BASE_URL) -> dict:
    """Append settlements newer than the file max. Returns a summary."""
    if not symbols:
        raise ValueError("no symbols given")
    floor = _max_ts(out)
    fetched = 0
    written = 0
    errors: dict[str, str] = {}
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as fh:
        for symbol in symbols:
            try:
                rows = _fetch(symbol, limit, timeout_s, base_url)
            except (urllib.error.URLError, ValueError, KeyError,
                    TimeoutError, OSError) as exc:
                errors[symbol] = f"{type(exc).__name__}: {exc}"
                continue
            fetched += len(rows)
            for row in rows:
                if row["funding_ts_ms"] > floor.get(symbol, 0):
                    fh.write(json.dumps(row, sort_keys=True) + "\n")
                    written += 1
                    floor[symbol] = row["funding_ts_ms"]
    if fetched == 0:
        raise ValueError(f"all symbols failed: {errors}")
    return {"symbols": symbols, "fetched": fetched, "written": written,
            "errors": errors, "out": str(out)}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Record venue funding settlements (public, no auth)")
    parser.add_argument("--symbols", required=True,
                        help="comma list, e.g. BTCUSDT,ETHUSDT")
    parser.add_argument("--out", required=True)
    parser.add_argument("--mode", default="once", choices=("once", "watch"))
    parser.add_argument("--interval-s", type=float, default=3600.0)
    parser.add_argument("--duration-s", type=float, default=0.0)
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",")
               if s.strip()]
    try:
        if args.mode == "once":
            summary = record_once(symbols, Path(args.out),
                                  limit=args.limit)
            print(f"funding: +{summary['written']} settlements "
                  f"({summary['fetched']} fetched) -> {args.out}")
            return 0
        if args.interval_s <= 0 or args.duration_s <= 0:
            raise ValueError("watch needs --interval-s > 0 and "
                             "--duration-s > 0")
        end = time.monotonic() + args.duration_s
        total = 0
        while True:
            try:
                summary = record_once(symbols, Path(args.out),
                                      limit=args.limit)
                total += summary["written"]
            except ValueError as exc:
                print(f"funding watch round failed: {exc}",
                      file=sys.stderr)
            if time.monotonic() + args.interval_s > end:
                break
            time.sleep(args.interval_s)
        print(f"funding watch done: +{total} settlements -> {args.out}")
        return 0
    except ValueError as exc:
        print(f"BLOCKED: {exc}")
        return EXIT_BLOCKED


if __name__ == "__main__":
    raise SystemExit(main())
