"""Minimal stdlib WebSocket client for public market streams (Worker 2, E-006).

RFC 6455 over ``socket`` + ``ssl`` — no third-party dependency, matching the
project's stdlib-only data path. Speaks just enough protocol for Binance
public market-data streams: opening handshake, masked text frames, ping/pong
(auto-replied), close handshake, and fragmented message reassembly. No
extensions, no client-offered subprotocols.

Server messages arrive via ``recv_message()`` which returns complete
application messages only; protocol frames are handled internally.
"""
from __future__ import annotations

import base64
import hashlib
import os
import socket
import ssl
import struct
import time
from dataclasses import dataclass
from urllib.parse import urlparse

__all__ = ["WsClient", "WsClosed", "WsHandshakeError", "encode_frame", "GUID", "MAX_FRAME_BYTES"]

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

# Largest single frame the client will accept. Public market-data messages
# are KB-scale; anything bigger is a protocol fault, not data. The cap is
# checked before the payload is read, so a corrupt length cannot OOM the
# collector on a long capture.
MAX_FRAME_BYTES = 8 << 20

_OP_CONT = 0x0
_OP_TEXT = 0x1
_OP_BINARY = 0x2
_OP_CLOSE = 0x8
_OP_PING = 0x9
_OP_PONG = 0xA


class WsClosed(Exception):
    """The websocket connection closed (cleanly or by timeout/reset)."""


class WsHandshakeError(Exception):
    """The opening handshake failed."""


