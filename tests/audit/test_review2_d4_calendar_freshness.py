"""Review-2 defect 4: calendar freshness renewed without fetching (W5-24H).

Loading the same FOMC fixture on 12 and 14 October creates new fetched
timestamps and fresh status, with identical cached events and no HTTP
verification (FixtureAdapter.load stamps fetched_utc=now_utc every load).

Required: preserve source verified/fetched timestamp across
reload/restart. Implement background official-source refresh, cached
outage behavior and explicit expiry. Local reading is not a fetch.

Fails on base 3cadfca (bug reproduced); passes once fixed.
Strict-xfail marked in tests/audit/conftest.py while open.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.events.freshness import (
    FreshnessTracker, HttpResponse)
from cryptobot.events.sources import CpiSource, FomcSource
from cryptobot.events.store import EventStore

D12 = datetime(2026, 10, 12, tzinfo=timezone.utc)
D14 = datetime(2026, 10, 14, tzinfo=timezone.utc)
CANNED = (Path(__file__).resolve().parents[2] / "src" / "cryptobot"
          / "events" / "fixtures" / "canned")


def _canned(url, timeout_s=20):
    name = ("fomc_page_2026.txt" if "fomc" in url.lower()
            else "bls_cpi_page_2026.txt")
    return HttpResponse(status=200, body=(CANNED / name).read_bytes(),
                        url=url)


def test_fetched_timestamp_preserved_across_reload(tmp_path):
    """Verified fetch time persists across tracker reload/restart."""
    state = tmp_path / "event_source_state.json"
    store = EventStore()
    first = FreshnessTracker(state, [FomcSource(), CpiSource()])
    assert first.local_load(store, D12)
    assert all(v.ok for v in
               first.refresh_once(store, _canned, D12).values())
    verified = {s: first.states.get(s).verified_utc
                for s in ("fomc", "cpi")}
    assert all(verified.values()), "setup broken: refresh did not verify"
    # Restart: a fresh tracker on the same state file keeps verified_utc,
    # and a local re-read resolves fresh without re-verifying.
    second = FreshnessTracker(state, [FomcSource(), CpiSource()])
    for source, stamp in verified.items():
        assert second.states.get(source).verified_utc == stamp, (
            f"{source}: verified_utc not preserved across reload")
    assert second.local_load(EventStore(), D14) == {
        "fomc": "fresh", "cpi": "fresh"}


def test_reread_without_verification_is_not_fresh():
    """Two days later with no fetch, status must not claim fresh."""
    second = FomcSource().load(D14)
    assert second.status != "fresh", (
        f"local re-read reports status=fresh with fetched={second.fetched_utc}; "
        f"unverified cache must be stale/expired/outage, never fresh")
