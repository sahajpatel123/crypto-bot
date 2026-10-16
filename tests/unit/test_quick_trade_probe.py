"""Quick-trade probe: rule-level tests on synthetic streams.

Every expected number here is hand-computed from the frozen rules in
tools/quick_trade_probe.py; the tests pin causality (no fill before
decision), both fill sensitivities, the stop/horizon/expiry paths,
stale-book exclusion and markout signs.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import pytest  # noqa: E402

import quick_trade_probe as q  # noqa: E402


class S:
    def __init__(self) -> None:
        self.seq = 0
        self.ev: list[dict] = []

    def book(self, ts, bid, ask):
        self.seq += 1
        self.ev.append({"channel": "bookTicker", "symbol": "BTCUSDT",
                        "exchange_ts_ms": ts, "seq": self.seq,
                        "payload": {"bid": f"{bid:.2f}",
                                    "ask": f"{ask:.2f}"}})

    def trade(self, ts, px, qty=0.001, taker_buy=True):
        self.seq += 1
        self.ev.append({"channel": "aggTrade", "symbol": "BTCUSDT",
                        "exchange_ts_ms": ts, "seq": self.seq,
                        "payload": {"price": px, "qty": qty,
                                    "buyer_is_maker": not taker_buy}})

    def warmup(self, t0, n=26, step=1000, px=100.0, qty=0.01):
        for i in range(n):
            self.trade(t0 + i * step, px, qty)


T = 1_000_000


def _decision_stream(book_at_decision=True, fill_px=100.40):
    s = S()
    s.warmup(T)                       # 26 x 1s trades at 100.0
    if book_at_decision:
        s.book(T + 29_500, 100.35, 100.40)
    s.trade(T + 30_000, 100.40, qty=0.5)          # spike (disp 40 bps)
    s.book(T + 30_500, 100.35, 100.40)
    s.trade(T + 30_600, fill_px, qty=0.001)       # entry touch print
    s.trade(T + 30_700, 100.30, qty=0.001)        # maker exit print
    s.book(T + 35_700, 100.30, 100.35)            # markout 5s (mid .325)
    s.book(T + 60_700, 100.30, 100.30)            # markout 30s (mid .30)
    return s


def test_happy_path_maker_exit_exact_net():
    eps, counts, exits = q.probe_stream(
        _decision_stream().ev, ["BTCUSDT"], through=False)
    assert counts["candidates"] >= 1
    assert counts["filled"] == 1, counts
    assert exits == {"target-maker": 1, "stop": 0, "horizon": 0,
                     "exit-expiry": 0}
    [e] = eps
    assert e.bucket == "[12,inf)"
    # causality: the fill is strictly later than the decision event
    assert e.fill_order > (e.decision_ts, e.decision_seq)
    assert e.entry_limit == 100.40 and e.fill_price == 100.40
    assert e.exit_price == 100.35 and e.exit_how == "target-maker"
    q.apply_funding(e)
    assert e.gross_bps() == pytest.approx(4.980, abs=0.01)
    assert e.net(2.0, e.fee_out) == pytest.approx(0.980, abs=0.01)
    assert e.exit_ts - e.fill_ts == 100
    assert e.markout[5] == pytest.approx(7.470, abs=0.01)
    assert e.markout[30] == pytest.approx(9.960, abs=0.01)
    agg = q.aggregate([e])
    assert agg["overall"]["n"] == 1
    assert agg["overall"]["net_actual_mean_bps"] == pytest.approx(
        0.980, abs=0.01)
    assert agg["primary_disp_ge_5"]["n"] == 1
    assert agg["by_exit"]["target-maker"]["n"] == 1


def test_through_sensitivity_never_fills_at_limit():
    eps, counts, exits = q.probe_stream(
        _decision_stream().ev, ["BTCUSDT"], through=True)
    # the entry print sits exactly AT the limit: through must not fill
    assert counts["filled"] == 0, counts
    assert counts["unfilled_entry"] == 1, counts
    assert eps == []


def test_stop_path_taker_exit():
    s = S()
    s.warmup(T)
    s.book(T + 29_500, 100.35, 100.40)
    s.trade(T + 30_000, 100.40, qty=0.5)
    s.book(T + 30_500, 100.35, 100.40)
    s.trade(T + 30_600, 100.40, qty=0.001)      # fill (touch)
    s.book(T + 31_000, 100.50, 100.52)          # >= 100.5004 -> stop
    s.book(T + 31_200, 100.50, 100.53)          # arrival resolves
    eps, counts, exits = q.probe_stream(s.ev, ["BTCUSDT"], through=False)
    [e] = eps
    assert e.exit_how == "stop" and e.fee_out == 5.0
    assert e.exit_price == 100.53
    assert e.gross_bps() == pytest.approx(-12.948, abs=0.01)
    assert e.net(2.0, 5.0) == pytest.approx(-19.948, abs=0.01)


def test_horizon_path_when_no_exit_book_at_fill():
    s = S()
    s.warmup(T)
    s.book(T + 29_500, 100.35, 100.40)
    s.trade(T + 30_000, 100.40, qty=0.5)
    s.trade(T + 30_600, 100.40, qty=0.001)      # fill; book age 1100ms ->
    # exit_limit unavailable -> horizon fallback (no expiry path)
    s.book(T + 150_800, 100.36, 100.38)         # >= fill+120_000
    s.book(T + 150_900, 100.36, 100.38)         # arrival
    eps, counts, exits = q.probe_stream(s.ev, ["BTCUSDT"], through=False)
    [e] = eps
    assert e.exit_how == "horizon" and e.fee_out == 5.0
    assert e.exit_price == 100.38
    assert e.gross_bps() == pytest.approx(1.992, abs=0.01)


def test_stale_book_excludes_candidate():
    s = S()
    s.warmup(T)
    s.book(T + 28_000, 100.35, 100.40)          # 2000ms old at decision
    s.trade(T + 30_000, 100.40, qty=0.5)
    eps, counts, exits = q.probe_stream(s.ev, ["BTCUSDT"], through=False)
    assert counts["candidates"] >= 1
    assert counts["stale_book"] == 1
    assert counts["filled"] == 0 and eps == []


def test_no_imputation_unresolved_counted_at_eof():
    s = S()
    s.warmup(T)
    s.book(T + 29_500, 100.35, 100.40)
    s.trade(T + 30_000, 100.40, qty=0.5)
    s.trade(T + 30_600, 100.40, qty=0.001)      # fill, then stream ends
    eps, counts, exits = q.probe_stream(s.ev, ["BTCUSDT"], through=False)
    assert counts["filled"] == 1
    assert counts["filled_unresolved_eof"] == 1


# -- continuous two-sided mode ---------------------------------------------


def test_continuous_bid_fill_then_spread_exit():
    s = S()
    s.warmup(T)
    s.book(T + 29_500, 100.00, 100.10)
    s.trade(T + 30_000, 100.00, qty=0.001)                 # arms two-sided
    s.trade(T + 30_100, 100.00, qty=0.001, taker_buy=False)  # sell hits bid
    s.trade(T + 30_200, 100.10, qty=0.001, taker_buy=True)   # buy -> exit
    eps, counts, exits = q.probe_stream(
        s.ev, ["BTCUSDT"], through=False, mode="continuous")
    [e] = eps
    assert counts["requotes"] == 1 and counts["filled"] == 1
    assert e.side == 1 and e.fill_price == 100.00
    assert e.exit_price == 100.10 and e.exit_how == "target-maker"
    assert e.gross_bps() == pytest.approx(10.0, abs=0.01)
    assert e.net(2.0, 2.0) == pytest.approx(6.0, abs=0.01)


def test_continuous_ask_fill_then_spread_exit():
    s = S()
    s.warmup(T)
    s.book(T + 29_500, 100.00, 100.10)
    s.trade(T + 30_000, 100.00, qty=0.001)
    s.trade(T + 30_100, 100.10, qty=0.001, taker_buy=True)   # buy hits ask
    s.trade(T + 30_200, 100.00, qty=0.001, taker_buy=False)  # sell -> exit
    eps, counts, exits = q.probe_stream(
        s.ev, ["BTCUSDT"], through=False, mode="continuous")
    [e] = eps
    assert e.side == -1 and e.fill_price == 100.10
    assert e.exit_price == 100.00
    assert e.gross_bps() == pytest.approx(9.990, abs=0.01)


def test_continuous_requote_after_expiry():
    s = S()
    s.warmup(T)
    s.book(T + 29_500, 100.00, 100.10)
    s.trade(T + 30_000, 100.00, qty=0.001)      # arm #1 (cap T+33_000)
    s.trade(T + 33_500, 100.00, qty=0.001)      # expiry -> unfilled
    s.book(T + 34_800, 100.00, 100.10)          # fresh book for re-arm
    s.trade(T + 35_000, 100.00, qty=0.001)      # arm #2
    eps, counts, exits = q.probe_stream(
        s.ev, ["BTCUSDT"], through=False, mode="continuous")
    assert counts["requotes"] == 2
    assert counts["unfilled_entry"] == 1
    assert counts["filled"] == 0 and eps == []
