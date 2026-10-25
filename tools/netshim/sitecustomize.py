"""cryptobot netshim -- standalone, opt-in DNS-over-HTTPS fallback for exchange hostnames.

Problem: some ISP resolvers (observed: Reliance Jio, India) answer *.binance.com and
*.okx.com with a sinkhole address (a dead host), so every TCP connect times out although
the exchange itself is reachable (TLS and the websocket upgrade succeed when the real
address is used).  This module re-resolves ONLY those hostnames through public
DNS-over-HTTPS resolvers that are addressed by IP, and returns the real addresses to the
caller.  The caller still connects with the original hostname, so SNI and certificate
validation are unchanged, and no other lookup is touched.

It never raises into the caller: any failure falls through to the system resolver, which
is exactly the behaviour without this file.  It is active only when CRYPTOBOT_DOH=1 (set in
the recorder's launchd plist); with the variable unset, importing it is a no-op.

Install: put this directory on PYTHONPATH.  The file is named sitecustomize.py so Python
imports it at start-up; it first chains to the interpreter's own sitecustomize (Homebrew
ships one), which it would otherwise shadow.  It is self-contained (stdlib only) and works
when cryptobot is not importable.

The block between the "netguard core" markers is a byte-identical copy of the same block in
src/cryptobot/netguard.py.  Do not edit it here: edit the library, then run
``python tools/netshim/sync_core.py``.  tests/unit/test_netguard_behavior.py fails on drift.
"""
from __future__ import annotations

import contextlib
import importlib.util
import ipaddress
import json
import os
import random
import socket
import ssl
import sys
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping

_HERE = os.path.dirname(os.path.abspath(__file__))


def _chain_previous() -> None:
    """Run the interpreter's own sitecustomize, which this file shadows."""
    for entry in list(sys.path):
        try:
            if not entry or os.path.abspath(entry) == _HERE:
                continue
            candidate = os.path.join(entry, "sitecustomize.py")
            if os.path.isfile(candidate):
                spec = importlib.util.spec_from_file_location("_chained_sitecustomize", candidate)
                if spec is not None and spec.loader is not None:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                return
        except Exception:  # noqa: BLE001 - never break interpreter start-up
            return


# --- netguard core: keep byte-identical with tools/netshim/sitecustomize.py ---------------
ENV_FLAG = "CRYPTOBOT_DOH"
ENV_SUFFIXES = "CRYPTOBOT_DOH_SUFFIXES"
DEFAULT_SUFFIXES = ("binance.com", "okx.com")
RESOLVERS = (
    "https://1.1.1.1/dns-query?name={name}&type=A",
    "https://8.8.8.8/resolve?name={name}&type=A",
    "https://1.0.0.1/dns-query?name={name}&type=A",
    "https://8.8.4.4/resolve?name={name}&type=A",
)
TTL_MIN_S = 30
TTL_MAX_S = 300
STALE_MAX_S = 86400
FAIL_BACKOFF_S = 10.0
CACHE_MAX = 256
HTTP_TIMEOUT_S = 4.0
MAX_REPLY_BYTES = 65536
DOH_DEADLINE_S = 6.0  # total budget over all resolvers for one name
_NOTE_EVERY_S = 600.0

_lock = threading.RLock()  # re-entrant: a signal handler resolving a name must not deadlock
_tls = threading.local()
_rng = random.Random()  # private RNG: never disturbs the caller's global random state
_installed = False
_suffixes: tuple = DEFAULT_SUFFIXES
_real = socket.getaddrinfo
_previous = socket.getaddrinfo
_lookup: Callable | None = None
_clock: Callable = time.time  # wall time: monotonic stops during sleep on macOS
_first_real: Callable | None = None  # the resolver before the very first install
_cache: dict = {}  # name -> (expires, fetched, addresses)
_fail_until: dict = {}
_gates: dict = {}
_noted: dict = {}


