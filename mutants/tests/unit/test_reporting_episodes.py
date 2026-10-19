"""V-007: episode rebuild — partials, flips, shorts, funding attribution."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cryptobot.reporting.episodes import build_episodes
from cryptobot.reporting.schemas import Fill

T0 = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


def _fill(ts, side, qty, price, fee=0.0, exec_id="x", client="c"):
    return Fill(execution_id=exec_id, client_order_id=client, instrument="BTCUSDT",
                side=side, qty=qty, price=price, fee=fee,
                liquidity="taker", ts_utc=ts)


def _t(hours):
    return datetime(2026, 10, 10, 12 + hours, 0, tzinfo=timezone.utc)


def test_simple_round_trip_math():
    eps = build_episodes([
        _fill(_t(0), "BUY", 1.0, 100.0, 1.0, "e1"),
        _fill(_t(1), "SELL", 1.0, 110.0, 1.0, "e2"),
    ], [], _t(2))
    assert len(eps) == 1
    e = eps[0]
    assert (e.side, e.qty, e.entry_px, e.exit_px) == ("LONG", 1.0, 100.0, 110.0)
    assert e.gross == pytest.approx(10.0)
    assert e.fees == pytest.approx(2.0)
    assert e.net == pytest.approx(8.0)
    assert e.end_of_data is False
    assert e.holding_s == pytest.approx(3600.0)


def test_partial_exits_aggregate_as_legs():
    eps = build_episodes([
        _fill(_t(0), "BUY", 1.0, 100.0, 1.0, "e1"),
        _fill(_t(1), "SELL", 0.4, 110.0, 1.0, "e2"),
        _fill(_t(2), "SELL", 0.6, 108.0, 1.0, "e3"),
    ], [], _t(3))
    assert len(eps) == 1
    e = eps[0]
    assert len(e.legs) == 3
    assert e.exit_px == pytest.approx(108.8)
    assert e.gross == pytest.approx(8.8)
    assert e.net == pytest.approx(5.8)


def test_flip_splits_two_episodes_with_cost_transfer():
    eps = build_episodes([
        _fill(_t(0), "BUY", 1.0, 100.0, 0.0, "e1"),
        _fill(_t(1), "SELL", 1.5, 110.0, 0.0, "e2"),
        _fill(_t(2), "BUY", 0.5, 105.0, 0.0, "e3"),
    ], [], _t(3))
    assert len(eps) == 2
    assert eps[0].side == "LONG" and eps[0].qty == pytest.approx(1.0)
    assert eps[0].net == pytest.approx(10.0)
    assert eps[1].side == "SHORT" and eps[1].qty == pytest.approx(0.5)
    assert eps[1].entry_px == pytest.approx(110.0)
    assert eps[1].net == pytest.approx(2.5)


def test_open_at_end_is_marked_end_of_data():
    eps = build_episodes([_fill(_t(0), "BUY", 1.0, 100.0, 1.0, "e1")], [], _t(2))
    assert len(eps) == 1
    e = eps[0]
    assert e.end_of_data is True
    assert e.exit_px == pytest.approx(100.0)  # marked at last fill, disclosed
    assert e.gross == pytest.approx(0.0)
    assert e.net == pytest.approx(-1.0)


def test_short_side_signs():
    eps = build_episodes([
        _fill(_t(0), "SELL", 2.0, 100.0, 0.0, "e1"),
        _fill(_t(1), "BUY", 2.0, 90.0, 0.0, "e2"),
    ], [], _t(2))
    assert eps[0].side == "SHORT"
    assert eps[0].gross == pytest.approx(20.0)


def test_funding_attributes_by_window_overlap_and_conserves():
    eps = build_episodes([
        _fill(_t(0), "BUY", 1.0, 100.0, 0.0, "e1"),
        _fill(_t(1), "SELL", 1.0, 100.0, 0.0, "e2"),
        _fill(_t(2), "BUY", 1.0, 100.0, 0.0, "e3"),
        _fill(_t(3), "SELL", 1.0, 100.0, 0.0, "e4"),
    ], [(_t(0), -4.0)], _t(4))
    # Funding at t0 lands exactly on ep1 open → fully ep1's (conservation holds).
    assert eps[0].funding == pytest.approx(-4.0)
    assert eps[1].funding == pytest.approx(0.0)
    assert sum(e.funding for e in eps) == pytest.approx(-4.0)


def test_funding_outside_all_windows_is_orphan_but_conserved():
    eps = build_episodes([
        _fill(_t(0), "BUY", 1.0, 100.0, 0.0, "e1"),
        _fill(_t(1), "SELL", 1.0, 100.0, 0.0, "e2"),
    ], [(_t(3), -2.0)], _t(4))
    assert eps[0].funding == pytest.approx(0.0)
    # Conservation is enforced by metrics.reconcile via the orphan term.
