"""WebSocket codec + loopback tests (Worker 2, E-006). No network: socketpair only."""
import base64
import contextlib
import hashlib
import socket
import struct
import threading

import pytest

from cryptobot.market_data.ws import GUID, MAX_FRAME_BYTES, WsClient, WsClosed, encode_frame


def test_rfc6455_text_vector_unmasked():
    # RFC 6455 §5.7 example: "Hello" as a single unmasked text frame.
    assert encode_frame(0x1, b"Hello", mask=False) == bytes([0x81, 0x05]) + b"Hello"


def test_rfc6455_16bit_length():
    frame = encode_frame(0x2, bytes(256), mask=False)
    assert frame[:2] == bytes([0x82, 126])
    assert struct.unpack("!H", frame[2:4])[0] == 256


def test_rfc6455_64bit_length():
    frame = encode_frame(0x2, bytes(70000), mask=False)
    assert frame[:2] == bytes([0x82, 127])
    assert struct.unpack("!Q", frame[2:10])[0] == 70000


def test_masked_round_trip():
    payload = b'{"stream":"x"}'  # short length: mask key sits at bytes 2:6.
    frame = encode_frame(0x1, payload, mask=True)
    assert frame[1] & 0x80  # mask bit set: clients MUST mask.
    mask_key = frame[2:6]
    body = frame[6:]
    assert bytes(b ^ mask_key[i % 4] for i, b in enumerate(body)) == payload


def _server_script(sock, script):
    """Play server frames (unmasked) then answer exactly one pong/close read."""
    try:
        for opcode, payload, fin in script:
            sock.sendall(encode_frame(opcode, payload, fin=fin, mask=False))
        sock.settimeout(5.0)
        sock.recv(65536)  # client pong and/or close reply; content asserted by client side.
    except OSError:
        pass
    finally:
        with contextlib.suppress(OSError):
            sock.close()


def _loopback(script):
    client_sock, server_sock = socket.socketpair()
    thread = threading.Thread(target=_server_script, args=(server_sock, script), daemon=True)
    thread.start()
    return WsClient(client_sock), thread


def test_loopback_text_and_fragmented_reassembly():
    client, thread = _loopback([(0x1, b"Hello, ", True), (0x1, b"frag", False),
                                (0x0, b"ment", False), (0x0, b"ed", True)])
    assert client.recv_message(timeout_s=5.0) == ("text", b"Hello, ")
    assert client.recv_message(timeout_s=5.0) == ("text", b"fragmented")
    client.close()
    thread.join(timeout=5.0)


def test_loopback_ping_auto_pong():
    received = {}

    def server(sock):
        try:
            sock.sendall(encode_frame(0x9, b"hb", mask=False))
            sock.settimeout(5.0)
            data = sock.recv(65536)
            received["raw"] = data
            sock.sendall(encode_frame(0x1, b"after-ping", mask=False))
        except OSError:
            pass

    client_sock, server_sock = socket.socketpair()
    thread = threading.Thread(target=server, args=(server_sock,), daemon=True)
    thread.start()
    client = WsClient(client_sock)
    assert client.recv_message(timeout_s=5.0) == ("text", b"after-ping")
    raw = received["raw"]
    assert raw[0] & 0x0F == 0xA  # pong opcode.
    assert raw[1] & 0x80  # masked.
    assert client.pings_received == 1 and client.pongs_sent == 1
    client.close()
    thread.join(timeout=5.0)


def test_loopback_close_raises_closed():
    client, thread = _loopback([(0x8, struct.pack("!H", 1000), True)])
    with pytest.raises(WsClosed, match="peer sent close"):
        client.recv_message(timeout_s=5.0)
    thread.join(timeout=5.0)


def test_connect_rejects_bad_scheme():
    with pytest.raises(ValueError, match="scheme"):
        WsClient.connect("http://example.com/ws")


def test_handshake_preserves_coalesced_frame_bytes():
    def server(sock):
        try:
            request = b""
            while b"\r\n\r\n" not in request:
                request += sock.recv(4096)
            key = [ln for ln in request.decode("latin-1").split("\r\n")
                   if ln.lower().startswith("sec-websocket-key:")][0].split(":", 1)[1].strip()
            accept = base64.b64encode(hashlib.sha1((key + GUID).encode("ascii")).digest())
            sock.sendall(b"HTTP/1.1 101 Switching Protocols\r\n"
                          b"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                          b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n"
                          + encode_frame(0x1, b"coalesced", mask=False))
            sock.settimeout(5.0)
            sock.recv(65536)
        except OSError:
            pass

    client_sock, server_sock = socket.socketpair()
    thread = threading.Thread(target=server, args=(server_sock,), daemon=True)
    thread.start()
    trailing = WsClient._handshake(client_sock, "/ws", "example.com", 443)
    client = WsClient(client_sock)
    client._buf += trailing  # connect() tail: coalesced bytes join the read buffer.
    assert client.recv_message(timeout_s=5.0) == ("text", b"coalesced")
    client.close()
    thread.join(timeout=5.0)


def test_oversize_frame_rejected_before_payload_read():
    def server(sock):
        try:
            sock.sendall(bytes([0x82, 127]) + struct.pack("!Q", MAX_FRAME_BYTES + 1))
            sock.settimeout(5.0)
            sock.recv(65536)
        except OSError:
            pass

    client_sock, server_sock = socket.socketpair()
    thread = threading.Thread(target=server, args=(server_sock,), daemon=True)
    thread.start()
    client = WsClient(client_sock)
    with pytest.raises(WsClosed, match="exceeds"):
        client.recv_message(timeout_s=5.0)
    thread.join(timeout=5.0)


