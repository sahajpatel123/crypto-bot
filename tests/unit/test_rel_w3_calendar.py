"""REL-W3-DATA (4): BLS Employment gate, calendar refresh, cutoff.

- Employment fixture: officially-verified BLS dates, 08:30 ET, DST-aware.
- Refresh judges drift on upcoming dates only (scrolled-off past dates
  are not drift); missing upcoming dates -> drift outage -> no-entry.
- Admission cutoff: entries stop max-hold + exit-budget BEFORE each
  window so the full hold + orderly exit fit before the window opens.
- Missing/unverified required source -> no-entry; exits never blocked.
"""
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import cryptobot.events as _evpkg  # noqa: E402
from cryptobot.events.freshness import (FreshnessTracker,  # noqa: E402
                                        HttpResponse,
                                        parse_employment_dates)
from cryptobot.events.gate import EventGate, GateConfig  # noqa: E402
from cryptobot.events.profiles import (OperationalProfile,  # noqa: E402
                                       load_profile)
from cryptobot.events.sources import (CpiSource, EmploymentSource,  # noqa: E402
                                      FomcSource)
from cryptobot.events.store import EventStore  # noqa: E402

CANNED = Path(_evpkg.__file__).parent / "fixtures" / "canned"
REPO = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 10, 14, 4, 2, tzinfo=timezone.utc)


def _utc(*parts):
    return datetime(*parts, tzinfo=timezone.utc)


def _canned_empsit(http_url, timeout_s=20):
    return HttpResponse(status=200,
                        body=(CANNED / "bls_empsit_page_2026.txt").read_bytes(),
                        url=http_url)


def _employment_store(now, tmp_path, fetcher=_canned_empsit):
    store = EventStore()
    tracker = FreshnessTracker(tmp_path / "state.json", [EmploymentSource()])
    tracker.local_load(store, now)
    results = tracker.refresh_once(store, fetcher, now)
    assert all(r.ok for r in results.values())
    return store


def test_employment_fixture_verified_dates_and_release_time():
    snap = EmploymentSource().load(T0)
    assert snap.status == "cached"
    assert snap.source_url == \
        "https://www.bls.gov/schedule/news_release/empsit.htm"
    assert len(snap.events) == 14
    days = [e.scheduled_local_iso[:10] for e in snap.events]
    assert days == ["2026-11-06", "2026-12-04", "2027-01-08",
                    "2027-02-05", "2027-03-05", "2027-04-02",
                    "2027-05-07", "2027-06-04", "2027-07-02",
                    "2027-08-06", "2027-09-03", "2027-10-08",
                    "2027-11-05", "2027-12-03"]
    for event in snap.events:
        wall = datetime.fromisoformat(event.scheduled_local_iso)
        assert (wall.hour, wall.minute) == (8, 30)
        assert event.tz_name == "America/New_York"
    # DST spot checks: EST (UTC-5) in Nov 2026, EDT (UTC-4) in Jul 2027.
    by_id = {e.event_id: e for e in snap.events}
    assert by_id["EMP-2026-11-06"].scheduled_utc == \
        datetime(2026, 11, 6, 13, 30, tzinfo=timezone.utc)
    assert by_id["EMP-2027-07-02"].scheduled_utc == \
        datetime(2027, 7, 2, 12, 30, tzinfo=timezone.utc)
    assert snap.horizon_end_utc == datetime(2027, 12, 3, 13, 30,
                                            tzinfo=timezone.utc)


def test_employment_parser_release_list_rows_and_malformed_skip():
    body = ("Employment Situation\n"
            "<td>Nov. 6, 2026</td><td>08:30 AM</td>\n"
            "<td>May 7, 2027</td><td>08:30 AM</td>\n"  # May: no dot
            "<td>Sept. 3, 2027</td><td>08:30 AM</td>\n"
            "<td>Not a date</td><td>08:30 AM</td>\n")
    assert parse_employment_dates(body) == {date(2026, 11, 6),
                                            date(2027, 5, 7),
                                            date(2027, 9, 3)}


def test_employment_refresh_verifies_against_canned_page(tmp_path):
    store = EventStore()
    tracker = FreshnessTracker(tmp_path / "state.json", [EmploymentSource()])
    tracker.local_load(store, T0)
    results = tracker.refresh_once(store, _canned_empsit, T0)
    assert results["employment"].ok is True
    gate = EventGate(store, GateConfig(required_sources=("employment",)))
    assert gate.coverage_report(T0)["employment"] == "fresh"


