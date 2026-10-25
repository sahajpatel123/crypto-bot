"""Behaviour of the DNS-sinkhole guard, run against BOTH implementations.

``src/cryptobot/netguard.py`` (library) and ``tools/netshim/sitecustomize.py``
(standalone, must work with only its directory on PYTHONPATH) carry one core. Every test
here takes the ``ng`` fixture, which loads a fresh copy of each file in turn, so the two
cannot drift apart without a failure.  No test touches the network: the DoH lookup, the
system resolver and the clock are injected.
"""
from __future__ import annotations

import ast
import contextlib
import importlib.util
import os
import random
import socket
import subprocess
import sys
import textwrap
import threading
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = ROOT / "src" / "cryptobot" / "netguard.py"
STANDALONE = ROOT / "tools" / "netshim" / "sitecustomize.py"
IMPLS = {"library": LIBRARY, "standalone": STANDALONE}

SINKHOLE_V4 = "49.44.79.236"
SINKHOLE_V6 = "2405:200:1607:2820:41::36"
REAL_A = "13.224.10.1"
REAL_B = "13.224.10.2"
REAL_C = "13.224.10.3"

_loaded: list = []


def load_fresh(impl: str):
    """Import a fresh, independent copy of one implementation (module state is global)."""
    path = IMPLS[impl]
    spec = importlib.util.spec_from_file_location(f"_ng_{impl}_{len(_loaded)}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _loaded.append(module)
    return module


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Rig:
    """A fake DoH lookup, a fake system resolver and a fake clock around one module."""

    def __init__(self, module) -> None:
        self.ng = module
        self.clock = Clock()
        self.answer = ([REAL_A], 60)
        self.failure: Exception | None = None
        self.delay = 0.0
        self.lookup_calls: list = []
        self.system_calls: list = []
        self._lock = threading.Lock()

    def lookup(self, name):
        with self._lock:
            self.lookup_calls.append(name)
        if self.delay:
            time.sleep(self.delay)
        if self.failure is not None:
            raise self.failure
        return self.answer

    def system(self, host, port, family=0, type=0, proto=0, flags=0):
        """Synthetic getaddrinfo: names hit the ISP sinkhole, IPv4 literals resolve to
        themselves, honouring family/type/flags the way libc does."""
        with self._lock:
            self.system_calls.append((host, port, family, type, proto, flags))
        if isinstance(host, bytes):
            host = host.decode("ascii")
        number = int(port) if str(port).isdigit() else (443 if port == "https" else 0)
        try:
            socket.inet_pton(socket.AF_INET, host)
            literal = True
        except (OSError, TypeError):
            literal = False
        if literal:
            if family == socket.AF_INET6:
                raise socket.gaierror(socket.EAI_ADDRFAMILY, "no v6 for a v4 literal")
            canon = host if flags & socket.AI_CANONNAME else ""
            types = (type,) if type else (socket.SOCK_STREAM, socket.SOCK_DGRAM)
            return [(socket.AF_INET, t, 0, canon if i == 0 else "", (host, number))
                    for i, t in enumerate(types)]
        if flags & socket.AI_NUMERICHOST:
            raise socket.gaierror(socket.EAI_NONAME, "numeric host required")
        if family == socket.AF_INET6:
            return [(socket.AF_INET6, socket.SOCK_STREAM, 0, "", (SINKHOLE_V6, number, 0, 0))]
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (SINKHOLE_V4, number))]

    def install(self, **kwargs) -> bool:
        return self.ng.install(lookup=self.lookup, real_getaddrinfo=self.system,
                               clock=self.clock, **kwargs)

    def addresses(self, host="fapi.binance.com", port=443, **kwargs) -> list:
        return [r[4][0] for r in socket.getaddrinfo(host, port, **kwargs)]


@pytest.fixture(params=sorted(IMPLS))
def ng(request, monkeypatch):
    monkeypatch.delenv("CRYPTOBOT_DOH", raising=False)
    monkeypatch.delenv("CRYPTOBOT_DOH_SUFFIXES", raising=False)
    before = socket.getaddrinfo
    module = load_fresh(request.param)
    module.impl = request.param
    yield module
    module.uninstall()
    assert socket.getaddrinfo is before, "uninstall must restore the resolver"


