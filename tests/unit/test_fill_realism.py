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


def test_paper_fill_parameters_derive_from_spread_depth_latency():
    from cryptobot.execution.fill_realism import PaperFillParameters

    base = PaperFillParameters(tick_size_bps=1.0, spread_bps=2.0,
                               depth_multiple=1.0, latency_ms=250.0,
                               latency_drift_bps_per_s=2.0)
    # 1 (half spread) + 0 (depth) + 0.5 (latency) = 1.5 ticks
    assert base.expected_ticks == pytest.approx(1.5)
    assert base.adverse_bps == pytest.approx(1.5)
    assert base.slippage_probability == 1.0

    wider = PaperFillParameters(tick_size_bps=1.0, spread_bps=10.0,
                                depth_multiple=1.0, latency_ms=250.0)
    deeper = PaperFillParameters(tick_size_bps=1.0, spread_bps=2.0,
                                 depth_multiple=4.0, latency_ms=250.0)
    slower = PaperFillParameters(tick_size_bps=1.0, spread_bps=2.0,
                                 depth_multiple=1.0, latency_ms=2000.0)
    assert wider.expected_ticks > base.expected_ticks
    assert deeper.expected_ticks > base.expected_ticks
    assert slower.expected_ticks > base.expected_ticks
    # Floor: a benign quote still costs at least one adverse tick.
    benign = PaperFillParameters(spread_bps=0.0, latency_ms=0.0,
                                 depth_multiple=1.0)
    assert benign.expected_ticks == pytest.approx(1.0)
    # Cap keeps the paper stress bounded.
    extreme = PaperFillParameters(tick_size_bps=0.1, spread_bps=100.0,
                                  latency_ms=10000.0, cap_ticks=5.0)
    assert extreme.expected_ticks == pytest.approx(5.0)


def test_paper_fill_parameters_reject_invalid():
    from cryptobot.execution.fill_realism import PaperFillParameters

    with pytest.raises(ValueError):
        PaperFillParameters(tick_size_bps=0.0)
    with pytest.raises(ValueError):
        PaperFillParameters(depth_multiple=0.5)
    with pytest.raises(ValueError):
        PaperFillParameters(floor_ticks=3.0, cap_ticks=2.0)
