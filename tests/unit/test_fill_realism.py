"""T1.9: paper fills are pessimistic by default (never zero-slippage)."""
from __future__ import annotations

import pytest

from cryptobot.execution.fill_realism import pessimistic_fill_price, stressed_pnl


def test_book_walk_buy_walks_asks_plus_latency():
    asks = [(100.0, 0.5), (101.0, 1.0)]
    # Buy 1.0: 0.5@100 + 0.5@101 = 100.5 avg; +10bps latency penalty
    px = pessimistic_fill_price("BUY", qty=1.0, levels=asks,
                                latency_bps=10.0)
    assert px == pytest.approx(100.5 * 1.001)


def test_book_walk_sell_walks_bids_minus_latency():
    bids = [(100.0, 0.5), (99.0, 1.0)]
    px = pessimistic_fill_price("SELL", qty=1.0, levels=bids,
                                latency_bps=10.0)
    assert px == pytest.approx(99.5 * 0.999)


def test_insufficient_depth_fills_at_worst_plus_penalty():
    px = pessimistic_fill_price("BUY", qty=5.0, levels=[(100.0, 0.5)],
                                latency_bps=0.0, empty_book_bps=25.0)
    # 0.5@100 + 4.5@100*1.0025 -> vwap 100.225
    assert px == pytest.approx(100.225)


def test_stressed_pnl_reports_1x_and_2x():
    out = stressed_pnl(gross_pnl=100.0, costs_1x=30.0)
    assert out["pnl_1x"] == 70.0
    assert out["pnl_2x"] == 40.0


def test_paper_engine_default_is_pessimistic(tmp_path):
    import inspect

    from cryptobot.adapters import paper_engine

    src = inspect.getsource(paper_engine)
    assert "prob_slippage=0.0" not in src
