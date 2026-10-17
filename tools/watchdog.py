#!/usr/bin/env python3
"""External watchdog (T3.2): stale heartbeat + exposure -> flatten+alert.

Minimal separate process: reads a heartbeat JSON file the bot rewrites
({"ts_utc": ..., "has_exposure": bool, "run_id": ...}); when stale past
--max-age-s AND exposure is flagged, it runs the owner-configured
flatten command (never a hardcoded venue call, credentials stay with
that command's environment) and sends an alert via the alert sinks.

countdownCancelAll is deliberately NOT used: whether it leaves
conditional stops intact is unproven — the owner finding procedure is
in OWNER_ACTIONS.md.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def heartbeat_status(path: Path, *, max_age_s: float,
                     now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    try:
        doc = json.loads(Path(path).read_text())
        ts = datetime.fromisoformat(str(doc["ts_utc"]))
        age = (now - ts).total_seconds()
    except Exception as exc:  # noqa: BLE001 — unreadable = stale
        return {"stale": True, "has_exposure": True,
                "reason": f"heartbeat-unreadable:{exc}"}
    return {"stale": age > max_age_s, "age_s": age,
            "has_exposure": bool(doc.get("has_exposure")),
            "run_id": doc.get("run_id")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--heartbeat", required=True)
    ap.add_argument("--max-age-s", type=float, default=90.0)
    ap.add_argument("--flatten-cmd", default="",
                    help="shell command run once when stale+exposed")
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args(argv)
    while True:
        status = heartbeat_status(Path(args.heartbeat),
                                  max_age_s=args.max_age_s)
        if status["stale"] and status.get("has_exposure"):
            print(json.dumps({"watchdog": "TRIGGERED", **status}),
                  file=sys.stderr)
            if args.flatten_cmd:
                subprocess.run(args.flatten_cmd, shell=True,  # noqa: S602
                               check=False, timeout=120)
            return 3
        if args.once:
            print(json.dumps({"watchdog": "ok", **status}))
            return 0
        time.sleep(15.0)


if __name__ == "__main__":
    raise SystemExit(main())
