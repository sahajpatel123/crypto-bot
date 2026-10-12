"""Funding-backfill unit tests (W2, 24H). Fixture payloads only, no network."""
import zipfile

import pytest


def _backfill():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path("datasets").resolve()))
    import backfill_funding
    return backfill_funding


def _rest_row(funding_ms, rate="0.0001"):
    return {"symbol": "BTCUSDT", "fundingTime": funding_ms,
            "fundingRate": rate, "markPrice": "90000.0"}


def test_latency_range_measured_not_assumed():
    bf = _backfill()
    step = 8 * 3_600_000
    rest = [_rest_row(1_000_000_000_000), _rest_row(1_000_000_000_000 + step)]
    vision = [(1_000_000_000_005, 8, "0.0001"),
              (1_000_000_000_000 + step + 2, 8, "0.0001")]
    assert bf.vision_latency_range_ms(rest, vision) == (2, 5)
    with pytest.raises(ValueError, match="matches 0 REST settlements"):
        bf.vision_latency_range_ms(rest, [(9_000_000_000_005, 8, "0.0001")])


def test_reconcile_exact_or_loud():
    bf = _backfill()
    rest = [_rest_row(1_000_000, "0.00008482")]
    vision = [(1_000_005, 8, "0.00008482")]
    rec = bf.reconcile_month(rest, vision)
    assert rec["mismatches"] == []
    rec = bf.reconcile_month(rest, [(1_000_005, 8, "0.0001")])
    assert len(rec["mismatches"]) == 1 and "rate mismatch" in rec["mismatches"][0]
    rec = bf.reconcile_month(rest, vision + [(2_000_005, 8, "0.0001")])
    assert any("matches 0 REST" in m for m in rec["mismatches"])
    rec = bf.reconcile_month(rest + [_rest_row(2_000_000)], vision)
    assert any("missing from vision" in m for m in rec["mismatches"])


def test_month_zip_guards_month_boundaries(tmp_path):
    bf = _backfill()
    # 2026-10-01T00:00:00Z and 2026-09-30T16:00:00Z settlements.
    oct_row = _rest_row(1_790_812_800_000)
    sep_row = _rest_row(1_790_784_000_000)
    assert bf.month_of(1_790_812_800_000) == "2026-10"
    dest = tmp_path / "BTCUSDT" / "funding" / "BTCUSDT-fundingRate-2026-10.zip"
    n, sha = bf.write_month_zip(dest, "BTCUSDT", "2026-10", [oct_row], 8)
    assert n == 1 and len(sha) == 64
    with zipfile.ZipFile(dest) as zf:
        text = zf.read("BTCUSDT-fundingRate-2026-10.csv").decode()
    assert text.splitlines() == [
        "calc_time,funding_interval_hours,last_funding_rate",
        "1790812800000,8,0.0001"]
    with pytest.raises(ValueError, match="outside 2026-10"):
        bf.write_month_zip(dest, "BTCUSDT", "2026-10", [sep_row], 8)


def test_coverage_verification_flags_gaps():
    bf = _backfill()
    step = 8 * 3_600_000
    rows = [_rest_row(1_000_000), _rest_row(1_000_000 + step),
            _rest_row(1_000_000 + 2 * step)]
    assert bf._verify_coverage("BTCUSDT", rows, 1_000_000,
                               1_000_000 + 2 * step, 8,
                               now_ms=1_000_000 + 2 * step) == []
    gapped = [_rest_row(1_000_000), _rest_row(1_000_000 + 3 * step)]
    gaps = bf._verify_coverage("BTCUSDT", gapped, 1_000_000,
                               1_000_000 + 3 * step, 8,
                               now_ms=1_000_000 + 3 * step)
    assert len(gaps) == 1 and "gap" in gaps[0]
    assert bf._verify_coverage("BTCUSDT", [], 0, 1, 8) != []


def test_coverage_trailing_edge_clamps_to_now():
    bf = _backfill()
    step = 8 * 3_600_000
    # Last settlement 3h ago; range end is tomorrow: elapsed time is
    # covered, the future is (correctly) not demanded.
    rows = [_rest_row(1_000_000), _rest_row(1_000_000 + step)]
    assert bf._verify_coverage("BTCUSDT", rows, 1_000_000,
                               1_000_000 + 10 * step, 8,
                               now_ms=1_000_000 + step + 3 * 3_600_000) == []