def _note(key: str, message: str) -> None:
    now = time.monotonic()
    with _lock:
        if now - _noted.get(key, -1e9) < _NOTE_EVERY_S:
            return
        _noted[key] = now
    with contextlib.suppress(Exception):
        sys.stderr.write("[netguard] " + message + "\n")
        sys.stderr.flush()


def _parse_suffixes(raw) -> tuple:
    parts = (s.strip().lower().lstrip(".") for s in str(raw).split(","))
    return tuple(s for s in parts if s)


def matches(host) -> bool:
    """True for hostnames the shim may re-resolve; never IP literals, bytes or None."""
    try:
        if not isinstance(host, str):
            return False
        name = host.lower().rstrip(".")
        if not name:
            return False
        with contextlib.suppress(ValueError):
            ipaddress.ip_address(name)
            return False
        return any(name == s or name.endswith("." + s) for s in _suffixes)
    except Exception:  # noqa: BLE001 - a predicate must not raise into the resolver
        return False


def parse_answer(payload) -> tuple:
    """DoH JSON -> (addresses, ttl_s); raises ValueError when there is nothing usable."""
    if not isinstance(payload, dict) or payload.get("Status") != 0:
        seen = payload.get("Status") if isinstance(payload, dict) else payload
        raise ValueError(f"DNS status {seen!r}")
    addresses: list = []
    ttl = TTL_MAX_S
    for answer in payload.get("Answer") or ():
        if not isinstance(answer, dict) or answer.get("type") != 1:
            continue
        try:
            address = ipaddress.IPv4Address(str(answer["data"]))
        except (KeyError, ValueError):
            continue
        if not address.is_global or address.is_multicast or address.is_reserved:
            # loopback/private/link-local/unspecified/multicast/reserved: never a real exchange
            continue
        addresses.append(str(address))
        with contextlib.suppress(TypeError, ValueError):
            ttl = min(ttl, int(answer.get("TTL", TTL_MAX_S)))
    if not addresses:
        raise ValueError("no usable A records")
    return addresses, max(TTL_MIN_S, min(ttl, TTL_MAX_S))


def _response_socket(reply):
    """Find urllib's underlying socket so each response read honors the total deadline."""
    for path in (("fp", "fp", "raw", "_sock"), ("fp", "raw", "_sock"),
                 ("fp", "fp", "_sock"), ("fp", "_sock")):
        candidate = reply
        try:
            for attribute in path:
                candidate = getattr(candidate, attribute)
        except Exception:  # noqa: BLE001 - urllib wrappers vary by Python version
            continue
        if callable(getattr(candidate, "settimeout", None)):
            return candidate
    return None


def _http_get_json(url: str):
    request = urllib.request.Request(
        url, headers={"accept": "application/dns-json", "user-agent": "cryptobot-netguard/1"})
    context = ssl.create_default_context()
    deadline = getattr(_tls, "deadline", None)
    if deadline is None:
        deadline = time.monotonic() + HTTP_TIMEOUT_S
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("DoH response deadline exceeded")
    with urllib.request.urlopen(request, timeout=min(HTTP_TIMEOUT_S, remaining),
                                context=context) as reply:  # noqa: S310
        response_socket = _response_socket(reply)
        if response_socket is None:
            raise OSError("cannot enforce DoH response deadline")
        payload = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("DoH response deadline exceeded")
            response_socket.settimeout(min(HTTP_TIMEOUT_S, remaining))
            chunk = reply.read(1)  # check the total deadline even when a peer drips bytes
            if not chunk:
                break
            payload.extend(chunk)
            if len(payload) > MAX_REPLY_BYTES:
                raise ValueError("DoH response exceeds size limit")
        return json.loads(payload.decode("utf-8"))