def test_refresh_ignores_scrolled_off_past_dates(tmp_path):
    """Past cached dates missing from the page are not drift (REL-W3).

    At 2027-06-01 the Nov-2026..May-2027 releases have scrolled off the
    official page; refresh must still verify on the upcoming dates.
    """
    now = _utc(2027, 6, 1, 12, 0)
    rows = ["Employment Situation"]
    for month, day in [("Jun.", 4), ("Jul.", 2), ("Aug.", 6), ("Sep.", 3),
                       ("Oct.", 8), ("Nov.", 5), ("Dec.", 3)]:
        rows.append(f"<td>{month} {day}, 2027</td><td>08:30 AM</td>")
    page = "\n".join(rows).encode()

    def _scrolled(http_url, timeout_s=20):
        return HttpResponse(status=200, body=page, url=http_url)

    store = EventStore()
    tracker = FreshnessTracker(tmp_path / "state.json", [EmploymentSource()])
    tracker.local_load(store, now)
    results = tracker.refresh_once(store, _scrolled, now)
    assert results["employment"].ok is True


def test_refresh_missing_upcoming_date_is_drift_outage(tmp_path):
    """An upcoming cached date absent from the page blocks entries."""
    page = ("Employment Situation\n"
            "<td>Dec. 4, 2026</td><td>08:30 AM</td>\n").encode()

    def _drifted(http_url, timeout_s=20):
        return HttpResponse(status=200, body=page, url=http_url)

    store = EventStore()
    tracker = FreshnessTracker(tmp_path / "state.json", [EmploymentSource()])
    tracker.local_load(store, T0)
    results = tracker.refresh_once(store, _drifted, T0)
    result = results["employment"]
    assert result.ok is False
    assert "2026-11-06" in result.missing
    gate = EventGate(store, GateConfig(required_sources=("employment",)))
    decision = gate.check(T0)
    assert decision.blocked is True
    assert decision.reason == "event:stale-source:employment:outage"


def test_cutoff_fits_hold_plus_exit_before_every_window():
    """cutoff = window_start - 300 - 120 for every fixture event (REL-W3).

    A position admitted at the cutoff is flat by window start under
    normal closes; the 900s pre-buffer keeps 480s of slack for
    abnormal exits.
    """
    gate = EventGate(EventStore())
    assert gate.config.max_hold_s == 300
    assert gate.config.exit_budget_s == 120
    events = (FomcSource().load(T0).events + CpiSource().load(T0).events
              + EmploymentSource().load(T0).events)
    assert len(events) == 16 + 12 + 14
    for event in events:
        start, _ = gate.window(event)
        assert (start - gate.admission_cutoff(event)).total_seconds() == 420
        assert gate.config.pre_buffer_s - 420 == 480


def test_employment_window_blocks_from_cutoff(tmp_path):
    """EMP-2026-11-06: 13:30 UTC release, window 13:15, cutoff 13:08."""
    now = _utc(2026, 11, 6, 12, 0)
    gate = EventGate(_employment_store(now, tmp_path),
                     GateConfig(required_sources=("employment",)))
    assert gate.check(_utc(2026, 11, 6, 13, 7, 59)).reason == "event:clear"
    blocked = gate.check(_utc(2026, 11, 6, 13, 8))
    assert blocked.blocked is True
    assert blocked.reason == "event:pre-window:EMP-2026-11-06"
    assert gate.check(_utc(2026, 11, 6, 13, 30)).reason == \
        "event:in-window:EMP-2026-11-06"


def test_missing_employment_coverage_means_no_entry_exits_open(tmp_path):
    """Required employment source with no coverage blocks entries (REL-W3).

    The gate answers entry admission only: no exit-blocking API exists,
    so the no-entry policy cannot suppress protective exits.
    """
    gate = EventGate(EventStore(),
                     GateConfig(required_sources=("employment",)))
    decision = gate.check(T0)
    assert decision.blocked is True
    assert decision.reason == "event:stale-source:employment:unknown"
    assert [name for name in dir(EventGate) if "exit" in name] == []


def test_protected_profile_requires_all_three_sources():
    profile = load_profile(REPO / "configs" / "paper-protected.toml")
    assert isinstance(profile, OperationalProfile)
    assert profile.posture == "protected-operational"
    assert profile.gate.required_sources == ("fomc", "cpi", "employment")
    assert profile.gate.max_hold_s == 300
    assert profile.gate.exit_budget_s == 120


def test_profile_rejects_non_list_required_sources(tmp_path):
    bad = (REPO / "configs" / "paper-protected.toml").read_text()
    bad = bad.replace('required_sources = ["fomc", "cpi", "employment"]',
                      'required_sources = "fomc"')
    path = tmp_path / "bad.toml"
    path.write_text(bad)
    try:
        load_profile(path)
    except ValueError as exc:
        assert "required_sources" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("non-list required_sources accepted")
