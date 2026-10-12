#!/usr/bin/env python3
"""Repro finding 4: gap bar quality (Worker 5, OP-001). Exit 1 = bug present."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from cryptobot.market_data.bars import Bar1s, BarAggregator, to_s1_bar


def _trade(ts_ms, trade_id):
    return {"exchange_ts_ms": ts_ms,
            "payload": {"agg_id": trade_id, "price": 100.0, "qty": 1.0,
                        "buyer_is_maker": False}}


def main() -> int:
    agg = BarAggregator("BTCUSDT", lateness_ms=0)
    agg.on_bbo(99.0, 101.0, 500)
    agg.on_trade(_trade(100, 1))
    out = agg.on_trade(_trade(1100, 3))
    print(f"trade IDs 1→3: gap_jumps={agg.stats()['gap_jumps']}")
    gap_bars = [b for b in out if isinstance(b, Bar1s) and b.gap_before]
    print(f"closed: {len(out)} windows, {len(gap_bars)} gap-flagged Bar1s")
    if not gap_bars:
        print("setup broken: no gap bar produced")
        return 2
    converted = to_s1_bar(gap_bars[0])
    print(f"to_s1_bar(gap_bar) -> {converted!r}")
    if converted is not None and getattr(converted, "data_quality", None) is None:
        print("BUG REPRODUCED: gap bar converts to a normal clean Bar")
        print("also: Session._evaluate_symbol constructs MarketView(CLEAN) always")
        print("  (see src/cryptobot/app/session.py:363 quality=DataQuality.CLEAN)")
        return 1
    print("OK: gap bar blocked or carries degraded quality")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