@pytest.fixture
def rig(ng):
    return Rig(ng)


# --------------------------------------------------------------------- default OFF
def test_default_off_install_from_env_is_a_noop(ng):
    before = socket.getaddrinfo
    assert ng.install_from_env({}) is False
    assert socket.getaddrinfo is before
    assert ng.is_installed() is False


@pytest.mark.parametrize("value", ["", "0", "true", "yes", "on", "2", " 1", "1 "])
def test_only_exactly_one_enables(ng, value):
    before = socket.getaddrinfo
    assert ng.install_from_env({"CRYPTOBOT_DOH": value}) is False
    assert socket.getaddrinfo is before


def test_env_one_installs_and_uninstall_restores(ng):
    before = socket.getaddrinfo
    assert ng.install_from_env({"CRYPTOBOT_DOH": "1"}) is True
    assert socket.getaddrinfo is not before
    assert ng.is_installed() is True
    assert ng.uninstall() is True
    assert socket.getaddrinfo is before
    assert ng.uninstall() is False


def test_install_is_idempotent_and_does_not_double_wrap(rig, ng):
    assert rig.install() is True
    wrapper = socket.getaddrinfo
    assert rig.install() is False
    assert socket.getaddrinfo is wrapper


def test_install_from_env_never_raises(ng):
    class Hostile(dict):
        def get(self, *_a, **_k):
            raise RuntimeError("boom")

    assert ng.install_from_env(Hostile()) is False


def test_suffixes_from_env(ng):
    assert ng.install_from_env({"CRYPTOBOT_DOH": "1",
                                "CRYPTOBOT_DOH_SUFFIXES": " Example.TEST , .other.test"})
    assert ng.matches("api.example.test") and ng.matches("other.test")
    assert not ng.matches("fapi.binance.com")


def test_empty_suffix_variable_means_defaults(ng):
    assert ng.install_from_env({"CRYPTOBOT_DOH": "1", "CRYPTOBOT_DOH_SUFFIXES": " , "})
    assert ng.matches("fapi.binance.com") and ng.matches("www.okx.com")


# ------------------------------------------------------------------------ matching
@pytest.mark.parametrize("host", [
    "binance.com", "fapi.binance.com", "FSTREAM.Binance.COM", "demo-fapi.binance.com.",
    "api.binance.com", "www.okx.com", "okx.com", "a.b.c.binance.com"])
def test_matches_exchange_names(ng, host):
    assert ng.matches(host) is True


@pytest.mark.parametrize("host", [
    "example.com", "notbinance.com", "binance.com.evil.example", "binance.community",
    "data.binance.vision", "testnet.binancefuture.com", "api.bybit.com", "localhost", "",
    ".", "49.44.79.236", "13.224.10.1", "::1", "2405:200:1607:2820:41::36",
    b"fapi.binance.com", None, 443])
def test_does_not_match_others(ng, host):
    assert ng.matches(host) is False


# ----------------------------------------------------------- resolution behaviour
def test_exchange_host_gets_doh_addresses_not_the_sinkhole(rig, ng):
    rig.answer = ([REAL_A, REAL_B], 60)
    rig.install()
    got = rig.addresses(family=socket.AF_INET, type=socket.SOCK_STREAM)
    assert sorted(got) == [REAL_A, REAL_B]
    assert SINKHOLE_V4 not in got
    assert all(r[4][1] == 443 for r in socket.getaddrinfo("fapi.binance.com", 443))
    assert rig.lookup_calls == ["fapi.binance.com"]


def test_non_exchange_host_is_untouched(rig):
    rig.install()
    got = socket.getaddrinfo("example.com", 443, socket.AF_INET, socket.SOCK_STREAM)
    assert [r[4][0] for r in got] == [SINKHOLE_V4]  # whatever the system says, verbatim
    assert rig.lookup_calls == []
    assert rig.system_calls == [("example.com", 443, socket.AF_INET, socket.SOCK_STREAM, 0, 0)]


