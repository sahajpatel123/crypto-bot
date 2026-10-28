"""F-CARRY statistics tests: DSR N=16 rule, bespoke PBO, plateau.

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
    "forward_fcarry_stats", str(ROOT / "tools" / "forward_fcarry.py"))
fwd = importlib.util.module_from_spec(_spec)
sys.modules["forward_fcarry_stats"] = fwd  # dataclasses need it registered
_spec.loader.exec_module(fwd)

sys.path.insert(0, str(ROOT / "src"))
from cryptobot.research import slow_stats as ST  # noqa: E402

CELLS6 = [(1.0, "BTC"), (1.0, "ETH"), (1.0, "BOTH"),
          (1.25, "BTC"), (1.25, "ETH"), (1.25, "BOTH")]


# -- DSR explicit-N ---------------------------------------------------------------
def _series(seed, n=120, mean=0.001, sd=0.01):
    rng = np.random.RandomState(seed)
    return list(rng.normal(mean, sd, n))


def _trials(seed, k=15):
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


def test_missing_b4b_rule_is_conservative():
    # q(16) > q(15): the missing rule deflates MORE than naive N=15.
    r = _series(3, n=200, mean=0.002, sd=0.01)
    v15 = _trials(3)
    missing = fwd._dsr_with_n(r, v15, 16, hold_days=10.0)["dsr"]
    naive = ST.dsr_detail(r, v15, hold_days=10.0)["dsr"]
    assert missing <= naive
    assert missing < 1.0


def test_dsr_sensitivities_construction():
    r = _series(5, n=150, mean=0.0015, sd=0.012)
    v15 = _trials(5)
    n15 = fwd._dsr_with_n(r, v15, 15, hold_days=8.0)["dsr"]
    n25 = fwd._dsr_with_n(r, v15, 25, hold_days=8.0)["dsr"]
    assert n25 <= n15  # harsher trial penalty deflates more
    manual = ST.dsr_detail(r, v15 + [min(v15)], hold_days=8.0)
    assert manual["n_trials"] == 16
    assert manual["dsr"] <= ST.dsr_detail(r, v15, hold_days=8.0)["dsr"]


# -- bespoke PBO: hand-worked example ----------------------------------------------
def _hand_cells():
    # n = 16 days. Cell c has daily return m_c + (-1)^i with
    # m = [6, 5, 4, 3, 2, 1] (x1e-4; scale cancels in every ranking).
    means = [6e-4, 5e-4, 4e-4, 3e-4, 2e-4, 1e-4]
    out = {}
    for c, m in zip(CELLS6, means, strict=True):
        out[c] = [m + (1e-4 if i % 2 == 0 else -1e-4) for i in range(16)]
    return out


def test_pbo_bespoke_hand_worked_example():
    data = _hand_cells()
    got = fwd._pbo_bespoke(data)
    # Edges: n=16 over 8 partitions -> eight blocks of exactly 2 days.
    assert got["edges"] == [0, 2, 4, 6, 8, 10, 12, 14, 16]
    assert got["n_splits"] == 70
    # Every partition holds one even + one odd day, so EVERY 4-partition
    # IS set has 4 days at (m+1e-4) and 4 at (m-1e-4): mean m, sd
    # sqrt(8/7)*1e-4 (ddof=1: variance = 8*(1e-4)^2/7). Sharpe is
    # strictly ordered by m in every split; IS-best is always (1.0,'BTC').
    assert set(got["best_keys"]) == {(1.0, "BTC")}
    # Same arithmetic OOS: cell (1.0,'BTC') ranks first with 5 strictly
    # lower competitors -> lambda = 1.0 in all 70 splits -> PBO = 0.0.
    assert got["lambdas"] == [1.0] * 70
    assert got["pbo"] == 0.0
    # Two fully worked splits, exact Sharpe arithmetic:
    # IS days {0..7}: mean 6e-4 / sd (sqrt(8/7)*1e-4) * sqrt(365).
    expect_best = 6e-4 / (math.sqrt(8.0 / 7.0) * 1e-4) * math.sqrt(365)
    got_sr = ST.sharpe([data[(1.0, "BTC")][i] for i in range(8)], 365)
    assert got_sr == pytest.approx(expect_best, rel=1e-12)
    # Second-best cell is strictly below on the same days.
    got_second = ST.sharpe([data[(1.0, "ETH")][i] for i in range(8)], 365)
    assert got_second < got_sr
    # The other worked split: IS partitions {0,2,4,6} = days
    # {0,1,4,5,8,9,12,13}: same 4/4 parity mix, same conclusion.
    idx = [0, 1, 4, 5, 8, 9, 12, 13]
    srs = {c: ST.sharpe([data[c][i] for i in idx], 365) for c in CELLS6}
    assert max(srs, key=lambda c: srs[c]) == (1.0, "BTC")


def test_pbo_array_split_remainder_to_earliest():
    # The prereg's own example: n=100 -> [13,13,13,13,12,12,12,12].
    data = {c: [1e-4] * 100 for c in CELLS6}
    got = fwd._pbo_bespoke(data)
    sizes = [b - a for a, b in zip(got["edges"], got["edges"][1:], strict=False)]
    assert sizes == [13, 13, 13, 13, 12, 12, 12, 12]
    # Constant series: every Sharpe is 0.0, every split all-tied.
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


def test_pbo_bespoke_differs_from_pbo_cscv():
    # Discriminating fixture: n=20 (edges differ from i*n//s) with a
    # tied top pair, so the tie rules also discriminate. If the bespoke
    # procedure were replaced by pbo_cscv, this test fails.
    rng = np.random.RandomState(11)
    data = {}
    for j, c in enumerate(CELLS6):
        base = [3e-4, 3e-4, 1e-4, 1e-4, 0.0, 0.0][j]
        data[c] = [base + float(rng.normal(0, 4e-4)) for _ in range(20)]
    bespoke = fwd._pbo_bespoke(data)["pbo"]
    lib = ST.pbo_cscv([data[c] for c in CELLS6])
    assert bespoke == pytest.approx(0.1)  # pinned: 7 of 70 splits
    assert bespoke != pytest.approx(lib, rel=1e-9)
    # And the bespoke value is pinned: 70 deterministic splits.
    assert 0.0 <= bespoke <= 1.0


# -- plateau -------------------------------------------------------------------------
def test_plateau_on_tuple_keys_with_lexicographic_tiebreak():
    # Best (1.0,'BTC'): Hamming-1 neighbours are (1.25,'BTC'),
    # (1.0,'ETH'), (1.0,'BOTH'); 2 of 3 positive -> 2/3.
    sharpes = {(1.0, "BTC"): 2.0, (1.25, "BTC"): 1.0,
               (1.0, "ETH"): -1.0, (1.0, "BOTH"): 0.5,
               (1.25, "ETH"): -2.0, (1.25, "BOTH"): -3.0}
    got = fwd._plateau_detail(sharpes)
    assert got["value"] == pytest.approx(2.0 / 3.0)
    assert got["best"] == "k=1/BTC"
    assert sorted(got["neighbours"]) == ["k=1.25/BTC", "k=1/BOTH", "k=1/ETH"]
    assert got["positive_neighbours"] == 2
    # Exact tie for best: lexicographically smallest wins.
    tied = dict(sharpes)
    tied[(1.25, "ETH")] = 2.0
    got2 = fwd._plateau_detail(tied)
    assert got2["best"] == "k=1/BTC"


def test_plateau_refuses_nonfinite():
    bad = {(1.0, "BTC"): 2.0, (1.25, "BTC"): 1.0,
           (1.0, "ETH"): float("nan"), (1.0, "BOTH"): 0.5,
           (1.25, "ETH"): -2.0, (1.25, "BOTH"): -3.0}
    with pytest.raises(ValueError, match="non-finite"):
        fwd._plateau_detail(bad)