def _silent_pair():
    """Connected socketpair with no server thread (fully scripted writes)."""
    client_sock, server_sock = socket.socketpair()
    return WsClient(client_sock), server_sock


def test_nowait_drains_coalesced_frames_without_select():
    import select as _select

    client, server = _silent_pair()
    try:
        # Two frames in ONE kernel write: one recv grabs both; the second
        # would strand behind select without the app-buffer drain (E-009).
        server.sendall(encode_frame(0x1, b"first", mask=False)
                       + encode_frame(0x1, b"second", mask=False))
        assert client.recv_message_nowait() == ("text", b"first")
        # Kernel buffer is empty now (both frames arrived together), so
        # select reports nothing — the drain must not depend on it.
        assert _select.select([client.native_socket], [], [], 0.05) == ([], [], [])
        assert client.buffered_bytes > 0  # complete message sits in _buf.
        assert client.recv_message_nowait() == ("text", b"second")
        assert client.buffered_bytes == 0
    finally:
        server.close()


def test_nowait_returns_none_fast_when_idle():
    import time as _time

    client, server = _silent_pair()
    try:
        start = _time.perf_counter()
        assert client.recv_message_nowait() is None
        assert _time.perf_counter() - start < 1.0  # never blocks.
    finally:
        server.close()


def test_nowait_holds_partial_fragment_byte_identical():
    client, server = _silent_pair()
    try:
        server.sendall(encode_frame(0x1, b"frag", fin=False, mask=False))
        assert client.recv_message_nowait() is None  # incomplete: wait.
        before = bytes(client._buf)
        assert client.recv_message_nowait() is None  # repeatable, no consume.
        assert bytes(client._buf) == before
        server.sendall(encode_frame(0x0, b"ment", fin=True, mask=False))
        assert client.recv_message_nowait() == ("text", b"fragment")
    finally:
        server.close()


def test_nowait_answers_ping_and_continues():
    client, server = _silent_pair()
    try:
        server.sendall(encode_frame(0x9, b"hb", mask=False)
                       + encode_frame(0x1, b"data", mask=False))
        assert client.recv_message_nowait() == ("text", b"data")
        assert (client.pings_received, client.pongs_sent) == (1, 1)
        server.settimeout(5.0)
        raw = server.recv(65536)
        assert raw[0] & 0x0F == 0xA and raw[1] & 0x80
    finally:
        server.close()


def test_nowait_close_and_oversize_raise():
    client, server = _silent_pair()
    try:
        server.sendall(encode_frame(0x8, struct.pack("!H", 1000), mask=False))
        with pytest.raises(WsClosed, match="peer sent close"):
            client.recv_message_nowait()
    finally:
        server.close()
    client2, server2 = _silent_pair()
    try:
        server2.sendall(bytes([0x82, 127]) + struct.pack("!Q", MAX_FRAME_BYTES + 1))
        with pytest.raises(WsClosed, match="exceeds"):
            client2.recv_message_nowait()
    finally:
        server2.close()


def test_nowait_peer_eof_raises_closed():
    client, server = _silent_pair()
    server.close()  # EOF is genuine closure, not absence of data.
    with pytest.raises(WsClosed, match="peer closed"):
        client.recv_message_nowait()


def test_blocking_recv_prefers_buffered_before_waiting():
    client, server = _silent_pair()
    try:
        server.sendall(encode_frame(0x1, b"buffered", mask=False)
                       + encode_frame(0x1, b"next", mask=False))
        assert client.recv_message(timeout_s=5.0) == ("text", b"buffered")
        # Second message arrives from the buffer even though the kernel
        # socket is drained and quiet (no select dependency).
        assert client.recv_message(timeout_s=5.0) == ("text", b"next")
    finally:
        server.close()


@pytest.mark.skipif(__import__("shutil").which("openssl") is None,
                    reason="needs openssl CLI for a throwaway cert")
def test_nowait_over_real_tls_drains_without_select(tmp_path):
    import select as _select
    import ssl
    import subprocess

    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
         "-keyout", str(key), "-out", str(cert), "-days", "1",
         "-subj", "/CN=localhost"],
        check=True, capture_output=True, timeout=60)
    raw_client, raw_server = socket.socketpair()
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(str(cert), str(key))
    client_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    client_ctx.check_hostname = False
    client_ctx.verify_mode = ssl.CERT_NONE
    server_tls = server_ctx.wrap_socket(raw_server, server_side=True,
                                        do_handshake_on_connect=False)
    client_tls = client_ctx.wrap_socket(raw_client, server_hostname="localhost",
                                        do_handshake_on_connect=False)
    server_tls.settimeout(5.0)
    client_tls.settimeout(5.0)
    done = {}

    def _shake(sock, name):
        try:
            sock.do_handshake()
            done[name] = True
        except OSError:
            pass

    waiter = threading.Thread(target=_shake, args=(server_tls, "server"),
                              daemon=True)
    waiter.start()
    _shake(client_tls, "client")
    waiter.join(timeout=5.0)
    assert done == {"server": True, "client": True}
    try:
        server_tls.sendall(encode_frame(0x1, b"one", mask=False)
                           + encode_frame(0x1, b"two", mask=False))
        client = WsClient(client_tls)
        assert client.recv_message_nowait() == ("text", b"one")
        assert _select.select([client_tls], [], [], 0.05) == ([], [], [])
        assert client.recv_message_nowait() == ("text", b"two")
        # Idle over TLS: SSLWantRead means absence, never an error.
        assert client.recv_message_nowait() is None
    finally:
        with contextlib.suppress(OSError):
            client_tls.close()
        with contextlib.suppress(OSError):
            server_tls.close()