@pytest.mark.parametrize("host", ["127.0.0.1", "13.224.10.1", "1.1.1.1"])
def test_ip_literals_are_untouched(rig, host):
    rig.install()
    assert rig.addresses(host, 443, family=socket.AF_INET, type=socket.SOCK_STREAM) == [host]
    assert rig.lookup_calls == []


@pytest.mark.parametrize("host", [None, b"", 12, ""])
def test_odd_hosts_pass_through(rig, host):
    rig.install()
    with contextlib.suppress(Exception):  # the system resolver alone decides what is valid
        socket.getaddrinfo(host, 443)
    assert rig.lookup_calls == []
    assert rig.system_calls and rig.system_calls[0][0] == host


def test_bytes_host_is_resolved_like_str(rig):
    rig.install()
    assert rig.addresses(b"fapi.binance.com", 443, family=socket.AF_INET,
                         type=socket.SOCK_STREAM) == [REAL_A]


def test_trailing_dot_and_case_share_one_cache_entry(rig):
    rig.install()
    for host in ("fapi.binance.com", "FAPI.Binance.Com.", "fapi.binance.com"):
        assert rig.addresses(host, 443, family=socket.AF_INET, type=socket.SOCK_STREAM) == [REAL_A]
    assert rig.lookup_calls == ["fapi.binance.com"]


def test_port_forms(rig):
    rig.install()
    for port, number in ((443, 443), ("443", 443), (None, 0), ("https", 443)):
        got = socket.getaddrinfo("fapi.binance.com", port, socket.AF_INET, socket.SOCK_STREAM)
        assert got[0][4] == (REAL_A, number)


def test_family_type_and_proto_are_forwarded(rig):
    rig.install()
    rig.addresses(family=socket.AF_INET, type=socket.SOCK_DGRAM, proto=17)
    numeric_call = [c for c in rig.system_calls if c[0] == REAL_A][0]
    assert numeric_call[2:5] == (socket.AF_INET, socket.SOCK_DGRAM, 17)


def test_unspecified_family_returns_only_ipv4_real_addresses(rig):
    rig.install()
    got = socket.getaddrinfo("fapi.binance.com", 443)  # AF_UNSPEC: what create_connection uses
    assert {r[0] for r in got} == {socket.AF_INET}
    assert {r[4][0] for r in got} == {REAL_A}


def test_explicit_ipv6_defers_to_the_system_resolver(rig):
    rig.install()
    got = socket.getaddrinfo("fapi.binance.com", 443, socket.AF_INET6)
    assert got[0][0] == socket.AF_INET6 and got[0][4][0] == SINKHOLE_V6


def test_flags_are_kept_and_numerichost_added_for_the_literal_lookup(rig):
    rig.install()
    flags = socket.AI_ADDRCONFIG | socket.AI_PASSIVE
    rig.addresses(family=socket.AF_INET, type=socket.SOCK_STREAM, flags=flags)
    numeric_call = [c for c in rig.system_calls if c[0] == REAL_A][0]
    assert numeric_call[5] == flags | socket.AI_NUMERICHOST


def test_caller_numerichost_means_no_resolution(rig):
    rig.install()
    with pytest.raises(socket.gaierror):
        socket.getaddrinfo("fapi.binance.com", 443, flags=socket.AI_NUMERICHOST)
    assert rig.lookup_calls == []


def test_canonname_is_the_hostname_on_the_first_result_only(rig):
    rig.answer = ([REAL_A, REAL_B], 60)
    rig.install()
    got = socket.getaddrinfo("FAPI.binance.com", 443, socket.AF_INET, socket.SOCK_STREAM,
                             flags=socket.AI_CANONNAME)
    assert got[0][3] == "fapi.binance.com"
    assert all(r[3] == "" for r in got[1:])


