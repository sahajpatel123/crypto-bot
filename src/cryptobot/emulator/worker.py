"""EMULATED drill worker: open a position, then flatten on SIGTERM.

Runs in its own OS process so the drill can prove SIGTERM flatten and
SIGKILL orphan recovery over real sockets. It only talks to a loopback
MockEx (enforced) and never reads keys from the environment.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import signal
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from cryptobot.adapters.binance_live import BinanceLiveEngine
from cryptobot.adapters.mockex_server import DEFAULT_KEY, DEFAULT_SECRET
from cryptobot.app.engine import EngineOrder

_STOP = False


def _flatten(engine: BinanceLiveEngine, symbol: str) -> list[str]:
    account = engine._signed("GET", "/fapi/v2/account")
    closed: list[str] = []
    for pos in account.get("positions", []):
        if str(pos.get("symbol")) != symbol:
            continue
        qty = float(pos.get("positionAmt", 0))
        if abs(qty) < 1e-8:
            continue
        side = "SELL" if qty > 0 else "BUY"
        engine.submit(EngineOrder(
            instrument=symbol, side=side, qty=abs(qty), kind="MARKET",
            reduce_only=True, role="target"))
        closed.append(symbol)
    return closed


def main(argv: list[str] | None = None) -> int:
    global _STOP
    parser = argparse.ArgumentParser(prog="cryptobot.emulator.worker")
    parser.add_argument("--base", required=True)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--qty", type=float, default=0.002)
    parser.add_argument("--journal", required=True)
    parser.add_argument("--ready", required=True)
    args = parser.parse_args(argv)

    host = urlsplit(args.base).hostname
    if host not in ("127.0.0.1", "localhost"):
        print(f"worker: REFUSED non-loopback base {args.base}", file=sys.stderr)
        return 2
    engine = BinanceLiveEngine(
        api_key=DEFAULT_KEY, api_secret=DEFAULT_SECRET,
        journal_path=Path(args.journal), expected_leverage=3,
        run_tag="emu-worker", live_enable=True, demo=False,
        base_url=args.base)
    cid = engine.submit(EngineOrder(
        instrument=args.symbol, side="BUY", qty=args.qty, kind="MARKET",
        role="entry"))

    def _stop(_signum, _frame):
        global _STOP
        _STOP = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    Path(args.ready).write_text(json.dumps(
        {"client_id": cid, "pid": __import__("os").getpid()}), encoding="utf-8")
    while not _STOP:
        time.sleep(0.05)
    closed = _flatten(engine, args.symbol)
    account = engine._signed("GET", "/fapi/v2/account")
    flat = all(abs(float(p.get("positionAmt", 0))) < 1e-8
               for p in account.get("positions", []))
    engine.close()
    print(json.dumps({"closed": closed, "flat": flat,
                      "provenance": "EMULATED"}))
    return 0 if flat else 1


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        raise SystemExit(main())
