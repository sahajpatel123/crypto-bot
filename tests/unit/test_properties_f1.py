"""F1.1: property-based invariants for money-critical helpers.

Fast Hypothesis profiles only (<2s). These complement the deterministic
regression suites; they do not replace them.
"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from cryptobot.execution.fill_realism import PaperFillParameters
from cryptobot.risk.margin import (
    bracket_admission_check,
    maintenance_margin,
)
from cryptobot.risk.rounding import ceil_to_tick, floor_to_step, floor_to_tick

BRACKETS = [
    {"notionalCap": 50_000.0, "maintMarginRatio": 0.004, "cum": 0.0},
    {"notionalCap": 250_000.0, "maintMarginRatio": 0.005, "cum": 50.0},
]

pos = st.floats(min_value=1e-9, max_value=1e6, allow_nan=False,
                allow_infinity=False)
step = st.floats(min_value=1e-8, max_value=10.0, allow_nan=False,
                 allow_infinity=False)


@settings(max_examples=100, deadline=None)
@given(pos, step)
def test_rounding_never_increases_risk(value, size):
    assert floor_to_step(value, size) <= value + 1e-12
    assert floor_to_tick(value, size) <= value + 1e-12
    assert ceil_to_tick(value, size) >= value - 1e-12


@settings(max_examples=100, deadline=None)
@given(st.floats(min_value=0.0, max_value=1e7, allow_nan=False,
                 allow_infinity=False))
def test_maintenance_margin_monotonic_and_nonnegative(notional):
    mm = maintenance_margin(notional, BRACKETS)
    assert mm >= 0.0
    if notional < 250_000:
        assert maintenance_margin(notional + 1.0, BRACKETS) >= mm - 1e-9


@settings(max_examples=80, deadline=None)
@given(
    st.floats(min_value=10.0, max_value=1000.0, allow_nan=False,
              allow_infinity=False),
    st.floats(min_value=0.001, max_value=100.0, allow_nan=False,
              allow_infinity=False),
    st.floats(min_value=1.0, max_value=100.0, allow_nan=False,
              allow_infinity=False),
    st.floats(min_value=0.5, max_value=99.0, allow_nan=False,
              allow_infinity=False),
)
def test_liquidation_distance_monotonic_in_leverage(entry, qty, lev, stop_pct):
    stop = entry * (1.0 - stop_pct / 100.0)
    liqs = []
    for lv in (lev, lev * 2.0):
        r = bracket_admission_check(
            entry=entry, stop=stop, qty=qty, side="LONG", leverage=lv,
            brackets=BRACKETS, observed_ms=1_000, now_ms=1_000,
            stressed_slippage_bps=50.0)
        if "liquidation_price" in r:
            liqs.append(r["liquidation_price"])
    if len(liqs) == 2:
        assert liqs[1] >= liqs[0] - 1e-9


@settings(max_examples=60, deadline=None)
@given(
    st.floats(min_value=0.0, max_value=50.0, allow_nan=False),
    st.floats(min_value=0.0, max_value=5000.0, allow_nan=False),
    st.floats(min_value=1.0, max_value=20.0, allow_nan=False),
)
def test_fill_parameter_adverse_cost_monotonic(spread, latency, depth):
    a = PaperFillParameters(tick_size_bps=1.0, spread_bps=spread,
                            latency_ms=latency, depth_multiple=depth)
    b = PaperFillParameters(tick_size_bps=1.0, spread_bps=spread + 1.0,
                            latency_ms=latency, depth_multiple=depth)
    assert b.adverse_bps >= a.adverse_bps - 1e-9
    assert 1.0 <= a.expected_ticks <= a.cap_ticks
