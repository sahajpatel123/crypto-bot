"""Self-tests for the default network guard (Worker 5, W5-24H).

Proves: loopback works, external dials fail loudly by default, local
URL schemes pass, and the opt-in profile genuinely lifts the guard
(verified with an unroutable TEST-NET dial that needs no internet).
"""
import socket
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from net_guard import ExternalNetworkBlocked, Guard, host_allowed

TEST_NET = "192.0.2.1"  # RFC 5737 TEST-NET-1: never routed, needs no internet.


@pytest.fixture(autouse=True)
def _no_leaked_doh_shim():
    """Never leak the process-global DoH shim into another test file.

    ``cryptobot.netguard`` keeps its install state in module globals, so a test
    here that installs it would silently break ``test_netguard_integration.py``
    when this file happens to run first. Tear it back down after every test.
    """
    yield
    from cryptobot import netguard  # noqa: PLC0415 - only needed for teardown

    netguard.uninstall()


def test_host_allowlist_predicate():
    for good in (None, "localhost", "LOCALHOST.", "a.localhost",
                 "127.0.0.1", "127.9.9.9", "::1"):
        assert host_allowed(good), good
    for bad in ("fapi.binance.com", "8.8.8.8", "10.0.0.1", "example.com",
                "example.invalid", TEST_NET, ""):
        assert not host_allowed(bad), bad


def test_loopback_socketpair_works_under_guard():
    a, b = socket.socketpair()
    try:
        a.sendall(b"ping")
        assert b.recv(4) == b"ping"
    finally:
        a.close()
        b.close()


def test_external_connect_blocked():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(ExternalNetworkBlocked):
            sock.connect((TEST_NET, 81))
    finally:
        sock.close()


def test_external_create_connection_and_getaddrinfo_blocked():
    with pytest.raises(ExternalNetworkBlocked):
        socket.create_connection((TEST_NET, 443), timeout=2)
    with pytest.raises(ExternalNetworkBlocked):
        socket.getaddrinfo("fapi.binance.com", 443)


def test_external_urlopen_blocked_local_schemes_allowed(tmp_path):
    with pytest.raises(ExternalNetworkBlocked):
        urllib.request.urlopen("https://fapi.binance.com/fapi/v1/time",
                               timeout=2)
    req = urllib.request.Request("https://example.com/x")
    with pytest.raises(ExternalNetworkBlocked):
        urllib.request.urlopen(req, timeout=2)
    payload = tmp_path / "local.txt"
    payload.write_text("local-only")
    assert urllib.request.urlopen(payload.as_uri(),
                                  timeout=2).read() == b"local-only"
    assert urllib.request.urlopen("data:text/plain,hi",
                                  timeout=2).read() == b"hi"


def test_guard_uninstall_restores_originals():
    before = (socket.socket.connect, socket.create_connection,
              socket.getaddrinfo)
    assert before[0].__qualname__ == "Guard.install.<locals>.guarded_connect"
    guard = Guard()
    guard.uninstall()  # fresh guard: nothing saved, must be a safe no-op.
    assert (socket.socket.connect, socket.create_connection,
            socket.getaddrinfo) == before


@pytest.mark.public_data
def test_optin_profile_runs_unguarded():
    """Opt-in proof: TEST-NET dial must fail with OSError, not the guard.

    Skipped by default; runs only under --public-data /
    CRYPTOBOT_PUBLIC_DATA=1. No internet needed (TEST-NET is unroutable).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    try:
        try:
            sock.connect((TEST_NET, 81))
        except ExternalNetworkBlocked:
            pytest.fail("guard still active in opt-in profile")
        except OSError:
            pass  # expected: unguarded dial to unroutable TEST-NET.
        else:
            pytest.fail("TEST-NET dial unexpectedly succeeded")
    finally:
        sock.close()
