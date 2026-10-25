"""netguard against real sockets on loopback, through the code the bot really uses.

``socket.create_connection(("fapi.binance.com", port))`` must reach a local server when the
(injected) DoH answer is 127.0.0.1, and the live adapter's transport, the market-data REST
client and the websocket client must need nothing but ``install`` -- no logic change.
TLS: SNI and certificate verification still use the original hostname.

The suite-wide network guard stays active for everything except the hostname check in
``create_connection``/``urlopen`` (which would refuse a non-loopback *name* before DNS runs):
``socket.getaddrinfo`` stays guarded, so if the shim failed to rewrite the name the lookup
raises instead of touching the internet, and ``socket.connect`` stays loopback-only.
"""
from __future__ import annotations

import json
import shutil
import socket
import ssl
import subprocess
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from cryptobot import netguard
from cryptobot.adapters.binance_live import UrllibTransport
from cryptobot.cli import main as cli_main
from cryptobot.market_data.discovery import urllib_json_get
from cryptobot.market_data.ws import WsClient, _accept_key

# Captured at import, i.e. before the autouse suite guard patches them for each test.
_CREATE_CONNECTION = socket.create_connection
_URLOPEN = urllib.request.urlopen
_OPENER_OPEN = urllib.request.OpenerDirector.open

HOSTS = ["fapi.binance.com", "fstream.binance.com", "demo-fapi.binance.com", "api.binance.com"]


@pytest.fixture
def shim(monkeypatch):
    """netguard installed with DoH answering 127.0.0.1; name-checking guards lifted.

    Order-independent on purpose: every process-global these tests lean on is reset before
    the assertion, so the file gives the same answer whichever file ran first.

    * A shim an earlier test left installed is uninstalled first. ``install()`` is a no-op
      that returns False while one is active, so without this the new ``lookup`` would
      never be consulted and the transport would dial the real venue.
    * ``urllib`` builds its opener once per process and caches it in ``_opener``, baking in
      whatever proxy the environment had at that moment; deleting the proxy variables is
      therefore not enough once an earlier test has called ``urlopen``.
    """
    for var in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY",
                "ALL_PROXY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("no_proxy", "*")
    monkeypatch.setattr(socket, "create_connection", _CREATE_CONNECTION)
    monkeypatch.setattr(urllib.request, "urlopen", _URLOPEN)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", _OPENER_OPEN)
    monkeypatch.setattr(urllib.request, "_opener", None)
    asked: list = []

    def lookup(name):
        asked.append(name)
        return ["127.0.0.1"], 60

    netguard.uninstall()  # a leftover install would starve `lookup` below
    assert netguard.install(lookup=lookup) is True
    yield asked
    netguard.uninstall()


def test_a_shim_left_installed_by_an_earlier_test_does_not_starve_the_next_one():
    """Regression for the v1.1.1 order-dependent failure.

    ``tests/unit/test_net_guard.py`` used to leave the process-global DoH shim installed, so
    the next ``shim`` fixture got a stale install (``install()`` returns False while one is
    active) and the real venue was dialled instead of 127.0.0.1. This test leaves exactly
    that state behind on purpose; the fixture's pre-install ``netguard.uninstall()`` is what
    clears it, and every test below re-installs with its own lookup.
    """
    assert netguard.install(lookup=lambda _name: (["203.0.113.99"], 60)) is True
    assert netguard.is_installed() is True


def _serve(handler) -> tuple:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(8)
    server.settimeout(10)

    def loop():
        try:
            while True:
                conn, _ = server.accept()
                threading.Thread(target=handler, args=(conn,), daemon=True).start()
        except OSError:
            return

    threading.Thread(target=loop, daemon=True).start()
    return server, server.getsockname()[1]


def test_create_connection_to_exchange_name_reaches_the_local_server(shim):
    def echo(conn):
        with conn:
            conn.sendall(b"hello:" + conn.recv(100))

    server, port = _serve(echo)
    try:
        for host in HOSTS:
            with socket.create_connection((host, port), timeout=5) as client:
                client.sendall(b"ping")
                assert client.recv(100) == b"hello:ping"
        assert sorted(set(shim)) == sorted(HOSTS)
    finally:
        server.close()