def doh_lookup(name: str, fetch: Callable | None = None) -> tuple:
    """Resolve A records through DoH resolvers addressed by IP; (addresses, ttl_s)."""
    get = fetch or _http_get_json
    quoted = urllib.parse.quote(name, safe="")
    failure = "no resolver tried"
    deadline = time.monotonic() + DOH_DEADLINE_S
    _tls.deadline = deadline  # the default fetch shortens its socket timeout to what is left
    try:
        for template in RESOLVERS:
            if time.monotonic() >= deadline:
                failure += " (deadline)"
                break
            try:
                return parse_answer(get(template.format(name=quoted)))
            except Exception as exc:  # noqa: BLE001 - try the next resolver
                failure = f"{type(exc).__name__}: {exc}"
    finally:
        _tls.deadline = None
    raise OSError(f"all DoH resolvers failed for {name} ({failure})")


def _peek(name: str, now: float) -> tuple:
    with _lock:
        return _cache.get(name), _fail_until.get(name, -1e9) > now


def _pick(entry) -> list:
    addresses = list(entry[2])
    with _lock:
        _rng.shuffle(addresses)
    return addresses


def _fresh(entry, now: float) -> bool:
    return entry is not None and entry[0] > now


def _stale_ok(entry, now: float) -> bool:
    return entry is not None and now - entry[1] <= STALE_MAX_S


def _refresh(name: str, entry, now: float):
    previous = getattr(_tls, "busy", False)
    _tls.busy = True  # a lookup that itself resolves an exchange name must not recurse
    try:
        addresses, ttl = (_lookup or doh_lookup)(name)
        addresses = [str(a) for a in addresses]
        if not addresses:
            raise ValueError("empty answer")
        ttl = max(TTL_MIN_S, min(int(ttl), TTL_MAX_S))
    except Exception as exc:  # noqa: BLE001
        with _lock:
            _fail_until[name] = _clock() + FAIL_BACKOFF_S  # after the fetch, not before
        if _stale_ok(entry, now):  # stale-while-error beats a sinkhole
            _note(name + "!", f"{name}: DoH failed, serving stale answer ({exc})")
            return _pick(entry)
        _note(name + "!", f"{name}: DoH failed, system resolver used ({exc})")
        return None
    finally:
        _tls.busy = previous
    fresh = (now + ttl, now, tuple(addresses))
    with _lock:
        _cache[name] = fresh
        _fail_until.pop(name, None)
        while len(_cache) > CACHE_MAX:
            _cache.pop(next(iter(_cache)))
    _note(name, f"{name} -> {','.join(addresses)} (ttl {ttl}s)")
    return _pick(fresh)


def _resolve(name: str):
    now = _clock()
    entry, failing = _peek(name, now)
    if _fresh(entry, now):
        return _pick(entry)
    if failing:
        return _pick(entry) if _stale_ok(entry, now) else None
    with _lock:
        gate = _gates.setdefault(name, threading.Lock())
    if not gate.acquire(blocking=False):  # another thread is already asking DoH
        if _stale_ok(entry, now):
            return _pick(entry)
        if not gate.acquire(timeout=DOH_DEADLINE_S + HTTP_TIMEOUT_S):
            return None  # the lookup in flight is stuck: defer to the system resolver
    try:
        now = _clock()
        entry, failing = _peek(name, now)
        if _fresh(entry, now):
            return _pick(entry)
        if failing:
            return _pick(entry) if _stale_ok(entry, now) else None
        return _refresh(name, entry, now)
    finally:
        gate.release()


def resolve(name: str):
    """Real addresses for an exchange hostname, or None to defer to the system resolver."""
    try:
        return _resolve(str(name).lower().rstrip("."))
    except Exception:  # noqa: BLE001
        return None


def _expand(real, name, addresses, port, family, type_, proto, flags) -> list:
    results: list = []
    for address in addresses:
        try:
            results.extend(real(address, port, family, type_, proto, flags | socket.AI_NUMERICHOST))
        except OSError:
            continue
    if results and flags & socket.AI_CANONNAME:  # getaddrinfo: canonical name on the first only
        first = results[0]
        results = [first[:3] + (name,) + first[4:]] + [
            r[:3] + ("",) + r[4:] for r in results[1:]]
    return results