def test_only_global_addresses_are_ever_returned_by_the_default_lookup_path(ng):
    # the guard is in parse_answer (below); here: an injected lookup is trusted as-is.
    rig = Rig(ng)
    rig.answer = (["127.0.0.1"], 60)
    rig.install()
    assert rig.addresses(family=socket.AF_INET, type=socket.SOCK_STREAM) == ["127.0.0.1"]


# ----------------------------------------------------------------- TTL and caching
def test_answer_is_cached_until_ttl_then_refreshed(rig):
    rig.install()
    rig.answer = ([REAL_A], 60)
    assert rig.addresses(family=socket.AF_INET, type=socket.SOCK_STREAM) == [REAL_A]
    rig.answer = ([REAL_B], 60)
    rig.clock.advance(59)
    assert rig.addresses(family=socket.AF_INET, type=socket.SOCK_STREAM) == [REAL_A]
    assert len(rig.lookup_calls) == 1
    rig.clock.advance(2)  # TTL expired
    assert rig.addresses(family=socket.AF_INET, type=socket.SOCK_STREAM) == [REAL_B]
    assert len(rig.lookup_calls) == 2


@pytest.mark.parametrize(("ttl", "effective"), [(1, 30), (0, 30), (45, 45), (86400, 300)])
def test_ttl_is_clamped(rig, ttl, effective):
    rig.answer = ([REAL_A], ttl)
    rig.install()
    rig.addresses()
    rig.clock.advance(effective - 1)
    rig.addresses()
    assert len(rig.lookup_calls) == 1
    rig.clock.advance(2)
    rig.addresses()
    assert len(rig.lookup_calls) == 2


def test_cache_is_bounded(rig, ng):
    rig.install()
    for i in range(ng.CACHE_MAX + 40):
        rig.addresses(f"h{i}.binance.com")
    assert len(ng._cache) <= ng.CACHE_MAX


# ------------------------------------------------------------ failure behaviour
def test_stale_answer_is_served_when_doh_fails(rig):
    rig.install()
    rig.answer = ([REAL_A], 60)
    assert rig.addresses(family=socket.AF_INET, type=socket.SOCK_STREAM) == [REAL_A]
    rig.clock.advance(120)  # expired
    rig.failure = OSError("doh down")
    assert rig.addresses(family=socket.AF_INET, type=socket.SOCK_STREAM) == [REAL_A]
    assert SINKHOLE_V4 not in rig.addresses()
    assert rig.lookup_calls.count("fapi.binance.com") >= 2  # it did try DoH again


def test_failure_backoff_then_recovery(rig):
    rig.install()
    rig.addresses()
    rig.clock.advance(120)
    rig.failure = OSError("doh down")
    rig.addresses()
    seen = len(rig.lookup_calls)
    rig.clock.advance(3)
    rig.addresses()
    assert len(rig.lookup_calls) == seen  # inside the backoff: no new DoH round trip
    rig.failure = None
    rig.answer = ([REAL_B], 60)
    rig.clock.advance(11)
    assert rig.addresses(family=socket.AF_INET, type=socket.SOCK_STREAM) == [REAL_B]


def test_backoff_counts_from_the_end_of_a_slow_failing_lookup(rig):
    """A 16 s dead-DoH round trip must not leave an already-expired 10 s backoff."""
    def slow_failure(name):
        rig.lookup_calls.append(name)
        rig.clock.advance(16)
        raise OSError("blocked")

    rig.lookup = slow_failure
    rig.install()
    for _ in range(3):
        assert rig.addresses(family=socket.AF_INET, type=socket.SOCK_STREAM) == [SINKHOLE_V4]
    assert rig.lookup_calls == ["fapi.binance.com"]


def test_concurrent_failures_do_not_queue_serially(rig):
    rig.delay = 0.3
    rig.failure = OSError("blocked")
    rig.install()
    barrier = threading.Barrier(6)

    def worker():
        barrier.wait(5)
        rig.addresses(family=socket.AF_INET, type=socket.SOCK_STREAM)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    t0 = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert time.monotonic() - t0 < 1.0
    assert len(rig.lookup_calls) == 1


