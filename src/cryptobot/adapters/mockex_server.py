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
import socket
import threading
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
        return payload
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


class MockEx:
    def __init__(self, venue: SandboxVenue | None = None, *,
                 api_secret: str = DEFAULT_SECRET,
                 clock_offset_ms: int = 0) -> None:
        self.venue = venue or SandboxVenue(SandboxConfig())
        self.transport = SandboxTransport(self.venue)
        self.api_secret = api_secret.encode("utf-8")
        self.clock_offset_ms = int(clock_offset_ms)
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
                payload = json.dumps(_stamp(body) if not isinstance(body, list)
                                     else body).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("X-Cryptobot-Provenance", EMULATED)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def _error(self, exc: VenueHttpError) -> None:
                status = exc.status or 400
                doc = {"code": exc.code if exc.code is not None else -1000,
                       "msg": exc.msg, "emulated": True,
                       "provenance": EMULATED}
                payload = json.dumps(doc).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("X-Cryptobot-Provenance", EMULATED)
                if status in (418, 429):
                    self.send_header("Retry-After", "1")
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
                book = owner.venue.book("BTCUSDT")
                event = {"e": "bookTicker", "s": "BTCUSDT",
                         "b": f"{book['bid']:.2f}", "a": f"{book['ask']:.2f}",
                         "provenance": EMULATED, "emulated": True}
                queued = owner.venue.poll_stream()
                if isinstance(queued, dict):
                    queued = dict(queued)
                    queued["provenance"] = EMULATED
                    event = queued
                self.wfile.write(_ws_frame(json.dumps(event)))
                with contextlib.suppress(OSError):
                    self.connection.shutdown(socket.SHUT_RDWR)

        self.httpd = ThreadingHTTPServer((host, port), Handler)
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