def test_without_the_shim_the_name_is_not_rewritten(monkeypatch):
    """Control: no install, so the (guarded) system lookup is used and refuses the name."""
    monkeypatch.setattr(socket, "create_connection", _CREATE_CONNECTION)
    assert netguard.is_installed() is False
    with pytest.raises(RuntimeError, match="external network blocked"):
        socket.create_connection(("fapi.binance.com", 9), timeout=1)


def test_non_exchange_names_still_go_to_the_system_resolver(shim):
    with pytest.raises(RuntimeError, match="external network blocked"):
        socket.getaddrinfo("example.com", 443)
    assert shim == []


class _Api(BaseHTTPRequestHandler):
    seen: list = []

    def do_GET(self):  # noqa: N802
        type(self).seen.append((self.path, self.headers.get("Host")))
        body = json.dumps({"serverTime": 1_700_000_000_000, "symbols": []}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def _http_server():
    _Api.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Api)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_live_adapter_transport_needs_only_the_install(shim):
    server = _http_server()
    try:
        transport = UrllibTransport(f"http://fapi.binance.com:{server.server_port}", 5.0)
        reply = transport.request("GET", "/fapi/v1/time", {}, {})
        assert reply["serverTime"] == 1_700_000_000_000
        # the request still carries the original hostname (what SNI/Host verification use)
        assert _Api.seen == [("/fapi/v1/time", f"fapi.binance.com:{server.server_port}")]
        assert shim == ["fapi.binance.com"]
    finally:
        server.shutdown()


def test_market_data_rest_client_needs_only_the_install(shim):
    server = _http_server()
    try:
        payload, _ms = urllib_json_get(
            f"http://fapi.binance.com:{server.server_port}/fapi/v1/exchangeInfo", 5.0)
        assert payload["symbols"] == []
        assert shim == ["fapi.binance.com"]
    finally:
        server.shutdown()


def _ws_server_handler(conn):
    with conn:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = conn.recv(4096)
            if not chunk:
                return
            data += chunk
        key = next(line.split(":", 1)[1].strip() for line in data.decode().split("\r\n")
                   if line.lower().startswith("sec-websocket-key"))
        conn.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                      "Connection: Upgrade\r\n"
                      f"Sec-WebSocket-Accept: {_accept_key(key)}\r\n\r\n").encode())
        payload = b'{"e":"bookTicker","s":"BTCUSDT"}'
        conn.sendall(bytes([0x81, len(payload)]) + payload)
        conn.recv(10)


def test_websocket_client_needs_only_the_install(shim):
    server, port = _serve(_ws_server_handler)
    try:
        client = WsClient.connect(f"ws://fstream.binance.com:{port}/ws/btcusdt@bookTicker",
                                  timeout_s=5.0)
        kind, payload = client.recv_message(timeout_s=5.0)
        client.native_socket.close()
        assert json.loads(payload)["s"] == "BTCUSDT"
        assert shim == ["fstream.binance.com"]
    finally:
        server.close()


# ------------------------------------------------------------------ TLS: SNI and certs
def _make_cert(tmp_path, name):
    cert, key = tmp_path / f"{name}.crt", tmp_path / f"{name}.key"
    done = subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
         "-out", str(cert), "-days", "2", "-subj", f"/CN={name}",
         "-addext", f"subjectAltName=DNS:{name}"],
        capture_output=True, text=True, check=False)
    if done.returncode != 0:
        pytest.skip(f"openssl cannot make a SAN certificate here: {done.stderr[-200:]}")
    return cert, key


def _tls_server(tmp_path, cert_name):
    cert, key = _make_cert(tmp_path, cert_name)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    sni: list = []
    context.sni_callback = lambda _sock, name, _ctx: sni.append(name)
    outcome: list = []

    def handler(conn):
        try:
            with context.wrap_socket(conn, server_side=True) as tls:
                tls.sendall(b"secure-hello")
                tls.recv(10)
                outcome.append("ok")
        except OSError as exc:
            outcome.append(type(exc).__name__)

    server, port = _serve(handler)
    return server, port, cert, sni, outcome