def test_doh_lookup_has_an_overall_deadline(ng, monkeypatch):
    monkeypatch.setattr(ng, "DOH_DEADLINE_S", 0.5)
    calls: list = []

    def slow(url):
        calls.append(url)
        time.sleep(0.4)
        raise OSError("timeout")

    with pytest.raises(OSError, match="deadline"):
        ng.doh_lookup("fapi.binance.com", slow)
    assert len(calls) == 2  # not all four resolvers


def test_default_clock_is_wall_time_so_sleep_counts(ng):
    assert ng._clock is time.time


def test_reinstall_after_uninstall_with_a_foreign_wrapper_does_not_recurse(ng):
    base = socket.getaddrinfo
    ng.install(lookup=lambda n: (["127.0.0.1"], 60))
    ours = socket.getaddrinfo

    def outer(*args, **kwargs):
        return ours(*args, **kwargs)

    socket.getaddrinfo = outer
    try:
        ng.uninstall()
        # real resolver (not injected): the previous resolver is now the chained wrapper itself
        ng.install(lookup=lambda n: (["127.0.0.1"], 60))
        got = socket.getaddrinfo("localhost", 443, socket.AF_INET, socket.SOCK_STREAM)
        assert got  # a RecursionError here would escape: the shim is not allowed to loop
        got = socket.getaddrinfo("fapi.binance.com", 443, socket.AF_INET, socket.SOCK_STREAM)
        assert got[0][4][0] == "127.0.0.1"
    finally:
        ng.uninstall()
        socket.getaddrinfo = base


def test_lock_is_reentrant_for_signal_handlers(ng):
    with ng._lock, ng._lock:
        pass


def test_wrapper_advertises_its_matcher_and_real_resolver(rig, ng):
    rig.install()
    assert socket.getaddrinfo._cryptobot_matches("fapi.binance.com") is True
    assert socket.getaddrinfo._cryptobot_real == rig.system
    assert ng.system_getaddrinfo() == rig.system


def test_stale_answer_expires_after_a_day(rig, ng):
    rig.install()
    rig.addresses()
    rig.clock.advance(ng.STALE_MAX_S + 100)
    rig.failure = OSError("doh down")
    assert SINKHOLE_V4 in rig.addresses()  # too old to trust: system resolver answers


def test_total_doh_failure_without_cache_falls_back_to_system(rig):
    rig.failure = OSError("everything is down")
    rig.install()
    assert rig.addresses(family=socket.AF_INET, type=socket.SOCK_STREAM) == [SINKHOLE_V4]


@pytest.mark.parametrize("answer", [([], 60), (None, 60), ("x", "y"), 5, ([None], 60)])
def test_garbage_lookup_results_fall_back_without_raising(rig, answer):
    rig.answer = answer
    rig.install()
    assert rig.addresses(family=socket.AF_INET, type=socket.SOCK_STREAM) == [SINKHOLE_V4]


def test_system_resolver_errors_still_propagate_for_non_exchange_names(rig):
    rig.install()
    with pytest.raises(socket.gaierror):
        socket.getaddrinfo("example.com", 443, flags=socket.AI_NUMERICHOST)


def test_resolve_api_never_raises(rig, ng):
    rig.failure = KeyError("x")
    rig.install()
    assert ng.resolve("fapi.binance.com") is None
    assert ng.resolve(None) is None


def test_failed_names_do_not_poison_other_names(rig):
    rig.install()
    rig.failure = OSError("down")
    assert rig.addresses("fapi.binance.com", family=socket.AF_INET) == [SINKHOLE_V4]
    rig.failure = None
    assert rig.addresses("fstream.binance.com", family=socket.AF_INET,
                         type=socket.SOCK_STREAM) == [REAL_A]


# --------------------------------------------------------------- recursion / RNG
def test_lookup_that_resolves_an_exchange_name_does_not_recurse(rig):
    depth = []

    def reentrant(name):
        depth.append(name)
        assert len(depth) < 5, "unbounded recursion"
        socket.getaddrinfo("fapi.binance.com", 443)  # a lookup that dials the exchange itself
        return [REAL_A], 60

    rig.lookup = reentrant
    rig.install()
    got = rig.addresses(family=socket.AF_INET, type=socket.SOCK_STREAM)
    assert got == [REAL_A]
    assert depth == ["fapi.binance.com"]


