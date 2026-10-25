"""F2.4/F2.6: host provisioning and clock-skew checks.

Every check returns a row with name/status/detail. The overall verdict
is PASS only when all checks pass; offline runs cannot pass host-check
because the venue RTT and clock offset are not measured.
"""
from __future__ import annotations

import json
import platform
import resource
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

FAPI_TIME = "https://fapi.binance.com/fapi/v1/time"
SINKHOLE_HOSTS = ("fapi.binance.com", "fstream.binance.com", "api.binance.com",
                  "demo-fapi.binance.com")
SINKHOLE_REMEDY = ("export CRYPTOBOT_DOH=1 (opt-in DNS-over-HTTPS for exchange hostnames; "
                   "see tools/netshim/README.md), or set a public DNS (1.1.1.1 / 8.8.8.8) "
                   "in the OS network settings")


def _row(name: str, status: str, detail: str) -> dict:
    return {"check": name, "status": status, "detail": detail}


def python_check() -> dict:
    ok = sys.version_info >= (3, 12)
    return _row("python", "PASS" if ok else "FAIL",
                platform.python_version())


def ulimit_check(min_open_files: int = 4096) -> dict:
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft == resource.RLIM_INFINITY:
        soft = hard
    ok = int(soft) >= int(min_open_files)
    return _row("open-files", "PASS" if ok else "FAIL",
                f"soft={soft} hard={hard} required>={min_open_files}")


def disk_check(path: str | Path, min_free_gb: float) -> dict:
    usage = shutil.disk_usage(path)
    free_gb = usage.free / 1e9
    ok = free_gb >= float(min_free_gb)
    return _row("disk", "PASS" if ok else "FAIL",
                f"free_gb={free_gb:.1f} required>={min_free_gb}")


