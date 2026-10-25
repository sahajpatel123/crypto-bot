"""host-check dns-sinkhole row: injected resolvers and connector, no network."""
from __future__ import annotations

import socket
from types import SimpleNamespace

import pytest

from cryptobot import netguard
from cryptobot.ops import host_check
from cryptobot.ops.host_check import SINKHOLE_HOSTS, dns_sinkhole_check, run_host_check

SINK = "49.44.79.236"
REAL = "13.224.10.1"


def _check(system, doh, connects, **kw):
    calls: list = []

    def connector(address, port, timeout):
        calls.append((address, port))
        return address in connects

    row = dns_sinkhole_check(system_resolver=lambda h: system(h) if callable(system) else system,
                             doh_resolver=lambda h: doh(h) if callable(doh) else doh,
                             connector=connector, **kw)
    return row, calls


def test_healthy_host_passes_without_asking_doh():
    def doh(_host):
        raise AssertionError("DoH must not be consulted when the system address connects")

    row, _ = _check([REAL], doh, {REAL})
    assert row["check"] == "dns-sinkhole" and row["status"] == "PASS"


def test_sinkhole_is_a_fail_with_the_plain_remedy():
    row, calls = _check([SINK], [REAL], {REAL})
    assert row["status"] == "FAIL"
    assert "export CRYPTOBOT_DOH=1" in row["detail"] and "public DNS" in row["detail"]
    assert SINK in row["detail"] and REAL in row["detail"]
    assert (SINK, 443) in calls and (REAL, 443) in calls


def test_every_exchange_host_is_checked():
    seen: list = []
    dns_sinkhole_check(system_resolver=lambda h: seen.append(h) or [REAL],
                       doh_resolver=lambda h: [REAL], connector=lambda *a: True)
    assert seen == list(SINKHOLE_HOSTS)
    assert {"fapi.binance.com", "fstream.binance.com", "api.binance.com",
            "demo-fapi.binance.com"} == set(SINKHOLE_HOSTS)


def test_one_sinkholed_host_among_healthy_ones_fails():
    row, _ = _check(lambda h: [SINK] if h == "fstream.binance.com" else [REAL], [REAL],
                    {REAL})
    assert row["status"] == "FAIL" and "fstream.binance.com" in row["detail"]
    assert "fapi.binance.com system" not in row["detail"]


def test_same_answer_but_unreachable_is_not_called_a_sinkhole():
    row, _ = _check([REAL], [REAL], set())
    assert row["status"] == "PASS"  # venue-rtt owns plain unreachability


def test_both_unreachable_is_inconclusive_but_never_fatal():
    row, _ = _check([SINK], [REAL], set())
    assert row["status"] == "PASS" and "inconclusive" in row["detail"]


def test_doh_failure_is_inconclusive_and_never_raises():
    def doh(_h):
        raise OSError("no route")

    row, _ = _check([SINK], doh, set())
    assert row["status"] == "PASS" and "inconclusive" in row["detail"] and "OSError" in row["detail"]


def test_ipv6_only_host_with_no_ipv4_answer_is_not_a_regression():
    def system(_h):
        raise socket.gaierror(socket.EAI_NONAME, "no A record")

    row, _ = _check(system, [REAL], {REAL})
    assert row["status"] == "PASS" and "inconclusive" in row["detail"]


def test_one_unresolvable_host_does_not_hide_a_proven_sinkhole():
    def system(h):
        if h == "demo-fapi.binance.com":
            raise socket.gaierror("nope")
        return [SINK] if h == "fapi.binance.com" else [REAL]

    row, _ = _check(system, [REAL], {REAL})
    assert row["status"] == "FAIL" and "inconclusive for demo-fapi" in row["detail"]


def test_time_budget_is_inconclusive():
    row = dns_sinkhole_check(system_resolver=lambda h: [SINK], doh_resolver=lambda h: [REAL],
                             connector=lambda *a: False, budget_s=-1.0)
    assert row["status"] == "PASS" and "time budget" in row["detail"]


