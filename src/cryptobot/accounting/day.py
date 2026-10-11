"""Accounting-day helper (Worker 3, CONTRACTS v0.1.0).

Raw timestamps stay UTC; the accounting day is Asia/Kolkata 00:00-24:00. IST
observes no DST, so the zoneinfo result and the fixed UTC+5:30 fallback are
identical by construction; the fallback exists only for hosts without tzdata.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ACCOUNTING_TZ_NAME = "Asia/Kolkata"
IST_FALLBACK = timezone(timedelta(hours=5, minutes=30))


def accounting_tz():
    try:
        return ZoneInfo(ACCOUNTING_TZ_NAME)
    except ZoneInfoNotFoundError:
        return IST_FALLBACK


def accounting_date(moment_utc: datetime) -> date:
    if moment_utc.tzinfo is None:
        raise ValueError("moment must be timezone-aware")
    return moment_utc.astimezone(accounting_tz()).date()