def test_doh_endpoints_are_ip_literals(ng):
    import ipaddress
    import urllib.parse

    assert len(ng.RESOLVERS) >= 4
    for template in ng.RESOLVERS:
        ipaddress.ip_address(urllib.parse.urlsplit(template).hostname)
        assert urllib.parse.urlsplit(template).scheme == "https"


def test_global_random_state_is_not_disturbed(rig):
    rig.answer = ([REAL_A, REAL_B, REAL_C], 60)
    rig.install()
    random.seed(1234)
    expected = random.random()
    random.seed(1234)
    for _ in range(20):
        rig.clock.advance(1000)
        rig.addresses()
    assert random.random() == expected


def test_addresses_are_shuffled_across_calls(rig):
    rig.answer = ([REAL_A, REAL_B, REAL_C], 60)
    rig.install()
    firsts = {rig.addresses(family=socket.AF_INET, type=socket.SOCK_STREAM)[0]
              for _ in range(60)}
    assert len(firsts) > 1


# ----------------------------------------------------------------- concurrency
def test_concurrent_misses_make_one_doh_request(rig):
    rig.delay = 0.05
    rig.answer = ([REAL_A, REAL_B], 60)
    rig.install()
    results: list = []
    errors: list = []
    barrier = threading.Barrier(24)

    def worker():
        try:
            barrier.wait(5)
            results.append(sorted(set(rig.addresses(family=socket.AF_INET,
                                                    type=socket.SOCK_STREAM))))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(24)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert not errors
    assert results == [[REAL_A, REAL_B]] * 24
    assert rig.lookup_calls == ["fapi.binance.com"]


def test_concurrent_refresh_serves_stale_instead_of_blocking(rig):
    rig.install()
    rig.addresses()
    rig.clock.advance(120)
    rig.delay = 0.3
    rig.answer = ([REAL_B], 60)
    started = threading.Event()
    seen: list = []

    def refresher():
        started.set()
        seen.append(("refresh", rig.addresses(family=socket.AF_INET, type=socket.SOCK_STREAM)))

    thread = threading.Thread(target=refresher)
    thread.start()
    started.wait(2)
    time.sleep(0.05)
    t0 = time.monotonic()
    other = rig.addresses(family=socket.AF_INET, type=socket.SOCK_STREAM)
    elapsed = time.monotonic() - t0
    thread.join(5)
    assert other == [REAL_A] and elapsed < 0.25  # stale, immediately
    assert seen == [("refresh", [REAL_B])]
    assert len(rig.lookup_calls) == 2


def test_many_names_in_parallel(rig):
    rig.install()
    errors: list = []

    def worker(i):
        try:
            for _ in range(20):
                assert rig.addresses(f"n{i % 6}.binance.com", family=socket.AF_INET,
                                     type=socket.SOCK_STREAM) == [REAL_A]
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(18)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert not errors
    assert sorted(set(rig.lookup_calls)) == [f"n{i}.binance.com" for i in range(6)]
    assert len(rig.lookup_calls) == 6


# ------------------------------------------------------------- chaining/uninstall
def test_uninstall_with_a_wrapper_chained_on_top_passes_through(rig, ng):
    base = socket.getaddrinfo
    rig.install()
    ours = socket.getaddrinfo
    seen: list = []

    def outer(*args, **kwargs):
        seen.append(args[0])
        return ours(*args, **kwargs)

    socket.getaddrinfo = outer
    try:
        assert ng.uninstall() is True
        assert socket.getaddrinfo is outer  # cannot unwrap someone else's wrapper
        got = socket.getaddrinfo("fapi.binance.com", 443, socket.AF_INET, socket.SOCK_STREAM)
        assert got[0][4][0] == SINKHOLE_V4  # ...but it no longer re-resolves
    finally:
        socket.getaddrinfo = base


