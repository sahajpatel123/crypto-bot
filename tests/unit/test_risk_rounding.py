"""V-008 §7: the one shared venue-rounding rule."""
import math

import pytest

from cryptobot.risk.rounding import floor_to_step


def test_exact_multiples_stay_exact():
    assert floor_to_step(0.3, 0.1) == 0.3
    assert floor_to_step(1.0, 0.001) == 1.0
    assert floor_to_step(2.35, 0.01) == 2.35


def test_floors_down_to_step():
    assert floor_to_step(0.0019, 0.001) == 0.001
    assert floor_to_step(2.359, 0.01) == 2.35


def test_dust_below_one_step_returns_zero():
    assert floor_to_step(0.0009, 0.001) == 0.0
    assert floor_to_step(0.0, 0.001) == 0.0
    assert floor_to_step(-1.5, 0.001) == 0.0


def test_idempotent_across_sweep():
    qtys = [0.0009, 0.001, 0.0019, 0.01, 0.1, 0.3, 1.0, 2.359,
            100.0, 1234.5678]
    for step in (0.001, 0.01, 0.1):
        for qty in qtys:
            once = floor_to_step(qty, step)
            assert floor_to_step(once, step) == once


def test_invalid_step_raises():
    for bad in (0.0, -0.001, math.nan, math.inf, "0.001", True):
        with pytest.raises(ValueError):
            floor_to_step(1.0, bad)


def test_nonfinite_qty_raises():
    for bad in (math.nan, math.inf, "1.0"):
        with pytest.raises(ValueError):
            floor_to_step(bad, 0.001)


def test_round_to_tick_nearest():
    from cryptobot.risk.rounding import round_to_tick
    assert round_to_tick(59990.03, 0.1) == 59990.0
    assert round_to_tick(60000.53, 0.1) == 60000.5
    assert round_to_tick(100.0, 0.1) == 100.0


def test_round_to_tick_invalid_raises():
    import math
    from cryptobot.risk.rounding import round_to_tick
    for bad_tick in (0.0, -0.1, math.nan, math.inf):
        with pytest.raises(ValueError):
            round_to_tick(100.0, bad_tick)
    for bad_px in (0.0, -1.0, math.nan, math.inf):
        with pytest.raises(ValueError):
            round_to_tick(bad_px, 0.1)
