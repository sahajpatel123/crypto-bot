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

from cryptobot.events.sources import FomcSource

D12 = datetime(2026, 10, 12, tzinfo=timezone.utc)
D14 = datetime(2026, 10, 14, tzinfo=timezone.utc)


def test_fetched_timestamp_preserved_across_reload():
    """A re-read must keep the original verified fetch timestamp."""
    first = FomcSource().load(D12)
    second = FomcSource().load(D14)
    assert first.events, "setup broken: fixture carries no events"
    assert len(second.events) == len(first.events), (
        "setup broken: cached events changed between identical loads")
    assert second.fetched_utc == first.fetched_utc, (
        f"reload renewed fetched {first.fetched_utc} -> "
        f"{second.fetched_utc} with no HTTP verification")


def test_reread_without_verification_is_not_fresh():
    """Two days later with no fetch, status must not claim fresh."""
    second = FomcSource().load(D14)
    assert second.status != "fresh", (
        f"local re-read reports status=fresh with fetched={second.fetched_utc}; "
        f"unverified cache must be stale/expired/outage, never fresh")
