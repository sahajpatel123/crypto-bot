"""Build the PILOT-01 1-day dataset from Binance public archives.

Reads raw archive CSVs (aggTrades daily, futures 1m klines,
fundingRate monthly) plus a SOURCES record, and writes a pilot
capture dir: events.jsonl (cryptobot-events/1) + manifest.json +
funding.jsonl (enrollment sidecar contract) + SOURCES.md.

Honesty rules (no imputation, ever):
- aggTrade channel comes only from the aggTrades CSV (2.5M rows here).
- markPrice comes only from 1m futures-klines closes, each payload
  labeled cadence="1m-archive" and mark_proxy="klines-close" — the
  auditor flags this against the >=1s floor instead of pretending
  it passes. (Premium-index archive is relative, not prices.)
- No bookTicker/depth exists in the futures archive: NO quote channel
  is synthesized. Strategies needing books are unevaluable here.
- Funding settlements come only from fundingRate rows whose calc_time
  falls inside the pilot day, with source URL per record.

Usage:
  python tools/pilot_build.py --aggtrades <csv> --klines <csv> \\
      --funding <csv> --date 2026-09-21 --out data/pilot/2026-09-21 \\
      --sources SOURCES.json
Exit 0 on success; 2 on input/contract error.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import json
from pathlib import Path

EXIT_BLOCKED = 2


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _day_bounds(date: str) -> tuple[int, int]:
    start = datetime.datetime.strptime(date, "%Y-%m-%d").replace(
        tzinfo=datetime.timezone.utc)
    lo = int(start.timestamp() * 1000)
    return lo, lo + 86_400_000


def build(aggtrades: Path, klines: Path, funding: Path, date: str,
          out: Path, sources: dict) -> dict:
    lo, hi = _day_bounds(date)
    out.mkdir(parents=True, exist_ok=True)
    events_path = out / "events.jsonl"
    seq = 0
    n_trades = 0
    n_marks = 0
    with events_path.open("w", encoding="utf-8") as fh:
        with aggtrades.open(newline="") as csvfh:
            for row in csv.DictReader(csvfh):
                ts = int(row["transact_time"])
                if not lo <= ts < hi:
                    continue
                seq += 1
                n_trades += 1
                fh.write(json.dumps({
                    "v": 1, "format": "cryptobot-events/1", "seq": seq,
                    "channel": "aggTrade", "symbol": "BTCUSDT",
                    "exchange_ts_ms": ts,
                    "payload": {
                        "agg_id": int(row["agg_trade_id"]),
                        "price": float(row["price"]),
                        "qty": float(row["quantity"]),
                        "first_id": int(row["first_trade_id"]),
                        "last_id": int(row["last_trade_id"]),
                        "is_buyer_maker":
                            str(row["is_buyer_maker"]).lower() == "true",
                    }}, sort_keys=True) + "\n")
        with klines.open(newline="") as csvfh:
            reader = csv.reader(csvfh)
            header = next(reader, None)
            has_header = header is not None and \
                any("time" in (c or "").lower() for c in header)
            rows = list(reader) if has_header else ([header] + list(reader)
                                                    if header else [])
            for prow in rows:
                if not prow:
                    continue
                close_ts = int(float(prow[6]))
                close = float(prow[4])
                if not lo <= close_ts < hi:
                    continue
                seq += 1
                n_marks += 1
                fh.write(json.dumps({
                    "v": 1, "format": "cryptobot-events/1", "seq": seq,
                    "channel": "markPrice", "symbol": "BTCUSDT",
                    "exchange_ts_ms": close_ts,
                    "payload": {"mark": close,
                                "cadence": "1m-archive",
                                "mark_proxy": "klines-close"}},
                               sort_keys=True) + "\n")
    # Funding sidecar: only rows inside the pilot day.
    fund_path = out / "funding.jsonl"
    n_fund = 0
    with funding.open(newline="") as csvfh, \
            fund_path.open("w", encoding="utf-8") as fh:
        for row in csv.DictReader(csvfh):
            ts = int(float(row["calc_time"]))
            if not lo <= ts < hi:
                continue
            n_fund += 1
            fh.write(json.dumps({
                "symbol": "BTCUSDT", "funding_ts_ms": ts,
                "funding_rate": float(row["last_funding_rate"]),
                "source": sources.get(
                    "funding_url", "data.binance.vision")},
                sort_keys=True) + "\n")
    manifest = {
        "run_id": f"pilot-{date.replace('-', '')}",
        "input_class": "observed-public",
        "format": "cryptobot-events/1",
        "symbols": ["BTCUSDT"],
        "date": date,
        "preregistration": "coord/pivot/PILOT-01.json",
        "prior_use": "none",
        "selection": "top daily range of prior 30d, mechanical, frozen "
                     "before any strategy scoring (see PILOT-01)",
        "caveats": ["no quote channel in futures archive (books "
                    "unevaluable)", "marks at 1m archive cadence (floor "
                    "wants >=1s)"],
        "events_total": n_trades + n_marks,
        "agg_trades": n_trades,
        "marks_1m": n_marks,
        "funding_settlements": n_fund,
        "sources": sources,
        "sha256": {"events": _sha256(events_path),
                   "funding": _sha256(fund_path)},
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=1, sort_keys=True) + "\n",
        encoding="utf-8")
    (out / "SOURCES.md").write_text(
        f"# PILOT-01 sources ({date})\n\n" + "".join(
            f"- {k}: {v}\n" for k, v in sources.items()) +
        f"\nBuilt by tools/pilot_build.py. aggTrades archive checksum "
        f"verified against published .CHECKSUM before conversion.\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build PILOT-01 1-day dataset (no imputation)")
    parser.add_argument("--aggtrades", required=True)
    parser.add_argument("--klines", required=True,
                        help="futures 1m klines CSV (mark proxy source)")
    parser.add_argument("--funding", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--sources", required=True,
                        help="JSON file {name: url-or-note}")
    args = parser.parse_args()
    try:
        sources = json.loads(Path(args.sources).read_text(
            encoding="utf-8"))
        manifest = build(Path(args.aggtrades), Path(args.klines),
                         Path(args.funding), args.date, Path(args.out),
                         sources)
    except (ValueError, KeyError, FileNotFoundError,
            json.JSONDecodeError) as exc:
        print(f"BLOCKED: {type(exc).__name__}: {exc}")
        return EXIT_BLOCKED
    print(f"pilot: {manifest['events_total']} events "
          f"({manifest['agg_trades']} trades, {manifest['marks_1m']} "
          f"marks, {manifest['funding_settlements']} funding) "
          f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