def _accept_key(key: str) -> str:
    digest = hashlib.sha1((key + GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def encode_frame(opcode: int, payload: bytes, *, fin: bool = True, mask: bool = True) -> bytes:
    """Encode one frame. Clients MUST mask (RFC 6455 §5.3); tests use mask=False for vectors."""
    first = (0x80 if fin else 0x00) | (opcode & 0x0F)
    length = len(payload)
    header = bytes([first])
    if length < 126:
        header += bytes([(0x80 if mask else 0x00) | length])
    elif length < (1 << 16):
        header += bytes([(0x80 if mask else 0x00) | 126]) + struct.pack("!H", length)
    else:
        header += bytes([(0x80 if mask else 0x00) | 127]) + struct.pack("!Q", length)
    if not mask:
        return header + payload
    mask_key = os.urandom(4)
    masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
    return header + mask_key + masked


@dataclass
class _DecodedFrame:
    fin: bool
    opcode: int
    payload: bytes


class WsClient:
    """Blocking single-connection client. One instance per route (market/public)."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._buf = bytearray()
        self._closed = False
        self.pings_received = 0
        self.pongs_sent = 0

    # -- construction ------------------------------------------------------
    @classmethod
    def connect(cls, url: str, *, timeout_s: float = 10.0) -> "WsClient":
        parts = urlparse(url)
        if parts.scheme not in ("wss", "ws"):
            raise ValueError(f"bad websocket scheme: {parts.scheme}")
        host = parts.hostname or ""
        port = parts.port or (443 if parts.scheme == "wss" else 80)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        raw = socket.create_connection((host, port), timeout=timeout_s)
        sock: socket.socket = raw
        if parts.scheme == "wss":
            context = ssl.create_default_context()
            sock = context.wrap_socket(raw, server_hostname=host)
        sock.settimeout(timeout_s)
        try:
            trailing = cls._handshake(sock, path, host, port)
        except (OSError, WsHandshakeError):
            sock.close()
            raise
        client = cls(sock)
        client._buf += trailing
        return client

    @staticmethod
    def _handshake(sock: socket.socket, path: str, host: str, port: int) -> bytes:
        """Run the opening handshake; returns bytes coalesced past the header."""
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(request.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(4096)
            if not chunk:
                raise WsHandshakeError("connection closed during handshake")
            response += chunk
        head, trailing = response.split(b"\r\n\r\n", 1)
        lines = head.decode("latin-1").split("\r\n")
        if not lines[0].startswith("HTTP/1.1 101"):
            raise WsHandshakeError(f"handshake rejected: {lines[0][:120]}")
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                name, value = line.split(":", 1)
                headers[name.strip().lower()] = value.strip()
        if headers.get("sec-websocket-accept", "") != _accept_key(key):
            raise WsHandshakeError("bad Sec-WebSocket-Accept")
        return trailing

    # -- receiving ---------------------------------------------------------
    def _read_exactly(self, n: int) -> bytes:
        while len(self._buf) < n:
            try:
                chunk = self._sock.recv(65536)
            except socket.timeout as exc:
                raise WsClosed(f"read timeout after {n} bytes wanted") from exc
            except OSError as exc:
                raise WsClosed(f"socket error: {exc}") from exc
            if not chunk:
                raise WsClosed("peer closed the TCP connection")
            self._buf += chunk
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    def _read_frame(self) -> _DecodedFrame:
        head = self._read_exactly(2)
        fin = bool(head[0] & 0x80)
        opcode = head[0] & 0x0F
        masked = bool(head[1] & 0x80)
        length = head[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._read_exactly(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._read_exactly(8))[0]
        if length > MAX_FRAME_BYTES:
            raise WsClosed(f"frame of {length} bytes exceeds the {MAX_FRAME_BYTES} cap")
        mask_key = self._read_exactly(4) if masked else b""
        payload = self._read_exactly(length)
        if masked:
            payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        return _DecodedFrame(fin, opcode, payload)

    def recv_message(self, timeout_s: float | None = None) -> tuple[str, bytes]:
        """Return the next complete (type, payload): type is 'text' or 'binary'.

        Answers pings, assembles fragments, and raises WsClosed on close frames,
        timeouts, or transport errors. ``timeout_s`` overrides the socket timeout
        for this call (None keeps the connection default).
        """
        if self._closed:
            raise WsClosed("client is closed")
        if timeout_s is not None:
            self._sock.settimeout(timeout_s)
        chunks: list[bytes] = []
        kind = ""
        while True:
            frame = self._read_frame()
            if frame.opcode == _OP_PING:
                self.pings_received += 1
                self._send_raw(_OP_PONG, frame.payload)
                self.pongs_sent += 1
                continue
            if frame.opcode == _OP_PONG:
                continue
            if frame.opcode == _OP_CLOSE:
                self._closed = True
                try:
                    self._send_raw(_OP_CLOSE, frame.payload)
                except OSError:
                    pass
                raise WsClosed(f"peer sent close (code/payload: {frame.payload!r})")
            if frame.opcode in (_OP_TEXT, _OP_BINARY):
                kind = "text" if frame.opcode == _OP_TEXT else "binary"
                chunks = [frame.payload]
            elif frame.opcode == _OP_CONT and chunks:
                chunks.append(frame.payload)
            else:
                raise WsClosed(f"unexpected opcode: {frame.opcode}")
            if frame.fin:
                return kind, b"".join(chunks)

    # -- sending -----------------------------------------------------------
    def _send_raw(self, opcode: int, payload: bytes) -> None:
        self._sock.sendall(encode_frame(opcode, payload, mask=True))

    def send_text(self, text: str) -> None:
        self._send_raw(_OP_TEXT, text.encode("utf-8"))

    def ping(self, payload: bytes = b"") -> None:
        self._send_raw(_OP_PING, payload)

    def close(self, code: int = 1000, reason: str = "") -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._send_raw(_OP_CLOSE, struct.pack("!H", code) + reason.encode("utf-8"))
            self._sock.settimeout(2.0)
            with _suppress_closed():
                self._read_frame()
        except OSError:
            pass
        finally:
            try:
                self._sock.close()
            except OSError:
                pass

    @property
    def native_socket(self) -> socket.socket:
        return self._sock


class _suppress_closed:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return exc_type is not None and issubclass(exc_type, (WsClosed, OSError, ValueError, struct.error))
