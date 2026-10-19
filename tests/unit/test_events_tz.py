"""Event timezone tests (Worker 4, EV-001). EST/EDT + IST pinned."""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.events.timezones import (
    et_from_iso,
    et_local,
    format_ist,
    to_ist,
    to_utc,
)
from cryptobot.events.types import Event


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def test_fomc_january_is_est():
    assert to_utc(et_local(2026, 1, 28, 14, 0)) == _utc(2026, 1, 28, 19, 0)


def test_fomc_summer_is_edt():
    assert to_utc(et_local(2026, 7, 29, 14, 0)) == _utc(2026, 7, 29, 18, 0)
    assert to_utc(et_local(2026, 9, 16, 14, 0)) == _utc(2026, 9, 16, 18, 0)


def test_fomc_october_still_edt_december_back_to_est():
    # US DST 2026 ends Nov 1: Oct 28 is EDT, Dec 9 is EST.
    assert to_utc(et_local(2026, 10, 28, 14, 0)) == _utc(2026, 10, 28, 18, 0)
    assert to_utc(et_local(2026, 12, 9, 14, 0)) == _utc(2026, 12, 9, 19, 0)


def test_cpi_straddles_spring_forward():
    # DST starts Mar 8 2026: Feb 13 is EST, Mar 11 is EDT.
    assert to_utc(et_local(2026, 2, 13, 8, 30)) == _utc(2026, 2, 13, 13, 30)
    assert to_utc(et_local(2026, 3, 11, 8, 30)) == _utc(2026, 3, 11, 12, 30)


def test_cpi_straddles_fall_back():
    # DST ends Nov 1 2026: Oct 14 is EDT, Nov 10 is EST.
    assert to_utc(et_local(2026, 10, 14, 8, 30)) == _utc(2026, 10, 14, 12, 30)
    assert to_utc(et_local(2026, 11, 10, 8, 30)) == _utc(2026, 11, 10, 13, 30)


def test_spring_forward_gap_rejected():
    with pytest.raises(ValueError, match="nonexistent"):
        et_local(2026, 3, 8, 2, 30)


def test_ist_display_and_date_rollover():
    assert format_ist(_utc(2026, 9, 16, 18, 0)) == "2026-09-16 23:30 IST"
    assert format_ist(_utc(2026, 1, 28, 19, 0)) == "2026-01-29 00:30 IST"
    assert to_ist(_utc(2026, 10, 14, 12, 30)).day == 14


def test_naive_moments_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        to_utc(datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="timezone-aware"):
        to_ist(datetime(2026, 1, 1))


def test_et_from_iso_wall_time():
    assert to_utc(et_from_iso("2026-09-16T14:00:00")) == _utc(2026, 9, 16, 18, 0)


def _event_kwargs(scheduled_utc):
    return dict(
        event_id="T-1", source="cpi", title="t", kind="release",
        source_url="https://www.bls.gov/schedule/",
        scheduled_local_iso="2026-10-14T08:30:00", tz_name="America/New_York",
        scheduled_utc=scheduled_utc,
        first_seen_utc=_utc(2026, 10, 12, 13, 10),
        fetch_utc=_utc(2026, 10, 12, 13, 10), revision=0,
        horizon_end_utc=_utc(2026, 12, 10, 13, 30),
        expires_utc=_utc(2026, 10, 21, 12, 30))


def test_event_rejects_wall_utc_mismatch():
    # Oct 14 is EDT (12:30 UTC); storing the EST instant must fail loudly.
    with pytest.raises(ValueError, match="!="):
        Event(**_event_kwargs(_utc(2026, 10, 14, 13, 30)))
    event = Event(**_event_kwargs(_utc(2026, 10, 14, 12, 30)))
    assert event.scheduled_utc == _utc(2026, 10, 14, 12, 30)
