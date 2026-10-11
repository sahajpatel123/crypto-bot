"""WebSocket codec + loopback tests (Worker 2, E-006). No network: socketpair only."""
import base64
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
        try:
            sock.close()
        except OSError:
            pass


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
