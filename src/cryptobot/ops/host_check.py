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
from datetime import UTC, datetime
from pathlib import Path

FAPI_TIME = "https://fapi.binance.com/fapi/v1/time"


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


def run_host_check(*, min_free_gb: float = 20.0,
                   max_clock_skew_ms: int = 250,
                   check_network: bool = True,
                   out: str | None = None,
                   free_gb: float | None = None) -> dict:
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
    else:
        rows.append(_row("venue-rtt", "UNKNOWN", "network check disabled"))
        rows.append(_row("clock-skew", "UNKNOWN", "network check disabled"))
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


__all__ = ["run_host_check", "venue_rtt_and_skew", "time_sync_check",
           "disk_check", "ulimit_check", "python_check"]