def _getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    """Drop-in for socket.getaddrinfo; exchange hostnames come back with real addresses."""
    real = _real
    if getattr(_tls, "in_call", False):
        # re-entered through a wrapper chained on top of us: go straight to the base resolver
        return (_first_real or real)(host, port, family, type, proto, flags)
    _tls.in_call = True
    try:
        return _dispatch(real, host, port, family, type, proto, flags)
    finally:
        _tls.in_call = False


def _dispatch(real, host, port, family, type, proto, flags):
    try:
        if _installed and isinstance(host, (str, bytes, bytearray)) \
                and not flags & socket.AI_NUMERICHOST and not getattr(_tls, "busy", False):
            name = host.decode("ascii") if isinstance(host, (bytes, bytearray)) else host
            if matches(name):
                addresses = resolve(name)
                if addresses:
                    results = _expand(real, name.lower().rstrip("."), addresses, port,
                                      family, type, proto, flags)
                    if results:
                        return results
    except Exception:  # noqa: BLE001 - never raise because of the shim
        pass
    return real(host, port, family, type, proto, flags)


_getaddrinfo._cryptobot_netguard = True  # type: ignore[attr-defined]
_getaddrinfo._cryptobot_matches = matches  # type: ignore[attr-defined]
_getaddrinfo._cryptobot_real = _real  # type: ignore[attr-defined]  # updated by install()


def is_installed() -> bool:
    return _installed


def system_getaddrinfo() -> Callable:
    """The resolver that was in place before install (the system one), for diagnostics."""
    current = socket.getaddrinfo
    return getattr(current, "_cryptobot_real", None) or current  # also sees the standalone shim


def install(*, suffixes=None, lookup: Callable | None = None,
            real_getaddrinfo: Callable | None = None, clock: Callable | None = None) -> bool:
    """Patch socket.getaddrinfo; True when this call installed it, False when already active.

    ``lookup(name) -> (addresses, ttl_s)`` and ``clock()`` are injection points for tests.
    """
    global _installed, _suffixes, _real, _previous, _lookup, _clock, _first_real
    with _lock:
        if _installed or getattr(socket.getaddrinfo, "_cryptobot_netguard", False):
            return False
        if suffixes is None:
            _suffixes = DEFAULT_SUFFIXES
        else:
            raw = suffixes if isinstance(suffixes, str) else ",".join(suffixes)
            _suffixes = _parse_suffixes(raw) or DEFAULT_SUFFIXES
        _previous = socket.getaddrinfo
        _real = real_getaddrinfo or _previous
        if _first_real is None:
            _first_real = _real
        _getaddrinfo._cryptobot_real = _real  # type: ignore[attr-defined]
        _lookup = lookup
        _clock = clock or time.time
        _cache.clear()
        _fail_until.clear()
        _gates.clear()
        _noted.clear()
        _installed = True
        socket.getaddrinfo = _getaddrinfo
        return True


def uninstall() -> bool:
    """Restore the resolver that install() replaced; idempotent, for tests and shutdown."""
    global _installed, _suffixes, _lookup, _clock, _first_real
    with _lock:
        if not _installed:
            return False
        _installed = False  # a wrapper someone chained on top now passes straight through
        if socket.getaddrinfo is _getaddrinfo:
            socket.getaddrinfo = _previous
            _first_real = None
        _suffixes = DEFAULT_SUFFIXES
        _lookup = None
        _clock = time.time
        _cache.clear()
        _fail_until.clear()
        _gates.clear()
        return True


def install_from_env(environ: Mapping | None = None) -> bool:
    """Install only when CRYPTOBOT_DOH=1; never raises.  The default is OFF."""
    try:
        env = os.environ if environ is None else environ
        if env.get(ENV_FLAG, "") != "1":
            return False
        raw = env.get(ENV_SUFFIXES)
        suffixes = _parse_suffixes(raw) if raw is not None else None
        return install(suffixes=suffixes or None)
    except Exception:  # noqa: BLE001
        return False
# --- end netguard core ---------------------------------------------------------------------

_chain_previous()
install_from_env()
