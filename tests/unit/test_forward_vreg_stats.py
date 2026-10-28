"""V-REG statistics tests: DSR N=6 rule, bespoke PBO, plateau.

The PBO test below is the prereg-mandated hand-worked example: every
number is derived by hand in the comments, and the test must fail if the
bespoke procedure is replaced by slow_stats.pbo_cscv (proven by the
replacement test on a discriminating fixture).
"""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("pandas")

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "forward_vreg_stats", str(ROOT / "tools" / "forward_vreg.py"))
fwd = importlib.util.module_from_spec(_spec)
sys.modules["forward_vreg_stats"] = fwd  # dataclasses need it registered
_spec.loader.exec_module(fwd)

sys.path.insert(0, str(ROOT / "src"))
from cryptobot.research import slow_stats as ST  # noqa: E402

CELLS6 = [(1.5, 2), (1.5, 5), (2.0, 2), (2.0, 5), (2.5, 2), (2.5, 5)]


def _series(seed, n=120, mean=0.001, sd=0.01):
    rng = np.random.RandomState(seed)
    return list(rng.normal(mean, sd, n))


def _trials(seed, k=6):
    rng = np.random.RandomState(seed)
    return list(rng.normal(0.5, 1.0, k))


@pytest.mark.parametrize("seed", [1, 7, 42])
def test_dsr_explicit_matches_dsr_detail(seed):
    r = _series(seed)
    v = _trials(seed)
    got = fwd._dsr_with_n(r, v, len(v), hold_days=12.0)
    want = ST.dsr_detail(r, v, hold_days=12.0)
    for key in ("n", "n_eff", "acf1", "sr", "sr_ann", "expected_max",
                "inner", "skew", "kurt", "n_trials", "dsr"):
        assert got[key] == pytest.approx(want[key], rel=1e-12), key
    assert got["n_for_q"] == len(v)


def test_dsr_n_is_six_not_sixteen():
    assert fwd.N_DSR == 6
    r = _series(3, n=200, mean=0.002, sd=0.01)
    v6 = _trials(3)
    got = fwd._dsr_with_n(r, v6, 6, hold_days=10.0)
    assert got["n_for_q"] == 6
    assert got["n_trials"] == 6
    sixteen = fwd._dsr_with_n(r, v6, 16, hold_days=10.0)["dsr"]
    assert sixteen <= got["dsr"]


def test_dsr_sensitivities_construction():
    r = _series(5, n=150, mean=0.0015, sd=0.012)
    v6 = _trials(5)
    n6 = fwd._dsr_with_n(r, v6, 6, hold_days=8.0)["dsr"]
    n12 = fwd._dsr_with_n(r, v6, 12, hold_days=8.0)["dsr"]
    n25 = fwd._dsr_with_n(r, v6, 25, hold_days=8.0)["dsr"]
    assert n25 <= n12 <= n6


def _hand_cells():
    means = [6e-4, 5e-4, 4e-4, 3e-4, 2e-4, 1e-4]
    out = {}
    for c, m in zip(CELLS6, means, strict=True):
        out[c] = [m + (1e-4 if i % 2 == 0 else -1e-4) for i in range(16)]
    return out


def test_pbo_bespoke_hand_worked_example():
    data = _hand_cells()
    got = fwd._pbo_bespoke(data)
    assert got["edges"] == [0, 2, 4, 6, 8, 10, 12, 14, 16]
    assert got["n_splits"] == 70
    assert set(got["best_keys"]) == {(1.5, 2)}
    assert got["lambdas"] == [1.0] * 70
    assert got["pbo"] == 0.0
    expect_best = 6e-4 / (math.sqrt(8.0 / 7.0) * 1e-4) * math.sqrt(365)
    got_sr = ST.sharpe([data[(1.5, 2)][i] for i in range(8)], 365)
    assert got_sr == pytest.approx(expect_best, rel=1e-12)
    got_second = ST.sharpe([data[(1.5, 5)][i] for i in range(8)], 365)
    assert got_second < got_sr
    idx = [0, 1, 4, 5, 8, 9, 12, 13]
    srs = {c: ST.sharpe([data[c][i] for i in idx], 365) for c in CELLS6}
    assert max(srs, key=lambda c: srs[c]) == (1.5, 2)


def test_pbo_array_split_remainder_to_earliest():
    data = {c: [1e-4] * 100 for c in CELLS6}
    got = fwd._pbo_bespoke(data)
    sizes = [b - a for a, b in zip(got["edges"], got["edges"][1:], strict=False)]
    assert sizes == [13, 13, 13, 13, 12, 12, 12, 12]
    assert got["pbo"] == 1.0


def test_pbo_all_tied_gives_zero_lambda():
    data = {c: [2e-4 + (1e-5 if i % 2 else -1e-5) for i in range(16)]
            for c in CELLS6}
    got = fwd._pbo_bespoke(data)
    assert got["lambdas"] == [0.0] * 70
    assert got["pbo"] == 1.0


def test_pbo_refuses_short_ragged_nonfinite():
    good = _hand_cells()
    short = {c: v[:7] for c, v in good.items()}
    with pytest.raises(ValueError, match=">= 8 days"):
        fwd._pbo_bespoke(short)
    ragged = dict(good)
    ragged[CELLS6[0]] = ragged[CELLS6[0]][:-1]
    with pytest.raises(ValueError, match="equal-length"):
        fwd._pbo_bespoke(ragged)
    bad = dict(good)
    bad[CELLS6[0]] = list(bad[CELLS6[0]])
    bad[CELLS6[0]][3] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        fwd._pbo_bespoke(bad)
    five = {c: v for c, v in good.items() if c != CELLS6[-1]}
    with pytest.raises(ValueError, match="6 frozen cells"):
        fwd._pbo_bespoke(five)


def test_pbo_bespoke_differs_from_pbo_cscv():
    rng = np.random.RandomState(11)
    data = {}
    for j, c in enumerate(CELLS6):
        base = [3e-4, 3e-4, 1e-4, 1e-4, 0.0, 0.0][j]
        data[c] = [base + float(rng.normal(0, 4e-4)) for _ in range(20)]
    bespoke = fwd._pbo_bespoke(data)["pbo"]
    lib = ST.pbo_cscv([data[c] for c in CELLS6])
    assert bespoke == pytest.approx(0.1)
    assert bespoke != pytest.approx(lib, rel=1e-9)
    assert 0.0 <= bespoke <= 1.0


def test_plateau_on_tuple_keys_with_lexicographic_tiebreak():
    sharpes = {(1.5, 2): 2.0, (2.0, 2): 1.0, (2.5, 2): -1.0,
               (1.5, 5): 0.5, (2.0, 5): -2.0, (2.5, 5): -3.0}
    got = fwd._plateau_detail(sharpes)
    assert got["value"] == pytest.approx(2.0 / 3.0)
    assert got["best"] == "R=1.5/H=2"
    assert sorted(got["neighbours"]) == ["R=1.5/H=5", "R=2.5/H=2", "R=2/H=2"]
    assert got["positive_neighbours"] == 2
    tied = dict(sharpes)
    tied[(2.5, 5)] = 2.0
    got2 = fwd._plateau_detail(tied)
    assert got2["best"] == "R=1.5/H=2"


def test_plateau_refuses_nonfinite():
    bad = {(1.5, 2): 2.0, (2.0, 2): 1.0, (2.5, 2): float("nan"),
           (1.5, 5): 0.5, (2.0, 5): -2.0, (2.5, 5): -3.0}
    with pytest.raises(ValueError, match="non-finite"):
        fwd._plateau_detail(bad)
