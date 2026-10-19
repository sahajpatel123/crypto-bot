"""STUDY-04 unit tests — pin the frozen P1 conventions.

Fill-model bracketing, toxicity cancel/re-quote, flat-biased inventory
exit, round-trip economics, and the frozen decision rule.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import pivot_study_04_maker as S04  # noqa: E402


def _sim(model: str = "optimistic", tick: float = 0.1,
         toxicity: float = 0.6) -> S04.MakerSim:
    s = S04.MakerSim("TESTUSDT", model, tick, toxicity)
    s.on_book(1_000, 100.0, 100.1)  # quotes both sides at the touch
    return s


# ------------------------------------------------------------- fill models

def test_optimistic_fills_on_touch_trade() -> None:
    s = _sim("optimistic")
    assert s.bid_order == 100.0 and s.ask_order == 100.1
    s.on_trade(2_000, 100.0, 1.0, buyer_is_maker=True)  # taker sell at bid
    assert s.pos == 1 and s.fills[0]["side"] == "BUY"


def test_conservative_ignores_touch_requires_through() -> None:
    s = _sim("conservative")
    s.on_trade(2_000, 100.0, 1.0, buyer_is_maker=True)   # touch, not through
    assert s.pos == 0 and len(s.fills) == 0
    # thin flow (1 trade < 20) must NOT trip the toxicity filter (A1)
    assert s.bid_order == 100.0
    s.on_trade(3_000, 99.9, 1.0, buyer_is_maker=True)    # strictly through
    assert s.pos == 1 and s.fills[0]["side"] == "BUY"


def test_ask_fills_on_taker_buy() -> None:
    s = _sim("optimistic")
    s.on_trade(2_000, 100.1, 1.0, buyer_is_maker=False)  # taker buy at ask
    assert s.pos == -1 and s.fills[0]["side"] == "SELL"


def test_opposite_fill_closes_not_flips() -> None:
    s = _sim("optimistic")
    s.on_trade(2_000, 100.0, 1.0, buyer_is_maker=True)   # long @ bid
    s.on_trade(3_000, 100.1, 1.0, buyer_is_maker=False)  # ask hit closes it
    assert s.pos == 0 and len(s.round_trips) == 1
    # and a bid fill while short closes the short (not double-long)
    s2 = _sim("optimistic")
    s2.on_trade(2_000, 100.1, 1.0, buyer_is_maker=False)  # short @ ask
    s2.on_trade(3_000, 100.0, 1.0, buyer_is_maker=True)   # bid hit closes it
    assert s2.pos == 0 and len(s2.round_trips) == 1


# ------------------------------------------------------------- quoting

def test_requote_on_tick_move_away() -> None:
    s = _sim("optimistic")
    s.on_book(2_000, 100.2, 100.3)  # touch moved up 2 ticks
    assert s.bid_order == 100.2  # re-joined the new bid
    assert s.ask_order == 100.3


def test_toxicity_cancels_harmed_side_then_requotes_after_calm() -> None:
    s = _sim("optimistic", toxicity=0.6)
    # dense aggressive buying (>= 20 trades: A1 density floor): the FIRST
    # buy fills the ask (optimistic touch), and the continued toxic flow
    # keeps the ask gated (post-fill calm gate, A1)
    for i in range(25):
        s.on_trade(2_000 + i * 300, 100.2, 1.0, buyer_is_maker=False)
    assert s.pos == -1                       # ask filled by the first buy
    assert s.bid_order is not None           # bid unharmed by buy flow
    s.on_book(6_000, 100.0, 100.1)
    assert s.ask_order is None               # still within the 5s calm gate
    s.on_book(20_000, 100.0, 100.1)
    assert s.ask_order == 100.1              # re-quoted after calm


def test_thin_flow_never_trips_toxicity() -> None:
    s = _sim("optimistic", toxicity=0.6)
    s.on_trade(2_000, 100.05, 1.0, buyer_is_maker=True)  # inside spread
    assert s.bid_order == 100.0                           # rests (A1: thin flow)
    s.on_trade(3_000, 100.0, 1.0, buyer_is_maker=True)   # now fills the bid
    assert s.pos == 1


# ------------------------------------------------------------- inventory

def test_opposite_fill_closes_round_trip_both_maker() -> None:
    s = _sim("optimistic")
    s.on_trade(2_000, 100.0, 1.0, buyer_is_maker=True)   # BUY filled at bid
    s.on_trade(3_000, 100.1, 1.0, buyer_is_maker=False)  # SELL filled at ask
    assert s.pos == 0
    rt = s.round_trips[0]
    assert rt["entry_px"] == 100.0 and rt["exit_px"] == 100.1
    # gross 0.1 on ~100.05 notional = ~10bps; fees 2+2=4 -> net ~6bps
    assert rt["net_bps"] == pytest.approx(
        0.1 / 100.05 * 1e4 - 2 * S04.MAKER_FEE_BPS, abs=1e-6)


def test_time_exit_at_touch_is_taker() -> None:
    s = _sim("optimistic")
    s.on_trade(2_000, 100.0, 1.0, buyer_is_maker=True)   # long @100.0
    s.on_mark(62_000, 100.0)                             # 60s hold elapsed
    assert s.pos == 0
    rt = s.round_trips[0]
    assert rt["exit_px"] == s.best_bid == 100.0
    assert rt["fees_bps"] == S04.MAKER_FEE_BPS + S04.TAKER_FEE_BPS
    assert rt["net_bps"] == pytest.approx(-S04.TAKER_FEE_BPS
                                          - S04.MAKER_FEE_BPS, abs=1e-9)


def test_no_directional_carry_beyond_60s() -> None:
    s = _sim("optimistic")
    s.on_trade(2_000, 100.0, 1.0, buyer_is_maker=True)
    for t in (20_000, 40_000, 59_000):
        s.on_mark(t, 100.0)
    assert s.pos == 1  # still holding before 60s
    s.on_mark(62_000, 100.0)
    assert s.pos == 0   # force-exited at 60s


# ------------------------------------------------------------- decision rule

def test_decision_requires_both_models_and_n() -> None:
    base = {"n_fills": 250, "net_mean_bps": 1.0, "net_median_bps": 1.0,
            "markout_5s_mean_bps": -0.2, "markout_5s_n": 250}
    res = {"models": {"optimistic": dict(base),
                      "conservative": dict(base, net_mean_bps=-1.0)}}
    assert S04.decide(res)["verdict"] == "MERITS-CANDIDATE-EVALUATION"
    # conservative worse than -2bp -> NOT-MERITED
    res["models"]["conservative"]["net_mean_bps"] = -3.0
    assert S04.decide(res)["verdict"] == "NOT-MERITED"
    # insufficient fills -> DATA-INSUFFICIENT regardless
    res["models"]["optimistic"]["n_fills"] = 100
    res["models"]["conservative"]["net_mean_bps"] = -1.0
    assert S04.decide(res)["verdict"].startswith("DATA-INSUFFICIENT")


def test_markout_signed_vs_fill_side() -> None:
    s = _sim("optimistic")
    s.on_trade(2_000, 100.0, 1.0, buyer_is_maker=True)  # BUY fill
    s.on_mark(2_100, 100.0)                              # base mark
    s.on_mark(7_100, 100.5)                              # +5s: +50bps up
    mo = s.markout(2_100, "BUY", 5)
    assert mo == pytest.approx(50.0, abs=1e-6)           # favorable for long
    mo_sell = s.markout(2_100, "SELL", 5)
    assert mo_sell == pytest.approx(-50.0, abs=1e-6)     # adverse for short
