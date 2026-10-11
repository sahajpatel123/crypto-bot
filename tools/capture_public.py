"""Capture public Binance USD-M futures data (Worker 2, E-001).

Public REST only — no credentials, no orders. Two modes:

  discover:  fetch exchangeInfo, list current USDT-perp symbols dynamically
             (no hardcoded whitelist) with size-aware eligibility.
  capture:   record public klines to a cryptobot-recording/1 JSONL file
             labelled ``observed-public``.

Examples:
  python tools/capture_public.py discover --max-min-notional 20
  python tools/capture_public.py capture --symbol BTCUSDT --interval 1m \\
      --limit 60 --out data/observed/klines_BTCUSDT_1m.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cryptobot.market_data.discovery import (
    FAPI_BASE_URL,
    discover_usdt_perps,
    discovery_summary,
    eligible_symbols,
    fetch_exchange_info,
    urllib_json_get,
)
from cryptobot.market_data.recorder import INPUT_OBSERVED, KlineRecorder

INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


def cmd_discover(args: argparse.Namespace) -> int:
    payload, latency_ms, fetched_at = fetch_exchange_info(
        urllib_json_get, base_url=args.base_url, timeout_s=args.timeout_s
    )
    result = discover_usdt_perps(
        payload, fetch_latency_ms=latency_ms, fetched_at_utc=fetched_at, base_url=args.base_url
    )
    eligible = eligible_symbols(result, max_min_notional_usdt=args.max_min_notional)
    summary = discovery_summary(result, eligible)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    if args.interval not in INTERVAL_MS:
        raise SystemExit(f"unsupported interval: {args.interval} (choose from {sorted(INTERVAL_MS)})")
    interval_ms = INTERVAL_MS[args.interval]
    url = (
        f"{args.base_url}/fapi/v1/klines?symbol={args.symbol}"
        f"&interval={args.interval}&limit={args.limit}"
    )
    started = time.perf_counter()
    rows, latency_ms = urllib_json_get(url, args.timeout_s)
    local_recv_ms = int(time.time() * 1000)
    if not isinstance(rows, list) or not rows:
        raise SystemExit(f"no klines returned for {args.symbol} {args.interval}")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    capture_cmd = "python " + " ".join(sys.argv)
    recorder = KlineRecorder(
        out, symbol=args.symbol, channel=f"klines/{args.interval}",
        interval_ms=interval_ms, input_class=INPUT_OBSERVED,
        source="binance-fapi-public", capture_cmd=capture_cmd,
    )
    for row in rows:
        recorder.record_rest_kline(row, local_recv_ms)
    stats = recorder.finish(stale_after_ms=args.stale_after_ms)
    last_close_ms = int(rows[-1][6])
    data_age_ms = local_recv_ms - last_close_ms
    report = {
        "out": str(out),
        "input_class": INPUT_OBSERVED,
        "symbol": args.symbol,
        "interval": args.interval,
        "fetch_latency_ms": round(latency_ms, 1),
        "data_age_ms": data_age_ms,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "count": stats.count,
        "closed_count": stats.closed_count,
        "gaps": len(stats.gaps),
        "stale_count": stats.stale_count,
        "max_lag_ms": stats.max_lag_ms,
    }
    print(json.dumps(report, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture public Binance USD-M data")
    parser.add_argument("--base-url", default=FAPI_BASE_URL)
    parser.add_argument("--timeout-s", type=float, default=15.0)
    sub = parser.add_subparsers(dest="mode", required=True)
    p_discover = sub.add_parser("discover", help="list current USDT-perp symbols")
    p_discover.add_argument("--max-min-notional", type=float, default=None,
                            help="eligibility cap on venue minimum notional (USDT)")
    p_discover.add_argument("--out", default=None, help="write discovery JSON here")
    p_discover.set_defaults(func=cmd_discover)
    p_capture = sub.add_parser("capture", help="record public klines to JSONL")
    p_capture.add_argument("--symbol", required=True)
    p_capture.add_argument("--interval", default="1m")
    p_capture.add_argument("--limit", type=int, default=60)
    p_capture.add_argument("--out", required=True)
    p_capture.add_argument("--stale-after-ms", type=int, default=30_000)
    p_capture.set_defaults(func=cmd_capture)
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
