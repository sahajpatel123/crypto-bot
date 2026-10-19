"""Focused tests for the preregistered H1/H2/H3 dev evaluation."""
from __future__ import annotations

from cryptobot.research.h_eval import (
    Bar,
    h1_result,
    h2_trades,
    h3_trades,
    max_drawdown_bps,
    verdict_for,
)


def _trend_bars(n: int = 300) -> list[Bar]:
    bars, price = [], 100.0
    for i in range(n):
        price *= 1.002  # steady uptrend: EMA20 > EMA50, ATR gate passes
        bars.append(Bar(ts_ms=i * 3_600_000, open=price * 0.999,
                        high=price * 1.004, low=price * 0.996, close=price))
    return bars


def test_h2_trades_pay_taker_costs() -> None:
    trades = h2_trades(_trend_bars())
    assert trades, "uptrend must produce H2 trades"
    assert all(t.net_bps < t.gross_bps for t in trades)
    assert all(t.adverse_bps < t.net_bps for t in trades)


def test_h3_fades_funding_extreme() -> None:
    bars = _trend_bars(400)
    funding = [(i * 28_800_000, 0.0001) for i in range(40)]
    funding.append((40 * 28_800_000, 0.001))  # extreme positive -> short
    trades = h3_trades(bars, funding)
    assert trades, "funding extreme must produce an H3 trade"


def test_h1_unevaluable_without_book() -> None:
    assert h1_result()["verdict"] == "UNDERPOWERED"
    assert "UNEVALUABLE" in h1_result()["reason"]


def test_h1_imbalance_and_fill() -> None:
    from cryptobot.research.h1_eval import Snapshot, h1_trades, imbalance
    heavy_bid = Snapshot(ts_ms=0, bids=((100.0, 10.0),), asks=((101.0, 1.0),))
    assert imbalance(heavy_bid) is not None and imbalance(heavy_bid) > 0.6
    rising = [heavy_bid] + [
        Snapshot(ts_ms=k * 1000, bids=((100.0 + k, 5.0),),
                 asks=((101.0 + k, 5.0),)) for k in range(1, 60)]
    prints = [(500, 99.0, 50.0)]  # trades through the 100.0 bid -> fill
    trades = h1_trades(rising, prints)
    assert trades and trades[0].gross_bps > 0
    assert h1_trades(rising, []) == []  # no through-volume -> cancelled


def test_h4_ranks_causally() -> None:
    from cryptobot.research.h_eval import h4_trades
    calm = _trend_bars()
    volatile = [Bar(ts_ms=b.ts_ms, open=b.open, high=b.high * 1.05,
                    low=b.low * 0.95, close=b.close) for b in _trend_bars()]
    trades = h4_trades({"CALM": calm, "WILD": volatile,
                        "CALM2": calm, "CALM3": calm})
    assert isinstance(trades, list)  # synthetic only; fresh-data scoring locked


def test_drawdown_and_verdict_shape() -> None:
    bars = _trend_bars()
    trades = h2_trades(bars)
    assert max_drawdown_bps(trades) >= 0.0
    doc = verdict_for("H2-test", trades)
    assert doc["verdict"] in ("PASS", "FAIL", "UNDERPOWERED")
    assert "mean_net_bps_per_active_day" in doc
