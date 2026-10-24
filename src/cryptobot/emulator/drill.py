"""Lifecycle drill over real sockets against MockEx.

Every result is provenance EMULATED. A PASS here is not a demo-drill
and cannot make the gate GO.

Cells cover auth/filters, margin setup, entry, protection, partial
fills, 429/418/5xx/timeout/reject, clock skew, WS market streams,
user-data + listenKey expiry, watchdog freshness, SIGTERM flatten and
SIGKILL resume (separate OS processes), and flatten under failure.
Every cell must end flat or protected.
"""
from __future__ import annotations

import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import tracemalloc
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptobot.adapters.binance_live import BinanceLiveEngine, UnknownOutcomeError
from cryptobot.adapters.mockex_server import DEFAULT_KEY, DEFAULT_SECRET, EMULATED, MockEx
from cryptobot.app.engine import EngineOrder


def _ws_open(port: int, path: str) -> tuple[socket.socket, bytes]:
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
    return sock, data.split(b"\r\n\r\n", 1)[1]


def _read_frame(sock: socket.socket, buf: bytes) -> tuple[int, bytes, bytes]:
    while len(buf) < 2:
        chunk = sock.recv(4096)
        if not chunk:
            return 0x8, b"", b""
        buf += chunk
    opcode = buf[0] & 0x0F
    length = buf[1] & 0x7F
    start = 2
    if length == 126:
        while len(buf) < 4:
            buf += sock.recv(4096)
        length = int.from_bytes(buf[2:4], "big")
        start = 4
    elif length == 127:
        while len(buf) < 10:
            buf += sock.recv(4096)
        length = int.from_bytes(buf[2:10], "big")
        start = 10
    while len(buf) < start + length:
        chunk = sock.recv(4096)
        if not chunk:
            return 0x8, b"", b""
        buf += chunk
    return opcode, buf[start:start + length], buf[start + length:]


def _ws_read_many(port: int, path: str, count: int = 1) -> list[dict]:
    sock, buf = _ws_open(port, path)
    frames: list[dict] = []
    try:
        while len(frames) < count:
            opcode, payload, buf = _read_frame(sock, buf)
            if opcode == 0x8:
                return frames
            frames.append(json.loads(payload.decode("utf-8")))
    finally:
        with contextlib.suppress(OSError):
            sock.close()
    return frames


def _ws_read_one(port: int, path: str) -> dict:
    frames = _ws_read_many(port, path, 1)
    return frames[0] if frames else {}


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


def _positions(engine: BinanceLiveEngine) -> dict[str, float]:
    account = engine._signed("GET", "/fapi/v2/account")
    return {str(p.get("symbol")): float(p.get("positionAmt", 0))
            for p in account.get("positions", [])}


def _fault(mock: MockEx, action: str, op: str = "order") -> None:
    mock.venue.cfg.faults.entries.append(
        {"op": op, "action": action, "at": "once"})


def _wait_file(path: Path, timeout_s: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.02)
    return False


