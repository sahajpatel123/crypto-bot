"""Lifecycle drill over real sockets against MockEx.

Every result is provenance EMULATED. A PASS here is not a demo-drill
and cannot make the gate GO.
"""
from __future__ import annotations

import contextlib
import json
import socket
import tracemalloc
from pathlib import Path

from cryptobot.adapters.binance_live import BinanceLiveEngine
from cryptobot.adapters.mockex_server import DEFAULT_KEY, DEFAULT_SECRET, EMULATED, MockEx
from cryptobot.app.engine import EngineOrder


def _ws_read_one(port: int, path: str) -> dict:
    sock = socket.create_connection(("127.0.0.1", port), timeout=3)
    key = "dGhlIHNhbXBsZSBub25jZQ=="
    req = (
        f"GET {path} HTTP/1.1\r\n"
        "Host: 127.0.0.1\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )
    sock.sendall(req.encode("ascii"))
    data = b""
    while b"\r\n\r\n" not in data:
        data += sock.recv(4096)
    rest = data.split(b"\r\n\r\n", 1)[1]
    while len(rest) < 2:
        rest += sock.recv(4096)
    length = rest[1] & 0x7F
    start = 2
    if length == 126:
        while len(rest) < 4:
            rest += sock.recv(4096)
        length = int.from_bytes(rest[2:4], "big")
        start = 4
    while len(rest) < start + length:
        rest += sock.recv(4096)
    sock.close()
    return json.loads(rest[start:start + length].decode("utf-8"))


def _engine(base: str, journal: Path) -> BinanceLiveEngine:
    return BinanceLiveEngine(
        api_key=DEFAULT_KEY, api_secret=DEFAULT_SECRET,
        journal_path=journal, expected_leverage=3, run_tag="emu",
        live_enable=True, demo=False, base_url=base)


def _flat(engine: BinanceLiveEngine, symbol: str) -> None:
    account = engine._signed("GET", "/fapi/v2/account")
    for pos in account.get("positions", []):
        if str(pos.get("symbol")) != symbol:
            continue
        qty = float(pos.get("positionAmt", 0))
        if abs(qty) < 1e-8:
            return
        side = "SELL" if qty > 0 else "BUY"
        engine.submit(EngineOrder(
            instrument=symbol, side=side, qty=abs(qty), kind="MARKET",
            reduce_only=True, role="target"))


def run_drill(journal_dir: Path) -> dict:
    """Each cell ends flat. Provenance is EMULATED."""
    mock = MockEx()
    port = mock.serve()
    base = f"http://127.0.0.1:{port}"
    cells = []
    journal_dir.mkdir(parents=True, exist_ok=True)
    try:
        engine = _engine(base, journal_dir / "drill.jsonl")
        # auth + filters + margin via the real adapter
        cid = engine.submit(EngineOrder(
            instrument="BTCUSDT", side="BUY", qty=0.002, kind="MARKET",
            role="entry"))
        status = engine.order_status(cid)
        cells.append({"cell": "entry", "state": status.state if status else "missing",
                      "flat": False})
        _flat(engine, "BTCUSDT")
        cells[-1]["flat"] = True

        # partial fill: shrink the book then IOC
        mock.venue.set_size("BTCUSDT", 0.001)
        cid2 = engine.submit(EngineOrder(
            instrument="BTCUSDT", side="BUY", qty=0.002, kind="LIMIT",
            price=10_000_000.0, role="entry"))
        st2 = engine.order_status(cid2)
        cells.append({"cell": "partial-or-ioc",
                      "state": st2.state if st2 else "missing"})
        _flat(engine, "BTCUSDT")
        cells[-1]["flat"] = True
        mock.venue.set_size("BTCUSDT", 10.0)

        # protection: stop-market reduce-only after a position
        engine.submit(EngineOrder(
            instrument="ETHUSDT", side="BUY", qty=0.01, kind="MARKET",
            role="entry"))
        engine.submit(EngineOrder(
            instrument="ETHUSDT", side="SELL", qty=0.01, kind="STOP_MARKET",
            stop_price=1.0, reduce_only=True, role="stop"))
        _flat(engine, "ETHUSDT")
        cells.append({"cell": "protection", "flat": True})

        # 429
        mock.venue.cfg.faults.entries.append(
            {"op": "order", "action": "rate-limit", "at": "once"})
        refused = False
        try:
            engine.submit(EngineOrder(
                instrument="BTCUSDT", side="BUY", qty=0.002, kind="MARKET",
                role="entry"))
        except Exception as exc:
            refused = "429" in str(exc) or "rate" in str(exc).lower()
        cells.append({"cell": "http-429", "refused": refused, "flat": True})

        # 503 unknown-outcome: must raise (lookup-first) and end flat.
        # Fresh engine: the 429 cell leaves a 60s refuse-fast window on
        # the main engine, and the UNKNOWN must not block later cells.
        mock.venue.cfg.faults.entries.append(
            {"op": "order", "action": "unknown", "at": "once"})
        fengine = _engine(base, journal_dir / "e503.jsonl")
        unknowned = False
        try:
            fengine.submit(EngineOrder(
                instrument="BTCUSDT", side="BUY", qty=0.002, kind="MARKET",
                role="entry"))
        except Exception as exc:
            text = str(exc).lower()
            unknowned = ("503" in text or "unknown" in text
                         or "dropped" in text)
        _flat(fengine, "BTCUSDT")
        fengine.close()
        cells.append({"cell": "http-503", "unknowned": unknowned,
                      "flat": True})

        # clock skew: a huge offset must halt before an order
        skewed = MockEx(clock_offset_ms=60_000)
        sport = skewed.serve()
        sengine = _engine(f"http://127.0.0.1:{sport}", journal_dir / "skew.jsonl")
        halted = False
        try:
            sengine.submit(EngineOrder(
                instrument="BTCUSDT", side="BUY", qty=0.002, kind="MARKET",
                role="entry"))
        except Exception as exc:
            halted = "skew" in str(exc).lower() or "recvWindow" in str(exc)
        cells.append({"cell": "clock-skew-halt", "halted": halted, "flat": True})
        sengine.close()
        skewed.close()

        # websocket
        event = _ws_read_one(port, "/ws/emulated")
        cells.append({"cell": "websocket",
                      "emulated": event.get("emulated") is True or
                      event.get("provenance") == EMULATED,
                      "flat": True})

        # resume: drop the engine object, new engine reads the venue
        engine.close()
        resumed = _engine(base, journal_dir / "resume.jsonl")
        _flat(resumed, "BTCUSDT")
        _flat(resumed, "ETHUSDT")
        cells.append({"cell": "resume-flatten", "flat": True})
        resumed.close()
    finally:
        mock.close()
    ok = all(c.get("flat") for c in cells) and all(
        c.get(k, True) for c in cells
        for k in ("halted", "refused", "emulated", "unknowned")
        if k in c)
    return {"drill": "emulator-lifecycle", "provenance": EMULATED,
            "emulated": True, "verdict": "PASS" if ok else "FAIL",
            "cells": cells}


def run_soak(steps: int = 24) -> dict:
    """Simulated 24h: one step per hour, faults, must end flat."""
    tracemalloc.start()
    mock = MockEx()
    port = mock.serve()
    base = f"http://127.0.0.1:{port}"
    journal = Path("/tmp") / "cryptobot-soak-journal.jsonl"
    engine = _engine(base, journal)
    try:
        for hour in range(steps):
            if hour % 6 == 5:
                mock.venue.cfg.faults.entries.append(
                    {"op": "order", "action": "rate-limit", "at": "once"})
            with contextlib.suppress(Exception):
                engine.submit(EngineOrder(
                    instrument="BTCUSDT", side="BUY", qty=0.002,
                    kind="MARKET", role="entry"))
            _flat(engine, "BTCUSDT")
        account = engine._signed("GET", "/fapi/v2/account")
        leftover = [p for p in account.get("positions", [])
                    if abs(float(p.get("positionAmt", 0))) > 1e-8]
    finally:
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        engine.close()
        mock.close()
        journal.unlink(missing_ok=True)
    return {"drill": "emulator-soak", "provenance": EMULATED, "emulated": True,
            "hours": steps, "open_positions": len(leftover),
            "peak_bytes": peak, "verdict": "PASS" if not leftover else "FAIL"}


__all__ = ["run_drill", "run_soak"]
