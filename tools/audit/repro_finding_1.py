#!/usr/bin/env python3
"""Repro finding 1: future-VWAP quote (Worker 5, OP-001). Exit 1 = bug present."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from cryptobot.research.spread import PROFILE_ID, apply_profile

T0 = 1_700_000_000_000


def _trade(seq, ms, price):
    return {"v": 1, "format": "cryptobot-events/1",
            "input_class": "observed-public", "source": "x", "route": "x",
            "run_id": "t", "seq": seq, "channel": "aggTrade", "symbol": "BTCUSDT",
            "exchange_ts_ms": ms, "local_recv_ms": ms, "local_mono_ns": seq,
            "gap_kind": None, "venue_seq": seq,
            "payload": {"agg_id": seq, "price": price, "qty": 1.0,
                        "first_id": seq, "last_id": seq, "trade_ts_ms": ms,
                        "buyer_is_maker": False}}


def main() -> int:
    window = T0 + 1000
    day = [_trade(1, window + 50, 100.0), _trade(2, window + 950, 200.0)]
    merged, _ = apply_profile(day, "BTCUSDT", 1.0)
    modeled = [e for e in merged if e["payload"].get("quote_source") == PROFILE_ID]
    print(f"trades: 1050ms/100, 1950ms/200 (window {window})")
    if not modeled:
        print("no modeled quote emitted")
        return 1
    q = modeled[0]
    mid = (q["payload"]["bid"] + q["payload"]["ask"]) / 2
    print(f"modeled quote at {q['exchange_ts_ms']}ms centers at {mid}")
    print("causal expectation: 100.0 (only 1050ms trade known by 1100ms)")
    day2 = [_trade(1, window + 50, 100.0), _trade(2, window + 950, 1000.0)]
    merged2, _ = apply_profile(day2, "BTCUSDT", 1.0)
    modeled2 = [e for e in merged2 if e["payload"].get("quote_source") == PROFILE_ID]
    mid2 = (modeled2[0]["payload"]["bid"] + modeled2[0]["payload"]["ask"]) / 2 if modeled2 else None
    print(f"after changing 1950ms trade 200→1000, early quote centers at {mid2}")
    if abs(mid - 100.0) > 1e-9 or mid != mid2 and mid2 is not None and abs(mid - mid2) > 1e-9:
        # Bug: quote uses future VWAP (150) and moves with future data.
        if abs(mid - 150.0) < 1e-9:
            print("BUG REPRODUCED: quote centers at full-window VWAP 150 (uses future)")
        else:
            print(f"BUG REPRODUCED: quote centers at {mid}, causal is 100.0")
        return 1
    print("OK: quote is causal and stable under future mutation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
