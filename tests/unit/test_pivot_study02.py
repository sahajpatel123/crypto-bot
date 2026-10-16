"""STUDY-02 unit tests — pin the preregistered conventions.

reports/pivot/study02-prereg.json is the frozen contract; these tests assert
the tool implements it: funding sign conventions, strict attribution
boundaries, causal entry/exit lookups, one-position overlap skipping, and
missing-data skip (never impute).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import pivot_study_02_carry_swing as S  # noqa: E402


# ------------------------------------------------------------- funding math

def test_funding_sign_convention_short_collects_positive() -> None:
    # positive funding: longs pay shorts -> SHORT collects +rate
    s = [(5_000, 0.0001)]
    assert S.funding_collected(s, 1_000, 9_000, "SHORT") == 0.0001
    assert S.funding_collected(s, 1_000, 9_000, "LONG") == -0.0001


def test_funding_attribution_strictly_inside() -> None:
    s = [(1_000, 0.0001), (2_000, 0.0002), (3_000, -0.0001)]
    # settlement AT entry excluded, AT exit excluded, strictly inside kept
    assert S.funding_collected(s, 1_000, 3_000, "SHORT") == pytest.approx(0.0002)
    assert S.funding_collected(s, 999, 3_000, "SHORT") == pytest.approx(0.0003)
    # exit at 3001: the 3000 settlement is now strictly inside (and negative)
    assert S.funding_collected(s, 1_000, 3_001, "SHORT") == pytest.approx(0.0001)
    assert S.funding_collected(s, 1_000, 1_000, "SHORT") == 0.0


def test_net_bps_charges_rt_once() -> None:
    assert S.net_bps(0.0, 0.0) == pytest.approx(-26.0)
    assert S.net_bps(0.0, 0.0026) == pytest.approx(0.0)
    assert S.net_bps(0.01, 0.0) == pytest.approx(74.0)


# ------------------------------------------------------------- causal lookup

def test_first_close_at_or_after_is_causal_and_exact() -> None:
    times = [60_000, 120_000, 180_000]
    closes = [10.0, 11.0, 12.0]
    assert S.first_close_at_or_after(times, closes, 0) == (60_000, 10.0)
    assert S.first_close_at_or_after(times, closes, 60_000) == (60_000, 10.0)
    assert S.first_close_at_or_after(times, closes, 60_001) == (120_000, 11.0)
    assert S.first_close_at_or_after(times, closes, 10**9) is None


def test_hour_closes_takes_last_trade_of_hour() -> None:
    # minutes 00,01,02 in hour 0; minute 60 alone in hour 1
    times = [60_000, 120_000, 180_000, 120_000 + 3_600_000]
    closes = [1.0, 2.0, 3.0, 4.0]
    ht, hp = S.hour_closes(times, closes)
    assert ht == [3_600_000, 7_200_000]
    assert hp == [3.0, 4.0]


# ------------------------------------------------------------- P2 cells

def _flat_closes(n_minutes: int, start_px: float = 100.0) -> tuple[list[int], list[float]]:
    times = [m * 60_000 + 60_000 for m in range(n_minutes)]
    return times, [start_px] * n_minutes


def test_p2_trigger_and_entry_excludes_trigger_settlement() -> None:
    h = 3_600_000
    # settlements every 8h at +2bps; the hold (entry s+60s -> exit s+8h+60s)
    # collects exactly the NEXT settlement, never the trigger one
    settlements = [(i * 8 * h, 0.0002) for i in range(6)]
    times, closes = _flat_closes(60 * 48)  # 48h of flat 1m closes
    cells = S.p2_cells("TESTUSDT", settlements, times, closes, (0, 48 * h))
    short8 = S.summarize(
        next(c for c in cells if c["side"] == "SHORT" and c["hold_h"] == 8))
    assert short8["n_signals"] >= 1
    assert short8["n_entered"] >= 1
    # flat price -> price component 0; one settlement inside -> +2bps SHORT
    assert short8["price_mean_bps"] == pytest.approx(0.0)
    assert short8["funding_mean_bps"] == pytest.approx(2.0)
    # net = funding - 26
    assert short8["net_mean_bps"] == pytest.approx(2.0 - 26.0)


def test_p2_long_triggers_on_negative_funding() -> None:
    h = 3_600_000
    settlements = [(i * 8 * h, -0.0002) for i in range(6)]
    times, closes = _flat_closes(60 * 48)
    cells = S.p2_cells("TESTUSDT", settlements, times, closes, (0, 48 * h))
    long8 = S.summarize(
        next(c for c in cells if c["side"] == "LONG" and c["hold_h"] == 8))
    assert long8["n_entered"] >= 1
    # LONG collects -rate = +2bps when rate is -2bps
    assert long8["funding_mean_bps"] == pytest.approx(2.0)


def test_p2_overlap_skipped_and_counted() -> None:
    h = 3_600_000
    # dense positive settlements every 2h -> 8h holds overlap
    settlements = [(i * 2 * h, 0.0002) for i in range(30)]
    times, closes = _flat_closes(60 * 24 * 6)
    cells = S.p2_cells("TESTUSDT", settlements, times, closes, (0, 6 * 24 * h))
    short8 = next(c for c in cells if c["side"] == "SHORT" and c["hold_h"] == 8)
    assert short8["n_signals"] > short8["n_entered"]
    assert short8["n_skipped_overlap"] > 0


def test_p2_missing_exit_skips_never_imputes() -> None:
    h = 3_600_000
    settlements = [(i * 8 * h, 0.0002) for i in range(6)]
    # closes end at 26h -> late entries have no exit close
    times, closes = _flat_closes(60 * 26)
    cells = S.p2_cells("TESTUSDT", settlements, times, closes, (0, 48 * h))
    short8 = next(c for c in cells if c["side"] == "SHORT" and c["hold_h"] == 8)
    assert short8["n_skipped_missing"] >= 1
    assert len(short8["gross_bps"]) == short8["n_entered"]


# ------------------------------------------------------------- P3 cells

def test_p3_trigger_long_and_exit_horizon() -> None:
    h = 3_600_000
    # 1h closes rising 2%/24h: trailing-24h return >= 100bps from hour 24
    n = 72
    hcloses = [100.0 * (1 + 0.02 * (i / 24.0)) for i in range(n)]
    htimes = [i * h + h for i in range(n)]
    cells = S.p3_cells("TESTUSDT", [], htimes, hcloses, (0, n * h))
    long4 = S.summarize(
        next(c for c in cells if c["side"] == "LONG" and c["hold_h"] == 4))
    assert long4["n_signals"] >= 1
    assert long4["n_entered"] >= 1
    # price keeps rising over the 4h exit horizon: gross > 0 for LONG
    assert long4["gross_mean_bps"] > 0


def test_p3_missing_lookback_or_exit_skips() -> None:
    h = 3_600_000
    # hour index 10 missing (gap) -> lookback/exit chains break around it
    hcloses = [100.0 + i for i in range(48)]
    htimes = [i * h + h for i in range(48) if i != 10]
    cells = S.p3_cells("TESTUSDT", [], htimes, hcloses, (0, 48 * h))
    for c in cells:
        # every signal is accounted for: entered, overlap-skipped, or
        # missing-skipped — never silently dropped or imputed
        assert (c["n_entered"] + c["n_skipped_overlap"]
                + c["n_skipped_missing"]) == c["n_signals"]


def test_p3_one_position_per_side() -> None:
    h = 3_600_000
    # strong monotonic rise: every hour triggers LONG after warmup
    n = 96
    hcloses = [100.0 * (1 + 0.01 * i) for i in range(n)]
    htimes = [i * h + h for i in range(n)]
    cells = S.p3_cells("TESTUSDT", [], htimes, hcloses, (0, n * h))
    long4 = next(c for c in cells if c["side"] == "LONG" and c["hold_h"] == 4)
    assert long4["n_skipped_overlap"] > 0


# ------------------------------------------------------------- summaries

def test_summarize_empty_cell_is_none_not_zero() -> None:
    cell = {"symbol": "X", "family": "P2", "side": "SHORT", "hold_h": 8,
            "n_signals": 3, "n_entered": 0, "n_skipped_overlap": 1,
            "n_skipped_missing": 2, "gross_bps": [], "funding_bps": [],
            "price_bps": []}
    s = S.summarize(cell)
    assert s["net_mean_bps"] is None
    assert s["hit_rate"] is None


def test_summarize_net_and_hit() -> None:
    cell = {"symbol": "X", "family": "P3", "side": "LONG", "hold_h": 4,
            "n_signals": 2, "n_entered": 2, "n_skipped_overlap": 0,
            "n_skipped_missing": 0, "gross_bps": [30.0, 10.0],
            "funding_bps": [0.0, 0.0], "price_bps": [30.0, 10.0]}
    s = S.summarize(cell)
    # nets are 4 and -16 -> mean 9? no: (4 + -16)/2 = -6; hit 1/2
    assert s["net_mean_bps"] == pytest.approx(-6.0)
    assert s["hit_rate"] == pytest.approx(0.5)


def test_funding_stats_annualization_and_persistence() -> None:
    h = 3_600_000
    # rates rising 1,2,3,... bp: perfectly linear persistence (pearson 1.0)
    settlements = [(i * 8 * h, i * 0.0001) for i in range(1, 11)]
    st = S.funding_stats(settlements, (0, 100 * h))
    assert st["n"] == 10
    assert st["mean_bps_per_8h"] == pytest.approx(5.5)
    assert st["annualized_pct"] == pytest.approx(5.5 * 3 * 365 / 100)
    assert st["funding_per_day_bps"] == pytest.approx(16.5)
    assert st["breakeven_hold_days"] == pytest.approx(26.0 / 16.5)
    assert st["persistence_pearson_trail3_vs_next"] == pytest.approx(1.0)
    assert st["persistence_sign_match"] == pytest.approx(1.0)


def test_funding_stats_zero_variance_persistence_is_none() -> None:
    h = 3_600_000
    settlements = [(i * 8 * h, 0.0001) for i in range(10)]
    st = S.funding_stats(settlements, (0, 100 * h))
    # constant series: pearson undefined -> None, never a fake number
    assert st["persistence_pearson_trail3_vs_next"] is None
    assert st["persistence_sign_match"] == pytest.approx(1.0)


def test_p3_screen_arithmetic_fields() -> None:
    h = 3_600_000
    n = 72
    # period-3 pattern: 4h moves are -100bps or +200bps
    hcloses = [100.0 + (i % 3) for i in range(n)]
    htimes = [i * h + h for i in range(n)]
    rows = S.p3_screen("TESTUSDT", htimes, hcloses, (0, n * h))
    r4 = next(r for r in rows if r["h"] == 4)
    assert r4["n"] > 0
    assert r4["median_abs_move_bps"] == pytest.approx(100.0)
    assert r4["frac_ge_hurdle"] == pytest.approx(1.0)
    assert r4["frac_ge_target80"] == pytest.approx(1.0)
