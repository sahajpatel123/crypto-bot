"""Extend dev marks beyond the frozen 30d window (DEVELOPMENT only).

Downloads daily markPriceKlines zips for 2026-10-12..2026-10-18 and
writes cache-layout parquets identical in schema to the frozen set, so
research.h_eval.hourly_bars picks them up. The frozen manifest is
never edited; log use in research/DATA_LEDGER.md.
Usage: .venv/bin/python tools/extend_benchmark.py
"""
from __future__ import annotations

import csv
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from cryptobot.research.h_eval import load_funding  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "ZECUSDT",
           "NEARUSDT", "STRKUSDT", "XRPUSDT", "WUSDT")
DAYS = [f"2026-10-{d:02d}" for d in range(12, 19)]
URL = ("https://data.binance.vision/data/futures/um/daily/"
       "markPriceKlines/{s}/1m/{s}-1m-{d}.zip")


def rows_for(symbol: str, day: str, funding: list[tuple[int, float]]) -> list[dict]:
    req = urllib.request.Request(URL.format(s=symbol, d=day),
                                 headers={"User-Agent": "cryptobot-dev-extend"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        blob = resp.read()
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        text = zf.read(zf.namelist()[0]).decode()
    out: list[dict] = []
    for row in csv.reader(io.StringIO(text)):
        if not row or not row[0].isdigit():
            continue  # header
        open_ms, close_ms = int(row[0]), int(row[6])
        terms = [r for ts, r in funding if ts <= close_ms]
        nxt = next((ts for ts, _ in funding if ts > close_ms), close_ms)
        out.append({"ts_ms": close_ms, "open_time": open_ms,
                    "close_time": close_ms, "mark": float(row[4]),
                    "open_px": float(row[1]), "high_px": float(row[2]),
                    "low_px": float(row[3]),
                    "funding_rate": terms[-1] if terms else 0.0,
                    "funding_status": "sourced" if terms else "absent",
                    "next_funding_ms": nxt})
    return out


def today_rows(symbol: str, funding: list[tuple[int, float]]) -> list[dict]:
    """Today's 1m mark klines via public REST (no keys), paginated."""
    import json as _json
    start = 1792368000000  # 2026-10-19 00:00 UTC
    out: list[dict] = []
    while True:
        url = ("https://fapi.binance.com/fapi/v1/markPriceKlines"
               f"?symbol={symbol}&interval=1m&startTime={start}&limit=1500")
        req = urllib.request.Request(url, headers={"User-Agent": "cryptobot-dev"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            batch = _json.loads(resp.read())
        if not batch:
            break
        for row in batch:
            close_ms = int(row[6])
            terms = [r for ts, r in funding if ts <= close_ms]
            out.append({"ts_ms": close_ms, "open_time": int(row[0]),
                        "close_time": close_ms, "mark": float(row[4]),
                        "open_px": float(row[1]), "high_px": float(row[2]),
                        "low_px": float(row[3]),
                        "funding_rate": terms[-1] if terms else 0.0,
                        "funding_status": "sourced" if terms else "absent",
                        "next_funding_ms": close_ms})
        start = int(batch[-1][6]) + 1
        if len(batch) < 1500:
            break
    return out


def main() -> int:
    from cryptobot import netguard  # opt-in DNS-sinkhole fallback (CRYPTOBOT_DOH=1)

    netguard.install_from_env()
    total = 0
    for symbol in SYMBOLS:
        funding = load_funding(symbol, ROOT / "datasets/cache")
        for day in DAYS:
            dest = (ROOT / f"datasets/cache/symbol={symbol}/date={day}"
                    "/channel=markPrice/part.parquet")
            if dest.exists():
                continue
            rows = rows_for(symbol, day, funding)
            dest.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(pa.table({k: [r[k] for r in rows]
                                     for k in rows[0]}), dest)
            total += len(rows)
            print(f"{symbol} {day}: {len(rows)} minutes")
        dest = (ROOT / f"datasets/cache/symbol={symbol}/date=2026-10-19"
                "/channel=markPrice/part.parquet")
        if not dest.exists():
            rows = today_rows(symbol, funding)
            dest.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(pa.table({k: [r[k] for r in rows]
                                     for k in rows[0]}), dest)
            total += len(rows)
            print(f"{symbol} 2026-10-19 (today, partial): {len(rows)} minutes")
    print(f"extension minutes written: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