def test_reinstall_after_uninstall_starts_clean(rig, ng):
    rig.install()
    rig.addresses()
    ng.uninstall()
    rig.lookup_calls.clear()
    rig.install()
    rig.addresses()
    assert rig.lookup_calls == ["fapi.binance.com"]  # cache was dropped


# ------------------------------------------------------------ DoH parsing / transport
def _answer(*records, status=0):
    return {"Status": status, "Answer": list(records)}


def _a(ip, ttl=60):
    return {"name": "x.", "type": 1, "TTL": ttl, "data": ip}


def test_parse_answer_basic_and_ttl_min(ng):
    assert ng.parse_answer(_answer(_a(REAL_A, 120), _a(REAL_B, 45))) == ([REAL_A, REAL_B], 45)
    assert ng.parse_answer(_answer(_a(REAL_A, 1)))[1] == 30
    assert ng.parse_answer(_answer(_a(REAL_A, 99999)))[1] == 300


@pytest.mark.parametrize("bad", [
    "127.0.0.1", "127.8.8.8", "10.0.0.5", "192.168.1.1", "172.16.0.9", "169.254.169.254",
    "0.0.0.0", "224.0.0.1", "255.255.255.255", "100.64.0.1", "198.18.0.1"])
def test_parse_answer_discards_non_global_addresses(ng, bad):
    with pytest.raises(ValueError, match="usable"):
        ng.parse_answer(_answer(_a(bad)))
    assert ng.parse_answer(_answer(_a(bad), _a(REAL_A)))[0] == [REAL_A]


def test_parse_answer_ignores_cname_aaaa_and_junk(ng):
    payload = _answer({"type": 5, "data": "x.cloudfront.net."},
                      {"type": 28, "data": SINKHOLE_V6}, {"type": 1, "data": "not-an-ip"},
                      {"type": 1}, "junk", _a(REAL_A))
    assert ng.parse_answer(payload) == ([REAL_A], 60)


@pytest.mark.parametrize("payload", [None, [], "x", {"Status": 3}, {"Status": 0},
                                     {"Status": 0, "Answer": []}, {"Status": 0, "Answer": None}])
def test_parse_answer_rejects_unusable(ng, payload):
    with pytest.raises(ValueError):  # noqa: PT011
        ng.parse_answer(payload)


def test_doh_lookup_walks_resolvers_until_one_answers(ng):
    urls: list = []

    def fetch(url):
        urls.append(url)
        if len(urls) < 3:
            raise OSError("timeout")
        return _answer(_a(REAL_A))

    assert ng.doh_lookup("fapi.binance.com", fetch) == ([REAL_A], 60)
    assert len(urls) == 3
    assert all("name=fapi.binance.com" in u for u in urls)
    assert urls[0].startswith("https://1.1.1.1/") and urls[1].startswith("https://8.8.8.8/")


def test_doh_lookup_quotes_the_name(ng):
    urls: list = []
    ng.doh_lookup("a&b=c.binance.com", lambda u: urls.append(u) or _answer(_a(REAL_A)))
    assert "&b=c" not in urls[0] and "a%26b%3Dc.binance.com" in urls[0]


def test_doh_lookup_raises_oserror_when_all_fail(ng):
    def fetch(_url):
        raise ValueError("bad json")

    with pytest.raises(OSError, match="all DoH resolvers failed"):
        ng.doh_lookup("fapi.binance.com", fetch)


def test_default_doh_path_ignores_private_answers_end_to_end(rig, ng, monkeypatch):
    """A poisoned DoH answer (loopback/private) is dropped, so the system resolver decides."""
    monkeypatch.setattr(ng, "_http_get_json", lambda url: _answer(_a("127.0.0.1"), _a("10.1.1.1")))
    ng.install(real_getaddrinfo=rig.system, clock=rig.clock)
    assert rig.addresses(family=socket.AF_INET, type=socket.SOCK_STREAM) == [SINKHOLE_V4]