@pytest.mark.skipif(shutil.which("openssl") is None, reason="needs the openssl CLI")
def test_tls_sni_and_certificate_check_use_the_original_hostname(shim, tmp_path, monkeypatch):
    server, port, cert, sni, _outcome = _tls_server(tmp_path, "fapi.binance.com")
    monkeypatch.setenv("SSL_CERT_FILE", str(cert))
    try:
        context = ssl.create_default_context()
        with socket.create_connection(("fapi.binance.com", port), timeout=5) as raw, \
                context.wrap_socket(raw, server_hostname="fapi.binance.com") as tls:
            assert tls.recv(20) == b"secure-hello"
            assert tls.getpeercert()["subject"][0][0][1] == "fapi.binance.com"
        assert sni == ["fapi.binance.com"]  # SNI is the name, not 127.0.0.1
    finally:
        server.close()


@pytest.mark.skipif(shutil.which("openssl") is None, reason="needs the openssl CLI")
def test_tls_wrong_certificate_is_still_rejected(shim, tmp_path, monkeypatch):
    """The shim must not weaken verification: a trusted cert for another name fails."""
    server, port, cert, _sni, _outcome = _tls_server(tmp_path, "evil.example")
    monkeypatch.setenv("SSL_CERT_FILE", str(cert))
    try:
        context = ssl.create_default_context()
        with socket.create_connection(("fapi.binance.com", port), timeout=5) as raw, \
                pytest.raises(ssl.SSLCertVerificationError):
            context.wrap_socket(raw, server_hostname="fapi.binance.com")
    finally:
        server.close()


# ----------------------------------------------------------------- entry-point wiring
def test_cli_main_installs_from_env_only_when_flagged(monkeypatch):
    monkeypatch.delenv("CRYPTOBOT_DOH", raising=False)
    before = socket.getaddrinfo
    with pytest.raises(SystemExit):
        cli_main(["--help"])
    assert socket.getaddrinfo is before and not netguard.is_installed()

    monkeypatch.setenv("CRYPTOBOT_DOH", "1")
    try:
        with pytest.raises(SystemExit):
            cli_main(["--help"])
        assert netguard.is_installed() and socket.getaddrinfo is not before
    finally:
        netguard.uninstall()
    assert socket.getaddrinfo is before


def test_cli_main_calls_install_from_env_first(monkeypatch):
    calls: list = []
    monkeypatch.setattr(netguard, "install_from_env", lambda *a, **k: calls.append("env"))
    with pytest.raises(SystemExit):
        cli_main(["--help"])
    assert calls == ["env"]


# ------------------------------------------------- every exchange-facing tool is wired
def test_every_tool_that_dials_a_binance_or_okx_host_installs_netguard():
    import re
    from pathlib import Path

    tools = Path(__file__).resolve().parents[2] / "tools"
    host = re.compile(r"https?://[\w.-]*\b(?:fapi|fstream|api|demo-fapi|demo-fstream)"
                      r"\.binance\.com|wss?://[\w.-]*binance\.com|okx\.com")
    must = {"forward_c2", "forward_b4b", "forward_refresh", "demo_drill_live", "vision_pull",
            "capture_public", "capture_stream", "pivot_funding_capture", "extend_benchmark",
            "scan_universe"}
    found = {p.stem for p in tools.glob("*.py")
             if host.search(p.read_text(encoding="utf-8"))}
    for stem in sorted(must | found):
        text = (tools / f"{stem}.py").read_text(encoding="utf-8")
        main_src = text.split("\ndef main(", 1)[1].split("\ndef ", 1)[0]
        assert "install_from_env()" in main_src or "_install_netguard()" in main_src, stem
        if "_install_netguard()" in main_src:
            assert "netguard.install_from_env()" in text, stem
