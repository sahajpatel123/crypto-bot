"""Replay a cryptobot recording deterministically (Worker 2, E-001).

Loads a cryptobot-recording/1 JSONL file, enforces the expected input class
(observed vs synthetic are never silently mixed), replays the stream, and
prints gap/stale statistics plus a determinism hash computed over two
independent passes (they must match).

Example:
  python tools/replay_public.py --in data/observed/klines_BTCUSDT_1m.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cryptobot.market_data.recorder import INPUT_OBSERVED, analyze_klines, stats_to_dict
from cryptobot.market_data.replayer import assert_input_class, load_recording, replay, replay_hash


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic recording replay")
    parser.add_argument("--in", dest="path", required=True)
    parser.add_argument("--expect-class", default=INPUT_OBSERVED)
    parser.add_argument("--stale-after-ms", type=int, default=30_000)
    args = parser.parse_args()

    header, records = load_recording(args.path)
    assert_input_class(header, args.expect_class)
    interval_ms = int(header["interval_ms"])
    events = list(replay(records))
    stats = analyze_klines(records, interval_ms, stale_after_ms=args.stale_after_ms)
    first = replay_hash(records)
    second = replay_hash(list(replay(records)))
    report = {
        "path": args.path,
        "input_class": header["input_class"],
        "symbol": header.get("symbol"),
        "channel": header.get("channel"),
        "events": len(events),
        "deterministic": first == second,
        "replay_sha256": first,
        "stats": stats_to_dict(stats),
    }
    print(json.dumps(report, indent=2))
    return 0 if first == second else 1


if __name__ == "__main__":
    raise SystemExit(main())
