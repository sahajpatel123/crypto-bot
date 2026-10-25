"""Localhost HTTP + WebSocket Binance USD-M emulator.

Wraps SandboxVenue. Every response is labelled EMULATED. This is not
a venue and cannot satisfy a real demo-drill or a GO gate.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
import select
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

from cryptobot.adapters.binance_live import VenueHttpError
from cryptobot.adapters.sandbox_venue import (
    LABEL_KEY,
    SandboxConfig,
    SandboxTransport,
    SandboxVenue,
)

EMULATED = "EMULATED"
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
DEFAULT_KEY = "emulated-key"
DEFAULT_SECRET = "emulated-secret"


def _stamp(payload):
    if isinstance(payload, dict):
        payload = dict(payload)
        payload[LABEL_KEY] = True
        payload["emulated"] = True
        payload["provenance"] = EMULATED
        return payload
    if isinstance(payload, list):
        return [_stamp(row) if isinstance(row, dict) else row
                for row in payload]
    return payload


def _ws_frame(text: str) -> bytes:
    data = text.encode("utf-8")
    n = len(data)
    if n < 126:
        header = bytes([0x81, n])
    elif n < 65536:
        header = bytes([0x81, 126]) + n.to_bytes(2, "big")
    else:
        header = bytes([0x81, 127]) + n.to_bytes(8, "big")
    return header + data


def _client_gone(connection) -> bool:
    """Peek the client socket: EOF or a close frame means it left."""
    try:
        ready, _, _ = select.select([connection], [], [], 0)
        if not ready:
            return False
        data = connection.recv(2, socket.MSG_PEEK)
    except OSError:
        return True
    if not data:
        return True
    return (data[0] & 0x0F) == 0x8


class _QuietServer(ThreadingHTTPServer):
    """ThreadingHTTPServer that ignores client resets during fault tests."""

    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        import sys
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, BrokenPipeError, OSError)):
            return None
        return super().handle_error(request, client_address)


class MockEx:
    def __init__(self, venue: SandboxVenue | None = None, *,
                 api_secret: str = DEFAULT_SECRET,
                 clock_offset_ms: int = 0) -> None:
        self.venue = venue or SandboxVenue(SandboxConfig())
        self.transport = SandboxTransport(self.venue)
        self.api_secret = api_secret.encode("utf-8")
        self.clock_offset_ms = int(clock_offset_ms)
        # Requests refused at the door (bad signature / recvWindow) BEFORE
        # reaching the venue: {"method","path","code"}.
        self.refusals: list[dict] = []
        self.httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def serve(self, host: str = "127.0.0.1", port: int = 0) -> int:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt: str, *args) -> None:
                return

            def do_GET(self):  # noqa: N802
                self._dispatch()

            def do_POST(self):  # noqa: N802
                self._dispatch()

            def do_PUT(self):  # noqa: N802
                self._dispatch()

            def do_DELETE(self):  # noqa: N802
                self._dispatch()

            def _dispatch(self) -> None:
                if self.headers.get("Upgrade", "").lower() == "websocket":
                    self._websocket()
                    return
                parts = urlsplit(self.path)
                raw = parts.query
                if self.command != "GET":
                    length = int(self.headers.get("Content-Length", "0") or 0)
                    raw = self.rfile.read(length).decode("utf-8")
                try:
                    params = owner._verified_params(raw)
                except VenueHttpError as exc:
                    owner.refusals.append({"method": self.command,
                                           "path": parts.path,
                                           "code": exc.code})
                    self._error(exc)
                    return
                try:
                    body = owner.transport.request(
                        self.command, parts.path, params,
                        {k: v for k, v in self.headers.items()})
                except VenueHttpError as exc:
                    self._error(exc)
                    return
                if isinstance(body, dict) and "serverTime" in body:
                    body = dict(body)
                    body["serverTime"] = int(body["serverTime"]) + owner.clock_offset_ms
                payload = json.dumps(_stamp(body)).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("X-Cryptobot-Provenance", EMULATED)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def _error(self, exc: VenueHttpError) -> None:
                status = exc.status or 0
                if status == 0:
                    # Simulated read timeout: no response, drop the
                    # connection so the client sees a transport error
                    # (the adapter maps that to UNKNOWN, never retry).
                    self.close_connection = True
                    return
                doc = {"code": exc.code if exc.code is not None else -1000,
                       "msg": exc.msg, "emulated": True,
                       "provenance": EMULATED}
                payload = json.dumps(doc).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("X-Cryptobot-Provenance", EMULATED)
                if status in (418, 429):
                    hint = getattr(exc, "retry_after_s", None)
                    self.send_header(
                        "Retry-After",
                        "1" if hint is None else str(int(hint)))
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def _websocket(self) -> None:
                key = self.headers.get("Sec-WebSocket-Key", "")
                accept = base64.b64encode(hashlib.sha1(
                    (key + _WS_GUID).encode("utf-8")).digest()).decode("ascii")
                self.send_response(101)
                self.send_header("Upgrade", "websocket")
                self.send_header("Connection", "Upgrade")
                self.send_header("Sec-WebSocket-Accept", accept)
                self.send_header("X-Cryptobot-Provenance", EMULATED)
                self.end_headers()
                try:
                    owner._ws_session(self)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    with contextlib.suppress(OSError):
                        self.connection.shutdown(socket.SHUT_RDWR)

        self.httpd = _QuietServer((host, port), Handler)
        self.httpd.daemon_threads = True
        bound = self.httpd.server_address[1]
        self._thread = threading.Thread(target=self.httpd.serve_forever,
                                        name="mockex", daemon=True)
        self._thread.start()
        return int(bound)

    def close(self) -> None:
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None

    # -- websocket sessions (market + user data) ---------------------------
    def _ws_session(self, handler) -> None:
        """Stream EMULATED frames until the client leaves or time cap."""
        parts = urlsplit(handler.path)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        limit = int(query.get("frames", "50"))
        names = self._stream_names(parts.path, query)
        user_key = self._user_key(parts.path)
        if user_key is not None:
            self.venue._expire_listen_key_if_due()
            if user_key != self.venue.listen_key:
                self._ws_send(handler, {"e": "listenKeyExpired",
                                        "E": self.venue.now_ms()})
                self._ws_close(handler, 1000, "listenKeyExpired")
                return
        deadline = time.monotonic() + 8.0
        sent = 0
        while sent < limit and time.monotonic() < deadline:
            if _client_gone(handler.connection):
                return
            if user_key is not None:
                try:
                    event = self.venue.poll_stream()
                except ConnectionError:
                    self._ws_close(handler, 1011, "stream died")
                    return
                if event is None:
                    self.venue._expire_listen_key_if_due()
                    time.sleep(0.02)
                    continue
                if event.get("e") == "listenKeyExpired":
                    self._ws_send(handler, event)
                    self._ws_close(handler, 1000, "listenKeyExpired")
                    return
            else:
                if not names:
                    return
                event = self._market_event(names[sent % len(names)], sent)
                if parts.path.startswith("/stream"):
                    event = {"stream": names[sent % len(names)],
                             "data": _stamp(event)}
            self._ws_send(handler, event)
            sent += 1
            time.sleep(0.02)
        self._ws_close(handler, 1000, "done")

    def _ws_send(self, handler, event: dict) -> None:
        handler.wfile.write(_ws_frame(json.dumps(_stamp(event))))
        handler.wfile.flush()

    @staticmethod
    def _ws_close(handler, code: int, reason: str) -> None:
        payload = code.to_bytes(2, "big") + reason.encode("utf-8")[:120]
        frame = bytes([0x88, len(payload)]) + payload
        with contextlib.suppress(OSError):
            handler.wfile.write(frame)
            handler.wfile.flush()
            handler.connection.shutdown(socket.SHUT_RDWR)

    def _user_key(self, path: str) -> str | None:
        if not path.startswith("/ws/"):
            return None
        last = path.rstrip("/").rsplit("/", 1)[-1]
        # Our listenKeys are `sandbox-<uuid>`; a market stream name always
        # contains '@' or is a bare symbol. Treat sandbox keys as private.
        if last.startswith("sandbox-"):
            return last
        return None

    @staticmethod
    def _stream_names(path: str, query: dict) -> list[str]:
        if query.get("streams"):
            return [s for s in query["streams"].split("/") if s]
        if path.startswith("/ws/"):
            tail = path[len("/ws/"):].strip("/")
            return [s for s in tail.split("/") if s]
        return ["btcusdt@bookTicker"]

    def _market_event(self, name: str, seq: int) -> dict:
        symbol = name.split("@", 1)[0].upper()
        stream = name.split("@", 1)[1].lower() if "@" in name else "bookticker"
        book = self.venue.book(symbol)
        mark = self.venue.mid(symbol)
        now = self.venue.now_ms()
        spec = self.venue_spec(symbol)
        if stream == "aggtrade":
            return {"e": "aggTrade", "E": now, "s": symbol,
                    "a": 1000 + seq, "p": f"{mark:.2f}", "q": "0.010",
                    "f": 1000 + seq, "l": 1000 + seq, "T": now,
                    "m": seq % 2 == 0}
        if stream == "depth":
            return {"e": "depthUpdate", "E": now, "T": now, "s": symbol,
                    "U": 2000 + seq, "u": 2001 + seq, "pu": 1999 + seq,
                    "b": [[f"{book['bid']:.2f}", "1.000"]],
                    "a": [[f"{book['ask']:.2f}", "1.000"]]}
        if stream == "markprice":
            return {"e": "markPriceUpdate", "E": now, "s": symbol,
                    "p": f"{mark:.2f}", "i": f"{mark:.2f}",
                    "P": f"{mark:.2f}", "r": str(spec["funding_8h"]),
                    "T": now + 28_800_000}
        if stream == "forceorder":
            return {"e": "forceOrder", "E": now, "o": {
                "s": symbol, "S": "SELL", "o": "LIMIT", "f": "IOC",
                "q": "0.010", "p": f"{mark * 0.99:.2f}",
                "ap": f"{mark * 0.99:.2f}", "X": "FILLED", "l": "0.010",
                "z": "0.010", "T": now}}
        return {"e": "bookTicker", "u": 3000 + seq, "s": symbol,
                "b": f"{book['bid']:.2f}", "B": "1.000",
                "a": f"{book['ask']:.2f}", "A": "1.000", "T": now}

    @staticmethod
    def venue_spec(symbol: str) -> dict:
        from cryptobot.adapters.sandbox_venue import SYMBOLS
        return SYMBOLS[symbol.upper()]

    def _verified_params(self, raw: str) -> dict:
        if "signature=" not in raw:
            return dict(parse_qsl(raw, keep_blank_values=True))
        head, sig = raw.rsplit("signature=", 1)
        signed = head[:-1] if head.endswith("&") else head
        expect = hmac.new(self.api_secret, signed.encode("utf-8"),
                          hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expect, sig):
            raise VenueHttpError(401, -1022, "Signature for this request is not valid")
        params = dict(parse_qsl(signed, keep_blank_values=True))
        if "timestamp" in params:
            ts = int(float(params["timestamp"]))
            window = int(float(params.get("recvWindow", "5000")))
            skew = abs((self.venue.now_ms() + self.clock_offset_ms) - ts)
            if skew > window:
                raise VenueHttpError(400, -1021, "Timestamp for this request is outside of the recvWindow")
        return params


__all__ = ["DEFAULT_KEY", "DEFAULT_SECRET", "EMULATED", "MockEx"]
