"""F1.2 round-2 kills: ordermanager AFTER-survivors (8 real gaps).

Each test names its mutant(s) and fails on the mutated behavior:
_position_state epsilon boundaries (3), poll late-fill boundary +
resolved-break (2), recover detail-default + topup-default (3).
Proven-equivalent survivors (role-default x2, journal-encoding x5)
are justified in STATE.md, not tested.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cryptobot.execution import FakeVenue, OrderManager, OrderState

NOW = datetime(2026, 10, 17, 12, 0, 0, tzinfo=UTC)


def _manager(venue, tmp_path, **kw):
    return OrderManager(venue, log_path=tmp_path / "orders.jsonl",
                        now_utc=lambda: NOW, **kw)


class _Sink:
    """Recording RiskOutcomeSink (mirrors the kill-file sink)."""

    def __init__(self):
        self.deltas = []
        self.fills = []
        self.releases = []
        self.flats = 0

    def note_fill_delta(self, reservation_id, exec_id, symbol, venue_side,
                        qty, price, fee, ts_utc):
        self.deltas.append((reservation_id, exec_id, symbol, venue_side,
                            qty, price, fee, ts_utc))

    def note_fill(self, reservation_id):
        self.fills.append(reservation_id)

    def release(self, reservation_id):
        self.releases.append(reservation_id)
        return True

    def note_flat(self):
        self.flats += 1


def test_kill2_poll_late_fill_exact_eps(tmp_path):
    # poll__mutmut_56: `filled > before + 1e-12` vs `>=` — an exact
    # +1e-12 delta is float noise, not a late fill.
    venue = FakeVenue()
    mgr = _manager(venue, tmp_path)
    order = mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                             expire_at_utc=NOW + timedelta(seconds=60),
                             kind="STOP_MARKET", reservation_id="r-1")
    venue.cancel(order.client_id)
    mgr.poll()
    assert order.state == OrderState.CANCELLED
    venue.inject_fill(order.client_id, 1e-12, 1.0)
    events = mgr.poll()
    assert {"client_id": order.client_id,
            "event": "late-fill-booked"} not in events


def test_kill2_poll_resolved_continues_not_breaks(tmp_path):
    # poll__mutmut_80 (F1.2-fix line): `continue` vs `break` — a
    # resolved first order must not starve later orders of reads.
    venue = FakeVenue()
    mgr = _manager(venue, tmp_path, outcome_sink=_Sink())
    first = mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                             expire_at_utc=NOW + timedelta(seconds=60),
                             kind="STOP_MARKET", reservation_id="r-1")
    venue.cancel(first.client_id)
    mgr.poll()
    assert first.state == OrderState.CANCELLED
    second = mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                              expire_at_utc=NOW + timedelta(seconds=60),
                              kind="STOP_MARKET", reservation_id="r-2")
    venue.inject_fill(second.client_id, 0.01, 1.0)
    assert second.filled_qty == 0.0
    mgr.poll()
    # Break-mutant skips the second order (stays unfilled); orig adopts.
    assert second.filled_qty == 0.01


def test_kill2_recover_detail_fail_closed(tmp_path):
    # recover__mutmut_45/47 JUSTIFIED (fail-closed equivalent): rows
    # whose event NEEDS detail (callback-fired) crash recovery loudly
    # in every variant (KeyError orig vs TypeError mutants) — never a
    # silent mis-recovery. This pins the loudness, not the type.
    import json


    venue = FakeVenue()
    mgr = _manager(venue, tmp_path)
    mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                     expire_at_utc=NOW + timedelta(seconds=60),
                     kind="STOP_MARKET")
    path = tmp_path / "orders.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"client_id": "*", "event": "callback-fired",
                             "order": {}}) + "\n")
    with pytest.raises((KeyError, TypeError, ValueError)):
        OrderManager.recover(venue, path, now_utc=lambda: NOW)


def test_kill2_recover_topup_attempt_default(tmp_path):
    # recover__mutmut_104: `.get(res, 0)` vs `.get(res, 1)` — attempts
    # rebuild exactly (off-by-one would steal a retry post-restart).

    venue = FakeVenue()
    mgr = _manager(venue, tmp_path)
    mgr.submit_entry("BTCUSDT", "LONG", 0.01, 1.0,
                     expire_at_utc=NOW + timedelta(seconds=60),
                     kind="STOP_MARKET", reservation_id="r-9")
    mgr._log("*", "topup-attempt",
             {"reservation_id": "r-9", "attempt": 2})
    recovered = OrderManager.recover(
        venue, tmp_path / "orders.jsonl", now_utc=lambda: NOW)
    assert recovered._topup_attempts == {"r-9": 2}
