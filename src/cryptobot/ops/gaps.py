"""Recorder coverage gaps for the daily autopilot report (D4).

Reads only the sealed manifest (metadata). A gap percentage is the
fraction of wall-clock time inside the observed span with no sealed
chunk covering it — sleep, crash and restart holes show up here even
when every individual chunk is intact.
"""
from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ALERT_PCT = 5.0


def _notify(message: str) -> None:
    subprocess.run(
        ["osascript", "-e",
         f'display notification "{message}" with title "cryptobot"'],
        check=False)


def recorder_gap_report(recorder_root: str | Path,
                        *, day: datetime | None = None,
                        notify: bool = False) -> dict:
    root = Path(recorder_root)
    manifest = root / "manifest.json"
    if not manifest.exists():
        return {"status": "NO_MANIFEST", "recorder": str(root),
                "gap_pct": None, "alert": False}
    try:
        doc = json.loads(manifest.read_text(encoding="utf-8"))
    except ValueError:
        return {"status": "BAD_MANIFEST", "recorder": str(root),
                "gap_pct": None, "alert": False}
    entries = [e for e in doc.get("entries", [])
               if isinstance(e.get("first_ms"), int)
               and isinstance(e.get("last_ms"), int)]
    now = day or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = now
    todays = []
    for entry in entries:
        first = datetime.fromtimestamp(entry["first_ms"] / 1000, UTC)
        if first < day_start or first > day_end:
            continue
        todays.append((first, entry))
    if not todays:
        return {"status": "NO_CHUNKS_TODAY", "recorder": str(root),
                "gap_pct": None, "alert": False,
                "day": day_start.date().isoformat()}
    todays.sort(key=lambda pair: pair[0])
    covered_ms = sum(max(0, int(e["last_ms"]) - int(e["first_ms"]))
                     for _, e in todays)
    span_ms = max(0, int(day_end.timestamp() * 1000)
                  - int(todays[0][0].timestamp() * 1000))
    gap_pct = 0.0 if span_ms <= 0 else max(
        0.0, (1.0 - covered_ms / span_ms) * 100.0)
    gaps = sum(int(e.get("gaps", 0) or 0) for _, e in todays)
    alert = gap_pct > ALERT_PCT
    report = {"status": "OK", "recorder": str(root),
              "day": day_start.date().isoformat(),
              "chunks": len(todays), "covered_s": round(covered_ms / 1000, 1),
              "span_s": round(span_ms / 1000, 1),
              "gap_pct": round(gap_pct, 3), "sequence_gaps": gaps,
              "alert": alert, "alert_threshold_pct": ALERT_PCT}
    if alert and notify:
        _notify(f"Recorder gap {gap_pct:.1f}% today "
                f"(threshold {ALERT_PCT:.0f}%)")
        report["notified"] = True
    return report


__all__ = ["ALERT_PCT", "recorder_gap_report"]
