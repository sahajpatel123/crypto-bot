"""Default network guard for the ordinary test suite (Worker 5, W5-24H).

The ordinary suite must never touch the external network: every socket or
HTTP path in tests runs against loopback pairs, fakes, or recorded
fixtures. This module blocks external dials loudly (instead of letting an
unmocked path reach the internet), while loopback stays fully usable.

Profiles:
- Default (no flag/env): guard ON for every test. Tests marked
  ``@pytest.mark.public_data`` are SKIPPED (they need the opt-in profile).
- Opt-in (``pytest --public-data`` or ``CRYPTOBOT_PUBLIC_DATA=1``): guard
  stays ON for unmarked tests; only ``public_data``-marked tests run
  unguarded. Genuine public-data integration tests belong in this profile.

Guarded entry points (all source call sites use these module attributes):
``socket.socket.connect``, ``socket.create_connection``,
``socket.getaddrinfo`` (blocks before any resolver traffic),
``urllib.request.urlopen`` and ``urllib.request.OpenerDirector.open``.
``file:``/``data:`` URLs and AF_UNIX sockets are local and stay allowed.
"""

import contextlib
import ipaddress
import socket
import urllib.parse
import urllib.request

OPT_IN_ENV = "CRYPTOBOT_PUBLIC_DATA"
MARKER = "public_data"


class ExternalNetworkBlocked(RuntimeError):
    """An unmocked test path attempted external network access."""


def host_allowed(host) -> bool:
    """True for loopback literals and localhost names only (no DNS)."""
    if host is None:
        return True
    text = str(host).strip().lower().rstrip(".")
    if text in ("localhost",):
        return True
    if text.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        return False


def _deny(host, port, what: str) -> None:
    raise ExternalNetworkBlocked(
        f"external network blocked in tests: {what} to "
        f"{host}:{port} (loopback allowed; genuine public-data tests "
        f"must be marked @{MARKER} and run under --public-data)")


def _check_host(host, port, what: str) -> None:
    if not host_allowed(host):
        _deny(host, port, what)


def _split_address(address):
    if isinstance(address, (tuple, list)) and len(address) >= 2:
        return address[0], address[1]
    return address, None


class Guard:
    """Installable/restorable patch set. Use as a context manager."""

    def __init__(self) -> None:
        self._saved = []

    def install(self) -> "Guard":
        orig_connect = socket.socket.connect
        orig_create = socket.create_connection
        orig_getaddrinfo = socket.getaddrinfo
        orig_urlopen = urllib.request.urlopen
        orig_opener_open = urllib.request.OpenerDirector.open

        def guarded_connect(sock, address):
            if sock.family == getattr(socket, "AF_UNIX", object()):
                return orig_connect(sock, address)
            host, port = _split_address(address)
            _check_host(host, port, "socket.connect")
            return orig_connect(sock, address)

        def guarded_create_connection(address, *args, **kwargs):
            host, port = _split_address(address)
            _check_host(host, port, "socket.create_connection")
            return orig_create(address, *args, **kwargs)

        def guarded_getaddrinfo(host, port, *args, **kwargs):
            _check_host(host, port, "socket.getaddrinfo")
            return orig_getaddrinfo(host, port, *args, **kwargs)

        def guarded_urlopen(url, *args, **kwargs):
            _check_url(url)
            return orig_urlopen(url, *args, **kwargs)

        def guarded_opener_open(opener, fullurl, *args, **kwargs):
            _check_url(fullurl)
            return orig_opener_open(opener, fullurl, *args, **kwargs)

        socket.socket.connect = guarded_connect
        socket.create_connection = guarded_create_connection
        socket.getaddrinfo = guarded_getaddrinfo
        urllib.request.urlopen = guarded_urlopen
        urllib.request.OpenerDirector.open = guarded_opener_open
        self._saved = [
            ("socket.socket.connect", socket.socket, "connect", orig_connect),
            ("socket.create_connection", socket, "create_connection",
             orig_create),
            ("socket.getaddrinfo", socket, "getaddrinfo", orig_getaddrinfo),
            ("urllib.request.urlopen", urllib.request, "urlopen",
             orig_urlopen),
            ("urllib.request.OpenerDirector.open", urllib.request.OpenerDirector,
             "open", orig_opener_open),
        ]
        return self

    def uninstall(self) -> None:
        for _, obj, name, original in self._saved:
            with contextlib.suppress(AttributeError, TypeError):
                setattr(obj, name, original)
        self._saved = []

    def __enter__(self) -> "Guard":
        return self.install()

    def __exit__(self, *exc) -> bool:
        self.uninstall()
        return False


def _check_url(url) -> None:
    if hasattr(url, "get_full_url"):
        with contextlib.suppress(Exception):
            url = url.get_full_url()
    if not isinstance(url, str):
        return
    parts = urllib.parse.urlsplit(url)
    scheme = (parts.scheme or "").lower()
    if scheme in ("file", "data"):
        return  # local-only schemes, no socket.
    if scheme in ("http", "https"):
        host = parts.hostname
        port = parts.port or (443 if scheme == "https" else 80)
        _check_host(host, port, f"urllib {scheme}")
        return
    _deny(parts.hostname or url, parts.port, f"urllib {scheme or 'unknown'}")
