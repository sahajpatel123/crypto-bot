"""Causal feature tests (Worker 1, Q-001)."""
import sys
from pathlib import Path
from statistics import mean, pstdev

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.features.breakout import (
    InsufficientHistory,
    MissingData,
    flow_mean,
    momentum_bps,
    ref_high,
    ref_low,
    swing_high,
    swing_low,
    volume_z,
)
from cryptobot.features.pullback import (
    pullback_high,
    pullback_low,
    resume_max,
    resume_min,
    swing_high_before,
    swing_low_before,
)


def test_ref_windows_exclude_trigger_bar():
    highs = [10.0] * 200
    highs[150] = 999.0
    assert ref_high(highs, 150) == 10.0
    assert ref_high(highs, 151) == 999.0
    lows = [10.0] * 200
    lows[150] = 1.0
    assert ref_low(lows, 150) == 10.0
    assert ref_low(lows, 151) == 1.0
    assert swing_high(highs, 151, 30) == 999.0
    assert swing_low(lows, 151, 30) == 1.0


def test_ref_rejects_short_or_gapped_history():
    with pytest.raises(InsufficientHistory):
        ref_high([1.0] * 50, 40, 120)
    vals: list = [1.0] * 200
    vals[100] = None
    with pytest.raises(MissingData) as exc:
        ref_high(vals, 150, 120)
    assert exc.value.index == 100


def test_momentum_bps_math_and_guards():
    closes = [100.0] * 200
    closes[100] = 101.0
    assert momentum_bps(closes, 100, 30) == pytest.approx(100.0)
    closes[101] = 99.0
    assert momentum_bps(closes, 101, 30) == pytest.approx(-100.0)
    bad = [100.0] * 200
    bad[70] = 0.0
    with pytest.raises(ValueError):
        momentum_bps(bad, 100, 30)
    with pytest.raises(InsufficientHistory):
        momentum_bps([100.0] * 10, 5, 30)


def test_volume_z_matches_statistics_and_flat_rule():
    vols = [float(i) for i in range(60)] + [100.0]
    assert volume_z(vols, 60, 60) == pytest.approx(
        (100.0 - mean(vols[:60])) / pstdev(vols[:60])
    )
    flat = [100.0] * 61
    assert volume_z(flat, 60, 60) == 0.0  # trigger at mean -> 0
    spike = [100.0] * 60 + [101.0]
    assert volume_z(spike, 60, 60) == float("inf")  # any uptick off flat tape


def test_flow_mean_inclusive_window_and_bounds():
    fracs = [0.0] * 200
    fracs[150] = 1.0
    assert flow_mean(fracs, 150, 10) == pytest.approx(0.1)
    bad = [0.5] * 200
    bad[150] = 1.5
    with pytest.raises(ValueError):
        flow_mean(bad, 150, 10)


def test_pullback_primitives_windows_and_indices():
    highs = [10.0] * 200
    highs[100] = 12.0
    level, idx = swing_high_before(highs, 150, 60)
    assert (level, idx) == (12.0, 100)
    lows = [10.0] * 200
    lows[145] = 9.0
    assert pullback_low(lows, 149, 10) == 9.0
    assert pullback_low(lows, 144, 10) == 10.0  # window excludes 145
    assert pullback_high(highs, 149, 10) == 10.0
    closes = [float(i) for i in range(200)]
    assert resume_max(closes, 150, 5) == 149.0
    assert resume_min(closes, 150, 5) == 145.0
    level, idx = swing_low_before(lows, 150, 60)
    assert (level, idx) == (9.0, 145)
    with pytest.raises(InsufficientHistory):
        resume_max(closes, 3, 5)


def test_features_causal_future_perturbation_invariant():
    highs = [100.0 + (i % 7) for i in range(200)]
    lows = [h - 1.0 for h in highs]
    closes = [100.0 + (i % 5) * 0.1 for i in range(200)]
    vols = [100.0 + (i % 3) for i in range(200)]
    fracs = [0.5] * 200
    before = (
        ref_high(highs, 150), ref_low(lows, 150),
        momentum_bps(closes, 150), volume_z(vols, 150), flow_mean(fracs, 150),
    )
    for i in range(151, 200):  # corrupt only the future
        highs[i] = 1e9
        lows[i] = -1e9
        closes[i] = 1e9
        vols[i] = 1e12
        fracs[i] = 1.0
    after = (
        ref_high(highs, 150), ref_low(lows, 150),
        momentum_bps(closes, 150), volume_z(vols, 150), flow_mean(fracs, 150),
    )
    assert before == after
