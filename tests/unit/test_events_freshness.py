"""Freshness tests (Worker 4, W4-24H). Real verification, no minting."""
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import cryptobot.events as _evpkg  # noqa: E402
from cryptobot.events.freshness import (  # noqa: E402
    CACHE_TTL,
    FreshnessTracker,
    HttpResponse,
    SourceStateStore,
    parse_cpi_release_dates,
    parse_fomc_decision_dates,
)
from cryptobot.events.sources import CpiSource, FomcSource  # noqa: E402
from cryptobot.events.store import EventStore  # noqa: E402

CANNED = Path(_evpkg.__file__).parent / "fixtures" / "canned"
T0 = datetime(2026, 10, 12, 13, 0, tzinfo=UTC)


def _canned(url, timeout_s=20):
    name = ("fomc_page_2026.txt" if "federalreserve" in url
            else "bls_cpi_page_2026.txt")
    return HttpResponse(status=200, body=(CANNED / name).read_bytes(),
                        url=url)


def _tracker(tmp_path):
    return FreshnessTracker(tmp_path / "state.json",
                            [FomcSource(), CpiSource()])


def test_fomc_parser_finds_all_eight_decisions():
    body = (CANNED / "fomc_page_2026.txt").read_text()
    days = {day.isoformat() for day in parse_fomc_decision_dates(body)
            if day.year == 2026}
    assert days == {"2026-01-28", "2026-03-18", "2026-04-29",
                    "2026-06-17", "2026-07-29", "2026-09-16",
                    "2026-10-28", "2026-12-09"}


def test_cpi_parser_finds_all_twelve_releases():
    body = (CANNED / "bls_cpi_page_2026.txt").read_text()
    days = sorted(day.isoformat() for day in parse_cpi_release_dates(body))
    assert days == ["2026-01-13", "2026-02-13", "2026-03-11",
                    "2026-04-10", "2026-05-12", "2026-06-10",
                    "2026-07-14", "2026-08-12", "2026-09-11",
                    "2026-10-14", "2026-11-10", "2026-12-10"]


def test_parsers_reject_markerless_pages():
    with pytest.raises(ValueError, match="marker"):
        parse_fomc_decision_dates("nothing here")
    with pytest.raises(ValueError, match="marker"):
        parse_cpi_release_dates("nothing here")


def test_local_load_never_verifies(tmp_path):
    store = EventStore()
    resolved = _tracker(tmp_path).local_load(store, T0)
    assert resolved == {"fomc": "unverified", "cpi": "unverified"}
    assert len(store) == 28  # events load; trust does not
    # Reload two days later: still unverified, nothing minted.
    store2 = EventStore()
    resolved2 = _tracker(tmp_path).local_load(
        store2, T0 + timedelta(days=2))
    assert resolved2 == {"fomc": "unverified", "cpi": "unverified"}


def test_refresh_verifies_and_persists_across_restart(tmp_path):
    store = EventStore()
    tracker = _tracker(tmp_path)
    tracker.local_load(store, T0)
    results = tracker.refresh_once(store, _canned, T0)
    assert {k: v.ok for k, v in results.items()} == {"fomc": True,
                                                    "cpi": True}
    assert store.status_at(T0) == {"fomc": "fresh", "cpi": "fresh"}
    # Restart: fresh local load resolves fresh from persisted verified_utc.
    store2 = EventStore()
    resolved = _tracker(tmp_path).local_load(store2, T0)
    assert resolved == {"fomc": "fresh", "cpi": "fresh"}
    coverage = store2.coverage("fomc")
    assert coverage.verified_utc == T0
    assert coverage.expires_utc == T0 + CACHE_TTL


def test_verified_cache_expires_explicitly(tmp_path):
    store = EventStore()
    tracker = _tracker(tmp_path)
    tracker.local_load(store, T0)
    tracker.refresh_once(store, _canned, T0)
    store2 = EventStore()
    late = T0 + CACHE_TTL + timedelta(seconds=1)
    resolved = _tracker(tmp_path).local_load(store2, late)
    assert resolved == {"fomc": "stale", "cpi": "stale"}
    assert store2.status_at(late) == {"fomc": "stale", "cpi": "stale"}


def test_failed_refresh_keeps_cache_and_records_outage(tmp_path):
    store = EventStore()
    tracker = _tracker(tmp_path)
    tracker.local_load(store, T0)

    def down(url, timeout_s=20):
        raise ConnectionError("dns down")

    results = tracker.refresh_once(store, down, T0)
    assert results["fomc"].ok is False
    assert "ConnectionError" in results["fomc"].error
    assert len(store) == 28  # cache kept
    assert store.status_at(T0)["fomc"] == "outage"
    state = SourceStateStore(tmp_path / "state.json").load().get("fomc")
    assert state.consecutive_failures == 1
    assert state.verified_utc is None  # never moved


def test_http_error_is_outage_not_verification(tmp_path):
    store = EventStore()
    tracker = _tracker(tmp_path)
    tracker.local_load(store, T0)

    def forbidden(url, timeout_s=20):
        return HttpResponse(status=403, body=b"denied", url=url)

    results = tracker.refresh_once(store, forbidden, T0)
    assert results["cpi"].ok is False
    assert "403" in results["cpi"].error


def test_schedule_drift_never_auto_applies(tmp_path):
    store = EventStore()
    tracker = _tracker(tmp_path)
    tracker.local_load(store, T0)
    body = (CANNED / "bls_cpi_page_2026.txt").read_text().replace(
        "October 14, 2026", "October 21, 2026")

    def drifted(url, timeout_s=20):
        if "federalreserve" in url:
            return _canned(url)
        return HttpResponse(status=200, body=body.encode(), url=url)

    results = tracker.refresh_once(store, drifted, T0)
    assert results["cpi"].ok is False
    assert results["cpi"].missing == ("2026-10-14",)
    assert results["cpi"].extra == ("2026-10-21",)
    # Cache untouched: the Oct 14 event still stands as cached.
    assert store.get("CPI-2026-10-14").scheduled_utc == datetime(
        2026, 10, 14, 12, 30, tzinfo=UTC)


def test_background_thread_refreshes_then_stops(tmp_path):
    store = EventStore()
    tracker = _tracker(tmp_path)
    tracker.local_load(store, T0)
    seen: list = []
    tracker.start(store, _canned, interval_s=0.05, now_utc=lambda: T0,
                  on_result=seen.append)
    deadline = time.time() + 5
    while not seen and time.time() < deadline:
        time.sleep(0.05)
    tracker.stop()
    assert seen, "background refresh never fired"
    assert seen[0]["fomc"].ok is True
    assert store.status_at(T0) == {"fomc": "fresh", "cpi": "fresh"}