def test_budget_expiring_before_all_system_addresses_is_inconclusive(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(host_check, "time", SimpleNamespace(monotonic=lambda: now[0]))
    system_addresses = [SINK, "49.44.79.237", "49.44.79.238"]
    doh_calls: list[str] = []
    connect_calls: list[str] = []

    def connector(address, _port, _timeout):
        connect_calls.append(address)
        if address != REAL:
            now[0] += 2.0  # the first failed system probe consumes the entire budget
        return address == REAL

    row = dns_sinkhole_check(
        hosts=("fapi.binance.com",), system_resolver=lambda _h: system_addresses,
        doh_resolver=lambda h: doh_calls.append(h) or [REAL], connector=connector, budget_s=1.0)
    assert row["status"] == "PASS" and "inconclusive" in row["detail"]
    assert "time budget" in row["detail"]
    assert len(connect_calls) == 1 and doh_calls == []


def test_https_proxy_does_not_skip_the_direct_probe(monkeypatch):
    # the websocket client ignores proxy variables, so the direct probe still runs
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    row = dns_sinkhole_check(hosts=("fapi.binance.com",),
                             system_resolver=lambda h: [SINK], doh_resolver=lambda h: [REAL],
                             connector=lambda a, *_: a == REAL)
    assert row["status"] == "FAIL" and "proxy" in row["detail"]


def test_healthy_host_is_never_a_flaky_fail_when_one_of_many_addresses_connects():
    addrs = [f"13.224.10.{i}" for i in range(1, 6)]
    for _ in range(200):
        row = dns_sinkhole_check(hosts=("fapi.binance.com",),
                                 system_resolver=lambda h: addrs, doh_resolver=lambda h: [REAL],
                                 connector=lambda a, *_: a == addrs[3])
        assert row["status"] == "PASS" and "sinkhole detected" in row["detail"]


def test_later_addresses_are_tried_not_just_a_sorted_prefix():
    addrs = [f"13.224.10.{i}" for i in range(1, 9)]
    row = dns_sinkhole_check(("fapi.binance.com",), system_resolver=lambda h: addrs,
                             doh_resolver=lambda h: addrs, connector=lambda a, p, t: a == addrs[-1])
    assert row["status"] == "PASS"  # never FAIL: answers agree


def _shim(module_matches=lambda h: True, *, installed=True):
    def fake(*_a, **_k):
        raise AssertionError("never called")

    fake._cryptobot_netguard = installed
    fake._cryptobot_matches = module_matches
    return fake


def test_mitigated_only_when_an_active_shim_covers_the_host(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _shim())
    row, _ = _check([SINK], [REAL], {REAL})
    assert row["status"] == "PASS" and "mitigated" in row["detail"]


def test_not_mitigated_when_the_suffix_list_excludes_the_host(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _shim(lambda h: h.endswith("okx.com")))
    row, _ = _check([SINK], [REAL], {REAL})
    assert row["status"] == "FAIL"


def test_no_shim_means_no_mitigation(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [])
    row, _ = _check([SINK], [REAL], {REAL})
    assert row["status"] == "FAIL"


def test_run_host_check_adds_the_row_and_keeps_existing_names(monkeypatch):
    monkeypatch.setattr(host_check, "venue_rtt_and_skew", lambda: (
        host_check._row("venue-rtt", "PASS", "median_ms=1.0"),
        host_check._row("clock-skew", "PASS", "offset_ms=1.0")))
    monkeypatch.setattr(host_check, "time_sync_check",
                        lambda: host_check._row("time-sync-daemon", "PASS", "x"))
    ok = host_check._row("dns-sinkhole", "PASS", "none")
    report = run_host_check(min_free_gb=0.0, free_gb=100.0, dns_check=lambda: ok)
    names = [r["check"] for r in report["rows"]]
    assert names == ["python", "open-files", "disk", "time-sync-daemon", "venue-rtt",
                     "clock-skew", "dns-sinkhole"]
    assert report["verdict"] == "PASS"  # PASS contract unchanged for a healthy host


def test_run_host_check_fails_on_a_sinkhole(monkeypatch):
    monkeypatch.setattr(host_check, "venue_rtt_and_skew", lambda: (
        host_check._row("venue-rtt", "PASS", "median_ms=1.0"),
        host_check._row("clock-skew", "PASS", "offset_ms=1.0")))
    monkeypatch.setattr(host_check, "time_sync_check",
                        lambda: host_check._row("time-sync-daemon", "PASS", "x"))
    bad = host_check._row("dns-sinkhole", "FAIL", "sinkholed")
    assert run_host_check(min_free_gb=0.0, free_gb=100.0, dns_check=lambda: bad)["verdict"] == "FAIL"


def test_offline_mode_marks_dns_unknown_without_touching_the_network():
    report = run_host_check(min_free_gb=0.0, check_network=False)
    rows = {r["check"]: r["status"] for r in report["rows"]}
    assert rows["dns-sinkhole"] == "UNKNOWN" and report["verdict"] == "FAIL"


def test_default_resolvers_bypass_the_standalone_shim_too(monkeypatch):
    sys_calls: list = []

    def real(host, port, *a, **k):
        sys_calls.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (SINK, port))]

    def wrapper(*a, **k):
        raise AssertionError("the shim itself must not be used")

    wrapper._cryptobot_real = real
    monkeypatch.setattr(socket, "getaddrinfo", wrapper)
    assert host_check._system_addresses("fapi.binance.com") == [SINK]
    assert sys_calls == ["fapi.binance.com"]


def test_default_resolvers_bypass_an_installed_netguard(monkeypatch):
    """The check must see the ISP's answer, not netguard's rewritten one."""
    seen: list = []

    def system(host, port, family=0, type=0, proto=0, flags=0):
        seen.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (SINK, port))]

    assert netguard.install(real_getaddrinfo=system, lookup=lambda n: ([REAL], 60))
    try:
        assert host_check._system_addresses("fapi.binance.com") == [SINK]
    finally:
        netguard.uninstall()
    assert seen == ["fapi.binance.com"]


@pytest.mark.parametrize("hosts", [(), ("fapi.binance.com",)])
def test_custom_host_lists(hosts):
    row = dns_sinkhole_check(hosts, system_resolver=lambda h: [REAL],
                             doh_resolver=lambda h: [REAL], connector=lambda *a: True)
    assert row["status"] == "PASS"