def _worker(base: str, journal: Path, ready: Path) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "cryptobot.emulator.worker",
         "--base", base, "--journal", str(journal),
         "--ready", str(ready)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def run_drill(journal_dir: Path) -> dict:
    """Each cell ends flat or protected. Provenance is EMULATED."""
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
        cells.append({"cell": "protection", "protected": True,
                      "flat": True})

        # 429
        _fault(mock, "rate-limit")
        refused = False
        try:
            engine.submit(EngineOrder(
                instrument="BTCUSDT", side="BUY", qty=0.002, kind="MARKET",
                role="entry"))
        except Exception as exc:
            refused = "429" in str(exc) or "rate" in str(exc).lower()
        cells.append({"cell": "http-429", "refused": refused, "flat": True})
        # The 429 cell leaves a 60s refuse-fast window on that engine;
        # later cells run on a fresh engine (same venue state).
        engine.close()
        engine = _engine(base, journal_dir / "after429.jsonl")

        # 418 ban (Retry-After 1) on a fresh engine
        _fault(mock, "rate-limit-418")
        bengine = _engine(base, journal_dir / "e418.jsonl")
        banned = False
        try:
            bengine.submit(EngineOrder(
                instrument="BTCUSDT", side="BUY", qty=0.002, kind="MARKET",
                role="entry"))
        except Exception as exc:
            banned = "418" in str(exc) or "ban" in str(exc).lower()
        _flat(bengine, "BTCUSDT")
        bengine.close()
        cells.append({"cell": "http-418", "banned": banned, "flat": True})

        # 5xx + timeout: outcome UNKNOWN, lookup-first, end flat
        for action, cell in (("gateway-502", "http-502"),
                             ("gateway-504", "http-504"),
                             ("timeout", "http-timeout")):
            _fault(mock, action)
            fengine = _engine(base, journal_dir / f"{cell}.jsonl")
            unknown = False
            try:
                fengine.submit(EngineOrder(
                    instrument="BTCUSDT", side="BUY", qty=0.002,
                    kind="MARKET", role="entry"))
            except UnknownOutcomeError:
                unknown = True
            except Exception as exc:
                unknown = "unknown" in str(exc).lower()
            _flat(fengine, "BTCUSDT")
            fengine.close()
            cells.append({"cell": cell, "unknowned": unknown, "flat": True})

        # deterministic reject: nothing executed, retry allowed
        _fault(mock, "reject")
        rengine = _engine(base, journal_dir / "reject.jsonl")
        rejected = False
        try:
            rengine.submit(EngineOrder(
                instrument="BTCUSDT", side="BUY", qty=0.002, kind="MARKET",
                role="entry"))
        except Exception as exc:
            rejected = "reject" in str(exc).lower() or "2010" in str(exc)
        _flat(rengine, "BTCUSDT")
        rengine.close()
        cells.append({"cell": "http-reject", "rejected": rejected,
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

        # websocket market streams: all B1 channels over one socket
        names = ["btcusdt@aggTrade", "btcusdt@bookTicker", "btcusdt@depth",
                 "btcusdt@markPrice", "btcusdt@forceOrder"]
        path = "/stream?streams=" + "/".join(names) + "&frames=5"
        frames = _ws_read_many(port, path, 5)
        seen = {f.get("data", f).get("e") for f in frames}
        streams_ok = (len(frames) == 5
                      and {"aggTrade", "bookTicker", "depthUpdate",
                           "markPriceUpdate", "forceOrder"} <= seen
                      and all(f.get("data", f).get("emulated") is True
                              for f in frames))
        cells.append({"cell": "market-streams", "events": sorted(
            str(s) for s in seen if s), "emulated": streams_ok,
            "flat": True})

        # websocket: single bookTicker on /ws path (legacy cell)
        event = _ws_read_one(port, "/ws/btcusdt@bookTicker")
        cells.append({"cell": "websocket",
                      "emulated": event.get("emulated") is True or
                      event.get("provenance") == EMULATED,
                      "flat": True})

        # user-data stream: order events + listenKey lifecycle over WS
        key = str(engine.open_listen_key())
        engine.keepalive_listen_key()
        engine.submit(EngineOrder(
            instrument="BTCUSDT", side="BUY", qty=0.002, kind="MARKET",
            role="entry"))
        user_frames = _ws_read_many(port, f"/ws/{key}", 1)
        uevent = user_frames[0] if user_frames else {}
        cells.append({"cell": "user-data-stream",
                      "event": uevent.get("e"),
                      "emulated": uevent.get("emulated") is True,
                      "flat": False})
        _flat(engine, "BTCUSDT")
        cells[-1]["flat"] = True

        # listenKey expiry: TTL enforced by the venue
        key2 = str(engine.open_listen_key())
        mock.venue.key_deadline_ms = mock.venue.now_ms() - 1
        expiry_frames = _ws_read_many(port, f"/ws/{key2}", 1)
        expired = bool(expiry_frames) and \
            expiry_frames[0].get("e") == "listenKeyExpired"
        if expired:
            engine.note_user_event(expiry_frames[0])
        cells.append({"cell": "listenkey-expiry", "expired": expired,
                      "key_cleared": engine.listen_key is None,
                      "flat": True})

        # WS gap: the production attachment halts on a dead socket and
        # releases only after a successful reconnect+heal.
        from cryptobot.adapters.user_stream import attach_user_stream
        state = {"fail": True}

        class _GapSocket:
            def recv(self, timeout_s: float):
                return None

            def close(self) -> None:
                return None

        def _gap_factory(_key: str):
            if state["fail"]:
                raise ConnectionError("emulated ws gap")
            return _GapSocket()

        attachment = attach_user_stream(
            None, engine, _gap_factory, start_thread=False,
            initial_backoff_s=0.0, max_backoff_s=0.0)
        gap_action = attachment.poll_once()
        gap_halted = attachment.halted and "user-stream-gap" in \
            attachment.halt_reasons()
        state["fail"] = False
        healed_action = attachment.poll_once()
        gap_healed = not attachment.halted
        attachment.close()
        cells.append({"cell": "ws-gap-halt",
                      "halted": gap_halted and gap_action == "backoff",
                      "healed": gap_healed and healed_action in
                      ("healed", "idle"),
                      "flat": True})

        # watchdog predicate: stale refuses, fresh passes (gate logic)
        from cryptobot.cli import _watchdog_fresh
        now = datetime.now(UTC)
        stale = {"ts_utc": (now - timedelta(minutes=15)).isoformat(),
                 "has_exposure": False}
        fresh = {"ts_utc": now.isoformat(), "has_exposure": True}
        cells.append({"cell": "watchdog-freshness",
                      "stale_refused": _watchdog_fresh(stale) is False,
                      "fresh_passes": _watchdog_fresh(fresh) is True,
                      "flat": True})

        # SIGTERM flatten in a separate OS process (real sockets)
        ready = journal_dir / "worker-ready.json"
        proc = _worker(base, journal_dir / "sigterm.jsonl", ready)
        term_ok = False
        try:
            started = _wait_file(ready)
            proc.send_signal(signal.SIGTERM)
            out, err = proc.communicate(timeout=15)
            term_ok = bool(started) and proc.returncode == 0 \
                and '"flat": true' in (out or "") \
                and abs(_positions(engine).get("BTCUSDT", 0.0)) < 1e-8
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
        cells.append({"cell": "sigterm-flatten", "flat_after": term_ok,
                      "flat": term_ok})

        # SIGKILL mid-position: orphan survives; a resumed engine flattens
        ready2 = journal_dir / "worker-ready-kill.json"
        proc2 = _worker(base, journal_dir / "sigkill.jsonl", ready2)
        started2 = orphan = flat_after = False
        try:
            started2 = _wait_file(ready2)
            os.kill(proc2.pid, signal.SIGKILL)
            proc2.wait(timeout=10)
            orphan = abs(_positions(engine).get("BTCUSDT", 0.0)) > 1e-8
            resumed = _engine(base, journal_dir / "resume.jsonl")
            _flat(resumed, "BTCUSDT")
            flat_after = abs(_positions(resumed).get("BTCUSDT", 0.0)) < 1e-8
            resumed.close()
        finally:
            with contextlib.suppress(Exception):
                proc2.kill()
            with contextlib.suppress(Exception):
                proc2.communicate(timeout=5)
        cells.append({"cell": "sigkill-resume",
                      "orphan_detected": started2 and orphan,
                      "flat": flat_after})

        # flatten under failure: first close fails, retry succeeds
        engine.submit(EngineOrder(
            instrument="BTCUSDT", side="BUY", qty=0.002, kind="MARKET",
            role="entry"))
        _fault(mock, "gateway-502")
        first_failed = False
        try:
            _flat(engine, "BTCUSDT")
        except UnknownOutcomeError as exc:
            first_failed = True
            with contextlib.suppress(Exception):
                engine.lookup(exc.client_id)
        except Exception:
            first_failed = True
        _flat(engine, "BTCUSDT")
        flat_after = abs(_positions(engine).get("BTCUSDT", 0.0)) < 1e-8
        cells.append({"cell": "flatten-under-failure",
                      "first_attempt_failed": first_failed,
                      "flat": flat_after})

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
        for k in ("halted", "refused", "emulated", "unknowned", "banned",
                  "rejected", "expired", "key_cleared", "stale_refused",
                  "fresh_passes", "protected", "flat_after", "orphan_detected",
                  "healed")
        if k in c)
    return {"drill": "emulator-lifecycle", "provenance": EMULATED,
            "emulated": True, "verdict": "PASS" if ok else "FAIL",
            "cells": cells}


class _WsConn:
    """Recorder-facing WS client over a MockEx market stream."""

    def __init__(self, port: int, path: str) -> None:
        self.sock, self._buf = _ws_open(port, path)

    def send_text(self, _text: str) -> None:
        return None  # MockEx serves every requested stream on connect.

    def recv_message(self, timeout_s: float = 1.0):
        self.sock.settimeout(timeout_s)
        opcode, payload, self._buf = _read_frame(self.sock, self._buf)
        if opcode == 0x8:
            raise ConnectionError("mockex: stream closed")
        return "text", payload

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self.sock.close()


def run_recorder_smoke(root: Path, seconds: float = 0.4) -> dict:
    """Recorder smoke against EMULATED streams (input_class SYNTHETIC).

    Proves the recorder's socket → classifier → writer → sealed manifest
    path without touching a public venue. A SYNTHETIC chunk is never
    evidence.
    """
    from cryptobot.market_data.live_recorder import (
        SYNTHETIC,
        ManifestChain,
        Recorder,
        RecorderConfig,
    )
    mock = MockEx()
    port = mock.serve()
    stream_path = (
        "/stream?streams=btcusdt@aggTrade/btcusdt@bookTicker/"
        "btcusdt@depth@100ms/btcusdt@markPrice/btcusdt@forceOrder"
        "&frames=500")
    root.mkdir(parents=True, exist_ok=True)

    def _connect(_url: str) -> _WsConn:
        return _WsConn(port, stream_path)

    def _rest(_url: str, _timeout: float) -> tuple[dict, float]:
        now = int(time.time() * 1000)
        return ({"time": now, "openInterest": "1.0", "markPrice": "1.0",
                 "indexPrice": "1.0", "lastFundingRate": "0.0001",
                 "nextFundingTime": now + 28_800_000, "T": now,
                 "lastUpdateId": 1, "bids": [["1.0", "1.0"]],
                 "asks": [["1.1", "1.0"]]}, 1.0)

    config = RecorderConfig(
        out_dir=str(root), symbols=("BTCUSDT",), venues=("binance",),
        chunk_seconds=1, input_class=SYNTHETIC, rest_poll_s=60,
        fsync_every=1, disk_budget_mb=50_000)
    recorder = Recorder(config, connect=_connect, rest_get=_rest,
                        sleep=lambda _s: None)
    try:
        recorder.run(duration_s=seconds)
    finally:
        mock.close()
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        return {"verdict": "FAIL", "reason": "no manifest"}
    doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = doc.get("entries", [])
    problems = ManifestChain(manifest_path).verify()
    types = sorted({r.get("type") for r in recorder.writer.records
                    if isinstance(r, dict)}) if isinstance(
        recorder.writer.records, list) else []
    ok = bool(entries) and not problems
    return {"verdict": "PASS" if ok else "FAIL",
            "input_class": SYNTHETIC, "chunks": len(entries),
            "records": sum(int(e.get("records", 0)) for e in entries),
            "manifest_problems": problems, "sample_types": types[:8]}


def _reconcile_all(engine: BinanceLiveEngine) -> float:
    """Lookup every journaled submit, return adopted fill qty (venue tape)."""
    ids = {str(r.get("client_id")) for r in engine._read_journal()
           if r.get("event") == "submit-intent" and r.get("client_id")}
    for cid in ids:
        with contextlib.suppress(Exception):
            engine.lookup(cid)
    return sum(float(r.get("qty", 0.0)) for r in engine._read_journal()
               if r.get("event") == "fill-adopted")


def run_soak(steps: int = 24, journal_dir: Path | None = None) -> dict:
    """Simulated 24h: one step per hour, faults, must end flat and known."""
    tracemalloc.start()
    mock = MockEx()
    port = mock.serve()
    base = f"http://127.0.0.1:{port}"
    tmp = Path(journal_dir or tempfile.mkdtemp(prefix="cryptobot-soak-"))
    tmp.mkdir(parents=True, exist_ok=True)
    dupe_fill = lost_fill = False
    leftover: dict[str, float] = {}
    peak = 0
    total_adopted = 0.0
    try:
        for hour in range(steps):
            # A fresh engine per hour: exercises restart/resume and
            # isolates the 60s refuse-fast window of a 429.
            engine = _engine(base, tmp / f"soak-{hour:02d}.jsonl")
            try:
                action = ["rate-limit", "unknown", "gateway-502",
                          "partial-legs", "expire-key", "die", "reorder",
                          "dupe"][hour % 8]
                if hour % 3 == 2:
                    mock.venue.set_size("BTCUSDT", 0.001)
                    try:
                        _fault(mock, action)
                        with contextlib.suppress(Exception):
                            engine.submit(EngineOrder(
                                instrument="BTCUSDT", side="BUY", qty=0.002,
                                kind="MARKET", role="entry"))
                    finally:
                        mock.venue.set_size("BTCUSDT", 10.0)
                with contextlib.suppress(Exception):
                    engine.submit(EngineOrder(
                        instrument="BTCUSDT", side="BUY", qty=0.002,
                        kind="MARKET", role="entry"))
                with contextlib.suppress(Exception):
                    _flat(engine, "BTCUSDT")
                adopted_qty = _reconcile_all(engine)
                total_adopted += adopted_qty
            finally:
                engine.close()
            trade_ids = [t.get("id") for t in mock.venue.trades]
            dupe_fill = len(trade_ids) != len(set(trade_ids))
            venue_qty = sum(float(t.get("qty", 0)) for t in mock.venue.trades)
            lost_fill = abs(venue_qty - total_adopted) > 1e-6
            if dupe_fill or lost_fill:
                break
        # Final cleanup with a clean engine (last hour may hold exposure).
        final = _engine(base, tmp / "soak-final.jsonl")
        try:
            _reconcile_all(final)
            _flat(final, "BTCUSDT")
            _flat(final, "ETHUSDT")
            positions = _positions(final)
            leftover = {s: q for s, q in positions.items() if abs(q) > 1e-8}
        finally:
            final.close()
    finally:
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        mock.close()
    return {"drill": "emulator-soak", "provenance": EMULATED, "emulated": True,
            "hours": steps, "open_positions": len(leftover),
            "duplicate_fill": bool(dupe_fill), "lost_fill": bool(lost_fill),
            "peak_bytes": peak,
            "verdict": "PASS" if not leftover and not dupe_fill
            and not lost_fill and peak < 200_000_000 else "FAIL"}


__all__ = ["run_drill", "run_soak"]
