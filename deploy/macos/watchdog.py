"""Stall detector and disk guard for the public-data recorder.

Reads heartbeat.json and chunk sizes. Does not read event payloads.
Below the free-space threshold it notifies and stops the recorder.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(os.environ.get(
    "CRYPTOBOT_ROOT", "/Users/sahajpatel/Code/cryto-bot-edge"))
RECORDER = Path(os.environ.get(
    "CRYPTOBOT_RECORDER", str(ROOT / "data" / "recorder")))
LOG = Path.home() / "Library" / "Logs" / "cryptobot" / "watchdog.log"
STATE = Path.home() / "Library" / "Logs" / "cryptobot" / "watchdog-state.json"
FREE_FLOOR_MB = int(os.environ.get("CRYPTOBOT_FREE_FLOOR_MB", "8192"))
STALL_S = int(os.environ.get("CRYPTOBOT_STALL_S", "600"))
LABEL = "com.cryptobot.recorder"


def _log(line: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _notify(message: str) -> None:
    subprocess.run(
        ["osascript", "-e",
         f'display notification "{message}" with title "cryptobot"'],
        check=False)


def _free_mb() -> float:
    usage = shutil.disk_usage(RECORDER if RECORDER.exists() else ROOT)
    return usage.free / (1024 * 1024)


def _chunk_bytes() -> int:
    chunks = RECORDER / "chunks"
    if not chunks.is_dir():
        return 0
    return sum(p.stat().st_size for p in chunks.glob("rec-*.jsonl.gz"))


def _heartbeat_age() -> float | None:
    path = RECORDER / "heartbeat.json"
    if not path.exists():
        return None
    try:
        stamp = json.loads(path.read_text()).get("ts_utc")
        from datetime import UTC, datetime
        when = datetime.fromisoformat(stamp)
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return time.time() - when.timestamp()
    except (ValueError, TypeError):
        return None


def main() -> int:
    free = _free_mb()
    nbytes = _chunk_bytes()
    age = _heartbeat_age()
    prev = {}
    if STATE.exists():
        try:
            prev = json.loads(STATE.read_text())
        except ValueError:
            prev = {}
    _log(f"free_mb={free:.0f} chunk_bytes={nbytes} heartbeat_age_s={age}")
    if free < FREE_FLOOR_MB:
        _notify(f"Disk free {free:.0f} MB is under {FREE_FLOOR_MB} MB. "
                "Stopping the recorder.")
        uid = os.getuid()
        plist = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(plist)],
                       check=False)
        _log("disk-guard stopped recorder")
        return 2
    stalled = False
    if prev.get("chunk_bytes") == nbytes and age is not None and age > STALL_S:
        stalled = True
    if age is not None and age > STALL_S and nbytes == prev.get("chunk_bytes"):
        stalled = True
    if stalled:
        uid = os.getuid()
        _log("stall: restarting recorder")
        subprocess.run(
            ["launchctl", "kickstart", "-k", f"gui/{uid}/{LABEL}"],
            check=False)
    STATE.write_text(json.dumps({
        "chunk_bytes": nbytes, "free_mb": free, "ts": time.time()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
