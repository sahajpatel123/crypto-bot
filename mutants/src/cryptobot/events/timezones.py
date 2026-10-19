"""Timezone helpers for macro events (Worker 4, EV-001).

Scheduled times are authored in America/New_York wall time (the official
calendar convention) and converted to UTC for storage/comparison. Display
uses Asia/Kolkata (IST, no DST).

US Eastern has DST, so there is no fixed-offset fallback: a host without
tzdata raises an explicit error instead of silently using a wrong offset.
IST uses the fixed UTC+5:30 fallback (identical by construction, since IST
observes no DST) following src/cryptobot/accounting/day.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ET_NAME = "America/New_York"
IST_NAME = "Asia/Kolkata"
IST_FALLBACK = timezone(timedelta(hours=5, minutes=30))


def et_tz() -> ZoneInfo:
    try:
        return ZoneInfo(ET_NAME)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(
            "tzdata missing America/New_York; refusing to guess the "
            "EST/EDT offset (install tzdata)") from exc


def ist_tz():
    try:
        return ZoneInfo(IST_NAME)
    except ZoneInfoNotFoundError:
        return IST_FALLBACK


def et_local(year: int, month: int, day: int, hour: int,
             minute: int, second: int = 0) -> datetime:
    """Build an aware America/New_York wall time.

    Rejects nonexistent wall times (spring-forward gap) explicitly.
    """
    zone = et_tz()
    naive = datetime(year, month, day, hour, minute, second)
    moment = naive.replace(tzinfo=zone, fold=0)
    # Round-trip check: a nonexistent wall time does not survive.
    back = moment.astimezone(timezone.utc).astimezone(zone)
    if back.replace(tzinfo=None) != naive:
        raise ValueError(f"nonexistent {ET_NAME} wall time: {naive.isoformat()}")
    return moment


def et_from_iso(local_iso: str) -> datetime:
    """Parse 'YYYY-MM-DDTHH:MM[:SS]' as America/New_York (or tz-tagged ISO)."""
    text = local_iso.strip()
    if text.endswith(("Z", "z")) or "+" in text[10:] or text[10:].count("-") > 2:
        # Already offset-aware ISO; honor it but require a real offset.
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if moment.tzinfo is None:
            raise ValueError(f"naive timestamp with tz marker: {text!r}")
        return moment
    naive = datetime.fromisoformat(text)
    if naive.tzinfo is not None:
        raise ValueError(f"unexpected tzinfo in wall time: {text!r}")
    return et_local(naive.year, naive.month, naive.day, naive.hour,
                    naive.minute, naive.second)


def to_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("moment must be timezone-aware")
    return moment.astimezone(timezone.utc)


def to_ist(moment_utc: datetime) -> datetime:
    if moment_utc.tzinfo is None:
        raise ValueError("moment must be timezone-aware")
    return moment_utc.astimezone(ist_tz())


def format_ist(moment_utc: datetime) -> str:
    """Render 'YYYY-MM-DD HH:MM IST' for reports and logs."""
    return to_ist(moment_utc).strftime("%Y-%m-%d %H:%M IST")


def parse_iso_utc(text: str) -> datetime:
    moment = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise ValueError(f"naive timestamp, UTC required: {text!r}")
    return moment.astimezone(timezone.utc)