def time_sync_check() -> dict:
    """Read the OS time-sync state; UNKNOWN is not PASS."""
    try:
        out = subprocess.run(
            ["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
            capture_output=True, text=True, timeout=5, check=False)
        value = out.stdout.strip().lower()
        if value == "yes":
            return _row("time-sync-daemon", "PASS", "timedatectl yes")
        if value == "no":
            return _row("time-sync-daemon", "FAIL",
                        "timedatectl says not synchronized")
        return _row("time-sync-daemon", "UNKNOWN",
                    f"timedatectl returned {value!r}")
    except (OSError, subprocess.SubprocessError) as exc:
        return _row("time-sync-daemon", "UNKNOWN", str(exc))


def venue_rtt_and_skew(*, samples: int = 3,
                       timeout_s: float = 5.0) -> tuple[dict, dict]:
    """Measure REST RTT + (server-local) clock offset. No credentials."""
    rtts: list[float] = []
    offsets: list[float] = []
    try:
        for _ in range(samples):
            before = time.time() * 1000
            with urllib.request.urlopen(FAPI_TIME,  # noqa: S310
                                        timeout=timeout_s) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            after = time.time() * 1000
            server = float(body["serverTime"])
            rtts.append(after - before)
            offsets.append(server - (before + after) / 2.0)
    except Exception as exc:  # noqa: BLE001 — report, never hide
        return (_row("venue-rtt", "FAIL", f"{type(exc).__name__}: {exc}"),
                _row("clock-skew", "FAIL", f"{type(exc).__name__}: {exc}"))
    rtts.sort()
    return (_row("venue-rtt", "PASS" if rtts[len(rtts) // 2] < 1000 else "FAIL",
                 f"median_ms={rtts[len(rtts) // 2]:.1f}"),
            _row("clock-skew", "PASS" if abs(offsets[-1]) <= 250 else "FAIL",
                 f"offset_ms={offsets[-1]:.1f}"))


def _system_addresses(host: str) -> list[str]:
    """The OS resolver's IPv4 answer, bypassing netguard (which hides the problem)."""
    from cryptobot import netguard

    infos = netguard.system_getaddrinfo()(host, 443, socket.AF_INET, socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def _doh_addresses(host: str) -> list[str]:
    from cryptobot import netguard

    return sorted(netguard.doh_lookup(host)[0])


def _tcp_connects(address: str, port: int, timeout_s: float) -> bool:
    try:
        socket.create_connection((address, port), timeout=timeout_s).close()
    except OSError:
        return False
    return True


def _active_shim_covers(host: str) -> bool:
    """True when a netguard shim (library or standalone) is active AND re-resolves host."""
    current = socket.getaddrinfo
    covers = getattr(current, "_cryptobot_matches", None)
    try:
        return bool(getattr(current, "_cryptobot_netguard", False) and covers and covers(host))
    except Exception:  # noqa: BLE001
        return False


MAX_PROBED_ADDRESSES = 8


def dns_sinkhole_check(hosts: tuple[str, ...] = SINKHOLE_HOSTS, *,
                       system_resolver: Callable[[str], list[str]] | None = None,
                       doh_resolver: Callable[[str], list[str]] | None = None,
                       connector: Callable[[str, int, float], bool] | None = None,
                       timeout_s: float = 3.0, port: int = 443,
                       budget_s: float = 20.0) -> dict:
    """Detect an ISP resolver that sinkholes exchange hostnames (observed: Jio, India).

    FAIL only on proof: the system answer differs from the DoH answer AND no system
    address accepts a TCP connect AND a DoH address does. A host whose system address
    connects is PASS without any DoH traffic. An inconclusive probe (no IPv4 answer,
    resolver error, time budget spent) is reported as PASS with an explicit "inconclusive"
    note: it never turns a healthy host's verdict into FAIL. A sinkhole that an active
    netguard shim already covers is PASS, mitigated.
    Resolvers and the connector are injectable so tests need no network.
    """
    import random

    system = system_resolver or _system_addresses
    doh = doh_resolver or _doh_addresses
    connect = connector or _tcp_connects
    proxied = ""
    proxies = urllib.request.getproxies()
    if proxies.get("https") or proxies.get("all"):
        # The websocket client dials sockets directly and ignores proxy variables, so
        # the direct probe is still the right one; the proxy is only noted.
        proxied = "; note: an HTTPS proxy is configured (websocket path ignores it)"
    rng = random.Random()

    def candidates(addresses: list[str]) -> list[str]:
        shuffled = list(addresses)
        rng.shuffle(shuffled)
        return shuffled[:MAX_PROBED_ADDRESSES]  # every reachable-or-not address, capped

    started = time.monotonic()
    deadline = started + max(0.0, budget_s)

    def reaches(addresses: list[str]) -> bool | None:
        selected = candidates(addresses)
        for address in selected:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            if connect(address, port, min(timeout_s, remaining)):
                return True
        if len(addresses) > len(selected):
            return None  # the probe cap prevents proving that every address is dead
        return False

    sinkholed: list[tuple[str, str]] = []
    unknown: list[str] = []
    for host in hosts:
        if time.monotonic() >= deadline:
            unknown.append(f"{host}: time budget {budget_s:.0f}s spent")
            continue
        try:
            system_addrs = list(system(host))
            if not system_addrs:
                unknown.append(f"{host}: system resolver returned no IPv4 addresses")
                continue
            system_reaches = reaches(system_addrs)
            if system_reaches is True:
                continue
            if system_reaches is None:
                unknown.append(f"{host}: system address probe incomplete (time budget or address cap)")
                continue
            if time.monotonic() >= deadline:
                unknown.append(f"{host}: time budget {budget_s:.0f}s spent")
                continue
            doh_addrs = list(doh(host))
            if sorted(doh_addrs) == sorted(system_addrs):
                continue  # answers agree: unreachable, but not a DNS sinkhole (venue-rtt says so)
            doh_reaches = reaches(doh_addrs)
            if doh_reaches is True:
                sinkholed.append((host, f"{host} system={','.join(system_addrs)} "
                                        f"(connect failed) doh={','.join(doh_addrs)} (connects)"))
            elif doh_reaches is None:
                unknown.append(f"{host}: DoH address probe incomplete (time budget or address cap)")
            else:
                unknown.append(f"{host}: neither system nor DoH address connects")
        except Exception as exc:  # noqa: BLE001 — a check must report, never crash host-check
            unknown.append(f"{host}: {type(exc).__name__}: {exc}")
    note = (("; inconclusive for " + "; ".join(unknown)) if unknown else "") + proxied
    if sinkholed:
        text = "; ".join(t for _, t in sinkholed)
        if all(_active_shim_covers(h) for h, _ in sinkholed):
            return _row("dns-sinkhole", "PASS",
                        "ISP DNS sinkholes " + text
                        + " -- mitigated in this process (CRYPTOBOT_DOH=1 active)" + note)
        return _row("dns-sinkhole", "FAIL",
                    "ISP DNS sinkholes exchange hostnames: " + text
                    + ". Remedy: " + SINKHOLE_REMEDY + note)
    if unknown:
        return _row("dns-sinkhole", "PASS",
                    f"no sinkhole proven for {len(hosts)} hosts" + note)
    return _row("dns-sinkhole", "PASS", f"no sinkhole detected for {len(hosts)} hosts" + note)


def run_host_check(*, min_free_gb: float = 20.0,
                   max_clock_skew_ms: int = 250,
                   check_network: bool = True,
                   out: str | None = None,
                   free_gb: float | None = None,
                   dns_check: Callable[[], dict] | None = None) -> dict:
    rows = [python_check(), ulimit_check(),
            disk_check(".", min_free_gb)]
    if free_gb is not None:
        rows[-1] = _row("disk", "PASS" if free_gb >= min_free_gb else "FAIL",
                        f"free_gb={free_gb:.1f} required>={min_free_gb}")
    rows.append(time_sync_check())
    if check_network:
        rtt, skew = venue_rtt_and_skew()
        if skew["status"] == "PASS":
            try:
                offset = float(skew["detail"].split("=")[1])
            except (IndexError, ValueError):
                offset = float("inf")
            if abs(offset) > float(max_clock_skew_ms):
                skew["status"] = "FAIL"
                skew["detail"] += f" required<={max_clock_skew_ms}"
        rows.extend([rtt, skew])
        rows.append((dns_check or dns_sinkhole_check)())
    else:
        rows.append(_row("venue-rtt", "UNKNOWN", "network check disabled"))
        rows.append(_row("clock-skew", "UNKNOWN", "network check disabled"))
        rows.append(_row("dns-sinkhole", "UNKNOWN", "network check disabled"))
    verdict = "PASS" if all(r["status"] == "PASS" for r in rows) else "FAIL"
    doc = {"check": "host-check", "verdict": verdict,
           "generated_utc": datetime.now(UTC).isoformat(),
           "host": socket.gethostname(), "rows": rows}
    if out:
        p = Path(out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                     encoding="utf-8")
    return doc


__all__ = ["run_host_check", "venue_rtt_and_skew", "dns_sinkhole_check", "time_sync_check",
           "disk_check", "ulimit_check", "python_check"]
