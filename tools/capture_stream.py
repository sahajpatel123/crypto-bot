"""Run a supervised public-stream capture (Worker 2, E-006).

Discovers the live USDT-perp universe, selects a small capture set by an
explicit rule, measures clock offset, then runs the collector: one websocket
per routed surface (market + public), diff-depth books with resync, raw +
normalized + 1s-bar files, heartbeat, bounded storage, and a run manifest.

Bulk output stays in the run directory (outside git). Supervision: PID file,
heartbeat.json, STOP file, SIGTERM/SIGINT clean stop, bounded reservoirs.

Examples:
  python tools/capture_stream.py --top-n 2 --duration-s 1800 --run-base .captures
  python tools/capture_stream.py --top-n 2 --duration-s 60 --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cryptobot.market_data.collector import (
    Collector,
    CollectorConfig,
    measure_clock_offset_ms,
    select_capture_set,
)
from cryptobot.market_data.discovery import FAPI_BASE_URL, fetch_exchange_info, urllib_json_get

DOCS_RECHECK = (
    "2026-10-11: official Binance WS docs unreachable from here (JS-gated, HTTP 202 "
    "empty body on Connect + order-book guides); routing verified via 6 independent "
    "client migration notes (legacy /ws + /stream decommissioned 2026-04-23; routed "
    "/public + /market + /private on wss://fstream.binance.com; no cross-category "
    "mixing per connection) plus live route probes in this run."
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Supervised public-stream capture")
    parser.add_argument("--top-n", type=int, default=2)
    parser.add_argument("--symbols", default=None, help="comma list to override selection (recorded)")
    parser.add_argument("--duration-s", type=float, default=1800.0)
    parser.add_argument("--run-base", default=".captures")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--max-bytes", type=int, default=2_000_000_000)
    parser.add_argument("--chaos-disconnect-after-s", type=float, default=None)
    parser.add_argument("--lateness-ms", type=int, default=500)
    parser.add_argument("--base-url", default=FAPI_BASE_URL)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    payload, latency_ms, fetched_at = fetch_exchange_info(urllib_json_get, base_url=args.base_url)
    meta_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    if args.symbols:
        symbols = tuple(s.strip().upper() for s in args.symbols.split(",") if s.strip())
        rule = f"operator override: {','.join(symbols)} (NOT dynamic selection)"
        evidence: dict = {}
    else:
        symbols, rule, evidence = select_capture_set(payload, urllib_json_get, args.base_url, args.top_n)
    offset = measure_clock_offset_ms(urllib_json_get, args.base_url)
    print(json.dumps({"symbols": list(symbols), "rule": rule, "quote_volumes": evidence,
                      "metadata_hash": meta_hash, "discovery_latency_ms": round(latency_ms, 1),
                      "clock_offset_ms": round(offset["offset_ms"], 1),
                      "clock_rtt_ms": round(offset["rtt_ms"], 1),
                      "docs_recheck": DOCS_RECHECK}, indent=2))
    if args.dry_run:
        return 0

    run_id = args.run_id or ("cap-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    run_dir = str(Path(args.run_base) / run_id)
    config = CollectorConfig(symbols=symbols, run_dir=run_dir, run_id=run_id,
                             capture_set_rule=rule, max_bytes=args.max_bytes,
                             chaos_disconnect_after_s=args.chaos_disconnect_after_s,
                             lateness_ms=args.lateness_ms)
    collector = Collector(config)
    collector._selection_evidence = evidence
    collector._metadata_hash = meta_hash

    def _stop(signum, frame):
        collector.request_stop()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    stats = collector.run(duration_s=args.duration_s)
    print(json.dumps({"run_id": run_id, "run_dir": run_dir,
                      "stop_reason": stats.stop_reason, "events_total": stats.events_total,
                      "per_channel": stats.per_channel,
                      "disconnects": {"natural": stats.disconnects_natural,
                                      "injected": stats.disconnects_injected},
                      "depth_resyncs": stats.depth_resyncs,
                      "bytes_written": stats.bytes_written}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