# ------------------------------------------------- import-time behaviour (no network)
def test_importing_does_not_touch_the_network_or_patch_the_resolver(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("network used at import time")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.delenv("CRYPTOBOT_DOH", raising=False)
    before = socket.getaddrinfo
    for impl in IMPLS:
        module = load_fresh(impl)
        assert module.is_installed() is False
        assert socket.getaddrinfo is before


def test_library_import_never_installs_even_with_the_flag(monkeypatch):
    monkeypatch.setenv("CRYPTOBOT_DOH", "1")
    before = socket.getaddrinfo
    module = load_fresh("library")
    assert module.is_installed() is False and socket.getaddrinfo is before


def test_standalone_installs_at_import_only_when_the_flag_is_set(monkeypatch):
    before = socket.getaddrinfo
    monkeypatch.setenv("CRYPTOBOT_DOH", "1")
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("network at import"))
    module = load_fresh("standalone")
    try:
        assert module.is_installed() is True and socket.getaddrinfo is not before
        assert module.matches("fapi.binance.com")
    finally:
        module.uninstall()
    assert socket.getaddrinfo is before


# ------------------------------------------------ cross-copy and drift protection
def test_second_copy_does_not_double_wrap(monkeypatch):
    first = load_fresh("standalone")
    second = load_fresh("library")
    try:
        assert first.install() is True
        wrapper = socket.getaddrinfo
        assert second.install() is False
        assert socket.getaddrinfo is wrapper
    finally:
        first.uninstall()


def test_standalone_core_is_byte_identical_to_the_library():
    sys.path.insert(0, str(ROOT / "tools" / "netshim"))
    try:
        import sync_core
    finally:
        sys.path.pop(0)
    assert sync_core.core_of(LIBRARY.read_text()) == sync_core.core_of(STANDALONE.read_text())


def test_standalone_does_not_import_cryptobot():
    tree = ast.parse(STANDALONE.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "cryptobot" not in imported and "tools" not in imported
    assert imported <= set(sys.stdlib_module_names)


# ----------------------------------------------- the real thing, in a fresh interpreter
def _run(code: str, *, pythonpath: str, env_extra: dict | None = None) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CRYPTOBOT_")}
    env["PYTHONPATH"] = pythonpath
    env.update(env_extra or {})
    done = subprocess.run([sys.executable, "-c", textwrap.dedent(code)], env=env, cwd="/",
                          capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


PROBE = """
import socket, sys
print(getattr(socket.getaddrinfo, "_cryptobot_netguard", False), "cryptobot" in sys.modules)
"""


def test_standalone_file_alone_on_pythonpath_activates_with_the_flag(tmp_path):
    shim_dir = str(STANDALONE.parent)
    assert _run(PROBE, pythonpath=shim_dir, env_extra={"CRYPTOBOT_DOH": "1"}) == "True False"


def test_standalone_file_alone_on_pythonpath_is_inert_without_the_flag():
    assert _run(PROBE, pythonpath=str(STANDALONE.parent)) == "False False"


def test_standalone_chains_to_the_interpreters_own_sitecustomize(tmp_path):
    other = tmp_path / "interp"
    other.mkdir()
    (other / "sitecustomize.py").write_text("import builtins; builtins.CHAINED_MARK = 'yes'\n")
    shim_dir = str(STANDALONE.parent)
    out = _run("import builtins, socket; print(getattr(builtins, 'CHAINED_MARK', 'no'), "
               "getattr(socket.getaddrinfo, '_cryptobot_netguard', False))",
               pythonpath=os.pathsep.join([shim_dir, str(other)]),
               env_extra={"CRYPTOBOT_DOH": "1"})
    assert out == "yes True"


def test_standalone_survives_a_broken_interpreter_sitecustomize(tmp_path):
    other = tmp_path / "interp"
    other.mkdir()
    (other / "sitecustomize.py").write_text("raise RuntimeError('broken')\n")
    out = _run(PROBE, pythonpath=os.pathsep.join([str(STANDALONE.parent), str(other)]),
               env_extra={"CRYPTOBOT_DOH": "1"})
    assert out == "True False"
