#!/usr/bin/env python3
"""Repro finding 2: mark close at open (Worker 5, OP-001). Exit 1 = bug present."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
PREP = ROOT / "datasets" / "prepare_benchmark_30d.py"


def main() -> int:
    spec = importlib.util.spec_from_file_location("prepare_benchmark_30d", PREP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    header = ["open_time", "open", "high", "low", "close", "volume",
              "close_time", "quote_volume", "count",
              "taker_buy_volume", "taker_buy_quote_volume", "ignore"]
    body = ["1000", "49000", "51000", "48900", "50000", "12.5",
            "60999", "625000", "150", "6.0", "300000", "0"]
    marks = module._convert_marks([header, body])
    print(f"_convert_marks([open=1000, close_time=60999, close=50000]) -> {marks!r}")
    item = marks[0]
    ts = int(item["ts_ms"]) if isinstance(item, dict) else int(item[0])
    print(f"emitted ts: {ts}ms; close available no earlier than 60999ms")
    if ts < 60999:
        print("BUG REPRODUCED: close published before availability (at minute open)")
        return 1
    print("OK: mark published no earlier than availability")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
