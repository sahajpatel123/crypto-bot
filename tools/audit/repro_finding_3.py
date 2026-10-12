#!/usr/bin/env python3
"""Repro finding 3: cross-symbol dedup (Worker 5, OP-001). Exit 1 = bug present."""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from cryptobot.research.backtest import MECHANISM_SPLIT, prepare_split_capture

T0 = 1_700_000_000_000


def _bbo(symbol, ts):
    return {"v": 1, "format": "cryptobot-events/1",
            "input_class": "synthetic-benchmark", "source": "x", "route": "x",
            "run_id": "t", "seq": 1, "channel": "bookTicker", "symbol": symbol,
            "exchange_ts_ms": ts, "local_recv_ms": ts, "local_mono_ns": 1,
            "gap_kind": None, "venue_seq": 0,
            "payload": {"bid": 60000.0, "ask": 60001.0,
                        "bid_qty": 5.0, "ask_qty": 5.0}}


class _TwoSymbol:
    dataset_id = "audit-two-symbol"

    def __init__(self, events_by_symbol):
        self._events = events_by_symbol

    def days(self):
        return (1,)

    def events(self, symbol, day):
        for e in self._events.get(symbol, []):
            yield dict(e)

    def coverage(self):
        return {"days": [{"day": 1, "quotes_observed": True}]}

    def manifest_sha(self):
        return "a" * 64


def main() -> int:
    ts = T0 + 1000
    ds = _TwoSymbol({"BTCUSDT": [_bbo("BTCUSDT", ts)],
                     "ETHUSDT": [_bbo("ETHUSDT", ts)]})
    with tempfile.TemporaryDirectory() as tmp:
        manifest = prepare_split_capture(ds, MECHANISM_SPLIT, Path(tmp) / "cap",
                                         ("BTCUSDT", "ETHUSDT"))
        lines = (Path(tmp) / "cap" / "events.jsonl").read_text().splitlines()
        events = [json.loads(line) for line in lines]
    symbols = sorted(e["symbol"] for e in events)
    print(f"input: BTC+ETH identical quote at {ts} (2 events)")
    print(f"output: n_events={manifest['n_events']}, symbols={symbols}")
    if manifest["n_events"] != 2 or symbols != ["BTCUSDT", "ETHUSDT"]:
        print("BUG REPRODUCED: dedup deleted another symbol's event")
        return 1
    print("OK: both symbols preserved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
