"""E1.3: lake parquet store, hash manifest, DQ report (synthetic fixtures)."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("pandas")
pytest.importorskip("pyarrow")


def _kline_rows(symbol_days):
    rows = []
    base_ms = 1704067200000  # 2024-01-01T00:00Z
    for sym, days in symbol_days:
        for d in days:
            o = base_ms + d * 86400000
            rows.append((sym, f"{o},100,101,99,100.5,10,{o + 86399999},"
                             f"1005,5,5,502.5,0"))
    return rows


def _write_zip(path: Path, name: str, lines: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, "\n".join(lines) + "\n")
    return path


def _dev_tree(tmp_path: Path) -> Path:
    raw = tmp_path / "raw"
    rows = _kline_rows([("BTCUSDT", [0, 1, 2, 4]), ("ETHUSDT", [0, 1, 2, 3])])
    by_sym: dict[str, list[str]] = {}
    for sym, line in rows:
        by_sym.setdefault(sym, []).append(line)
    # BTC day 3 missing (gap); ETH duplicated day 1; BTC day 4 wick added later.
    by_sym["ETHUSDT"].append(by_sym["ETHUSDT"][1])
    for sym, lines in by_sym.items():
        _write_zip(raw / "klines" / "1d" / sym / f"{sym}-1d-2023-12.zip",
                   f"{sym}-1d-2023-12.csv", lines)
    _write_zip(raw / "fundingRate" / "na" / "BTCUSDT"
               / "BTCUSDT-fundingRate-2023-12.zip",
               "BTCUSDT-fundingRate-2023-12.csv",
               ["calc_time,funding_interval_hours,last_funding_rate",
                "1701388800000,8,0.00010000",
                "1701417600000,8,-0.00005000"])
    return raw


def test_read_klines_normalizes_units_sorts_dedupes(tmp_path):
    from cryptobot.research.lake import read_klines_zip

    raw = _dev_tree(tmp_path)
    eth = read_klines_zip(
        raw / "klines" / "1d" / "ETHUSDT" / "ETHUSDT-1d-2023-12.zip")
    assert len(eth) == 4  # dupe removed
    assert eth["open_time"].is_monotonic_increasing
    assert str(eth["open_time"].dt.tz) == "UTC"
    # Seconds-unit input is detected and normalized to ms/UTC.
    sec = tmp_path / "sec.zip"
    _write_zip(sec, "s.csv", ["1704067200,100,101,99,100.5,10,"
                              "1704153599,1005,5,5,502.5,0"])
    df = read_klines_zip(sec)
    assert df["open_time"].iloc[0].isoformat() == "2024-01-01T00:00:00+00:00"
    usec = tmp_path / "usec.zip"
    _write_zip(usec, "u.csv", ["1704067200000000,100,101,99,100.5,10,"
                               "1704153599000000,1005,5,5,502.5,0"])
    dfu = read_klines_zip(usec)
    assert dfu["open_time"].iloc[0].isoformat() == "2024-01-01T00:00:00+00:00"
    bad = tmp_path / "bad.zip"
    _write_zip(bad, "b.csv", ["999,100,101,99,100.5,10,"
                              "999,1005,5,5,502.5,0"])
    with pytest.raises(ValueError, match="timestamp unit"):
        read_klines_zip(bad)


def test_build_lake_writes_partitioned_parquet_and_chained_manifest(tmp_path):
    from cryptobot.research.lake import build_lake, verify_lake_manifest

    raw = _dev_tree(tmp_path)
    manifest = build_lake(raw, tmp_path / "lake")
    assert (tmp_path / "lake" / "klines" / "interval=1d"
            / "symbol=BTCUSDT" / "data.parquet").exists()
    assert (tmp_path / "lake" / "funding" / "symbol=BTCUSDT"
            / "data.parquet").exists()
    assert manifest["provenance"] == "OBSERVED_PUBLIC"
    assert manifest["schema_version"] == 1
    assert verify_lake_manifest(tmp_path / "lake")["ok"] is True
    # Tamper with a parquet file -> manifest verification fails.
    pq = tmp_path / "lake" / "klines" / "interval=1d" / "symbol=BTCUSDT" / "data.parquet"
    with open(pq, "ab") as fh:
        fh.write(b"tamper")
    assert verify_lake_manifest(tmp_path / "lake")["ok"] is False


def test_dq_report_finds_gap_dupe_and_wick(tmp_path):
    from cryptobot.research.lake import data_quality_report, read_klines_zip

    raw = _dev_tree(tmp_path)
    # Add a flash-wick bar to BTC (range 60% of close).
    wick = (raw / "klines" / "1d" / "BTCUSDT"
            / "BTCUSDT-1d-2023-12.zip")
    btc = read_klines_zip(wick)
    import pandas as pd
    extra = pd.DataFrame([{
        "open_time": pd.Timestamp("2023-12-06T00:00Z"),
        "open": 100.0, "high": 130.0, "low": 70.0, "close": 100.5,
        "volume": 10.0, "close_time": pd.Timestamp("2023-12-06T23:59:59Z"),
        "quote_volume": 1005.0, "trades": 5, "taker_buy_base": 5.0,
        "taker_buy_quote": 502.5, "ignore": 0}])
    frames = {"BTCUSDT": pd.concat([btc, extra], ignore_index=True),
              "ETHUSDT": read_klines_zip(
                  raw / "klines" / "1d" / "ETHUSDT" / "ETHUSDT-1d-2023-12.zip")}
    rep = data_quality_report(frames, interval="1d")
    assert rep["BTCUSDT"]["gaps"] >= 1  # day 3 missing
    assert rep["BTCUSDT"]["outliers"] >= 1  # the wick
    assert rep["ETHUSDT"]["dupes_removed"] >= 0
    assert rep["BTCUSDT"]["rows"] == 5
    assert "first" in rep["BTCUSDT"] and "last" in rep["BTCUSDT"]


def test_load_dev_frames_reads_lake(tmp_path):
    from cryptobot.research.lake import build_lake, load_dev_frames

    raw = _dev_tree(tmp_path)
    build_lake(raw, tmp_path / "lake")
    frames = load_dev_frames(tmp_path / "lake", "klines", ["BTCUSDT"],
                             interval="1d")
    assert list(frames) == ["BTCUSDT"]
    assert len(frames["BTCUSDT"]) == 4
    funding = load_dev_frames(tmp_path / "lake", "funding", ["BTCUSDT"])
    assert len(funding["BTCUSDT"]) == 2
    assert set(funding["BTCUSDT"].columns) >= {
        "calc_time", "funding_interval_hours", "last_funding_rate"}


def test_read_klines_accepts_header_or_not(tmp_path):
    from cryptobot.research.lake import read_klines_zip

    row = ("1700611200000,0.00478,0.004825,0.004076,0.004531,12700997933,"
           "1700697599999,56367827.49,320715,6184933232,27467335.12,0")
    hdr = ("open_time,open,high,low,close,volume,close_time,quote_volume,"
           "count,taker_buy_volume,taker_buy_quote_volume,ignore")
    _write_zip(tmp_path / "h.zip", "h.csv", [hdr, row])
    _write_zip(tmp_path / "n.zip", "n.csv", [row])
    a = read_klines_zip(tmp_path / "h.zip")
    b = read_klines_zip(tmp_path / "n.zip")
    assert len(a) == len(b) == 1
    assert a["close"].iloc[0] == b["close"].iloc[0] == 0.004531


def test_build_lake_workers_and_symbol_filter_match(tmp_path):
    from cryptobot.research.lake import build_lake, verify_lake_manifest

    raw = _dev_tree(tmp_path)
    m1 = build_lake(raw, tmp_path / "lake1", workers=4)
    m2 = build_lake(raw, tmp_path / "lake2", workers=1,
                    symbols=["BTCUSDT"])
    paths1 = sorted(e["path"] for e in m1["entries"])
    paths2 = sorted(e["path"] for e in m2["entries"])
    assert all("BTCUSDT" in p for p in paths2)
    assert len(paths2) < len(paths1)
    assert verify_lake_manifest(tmp_path / "lake1")["ok"] is True
    assert verify_lake_manifest(tmp_path / "lake2")["ok"] is True


def test_build_lake_staged_datasets_merge_manifest(tmp_path):
    from cryptobot.research.lake import build_lake, verify_lake_manifest

    raw = _dev_tree(tmp_path)
    build_lake(raw, tmp_path / "lake", datasets=["klines:1d"], workers=2)
    assert verify_lake_manifest(tmp_path / "lake")["ok"] is True
    build_lake(raw, tmp_path / "lake", datasets=["fundingRate"], workers=2)
    rep = verify_lake_manifest(tmp_path / "lake")
    assert rep["ok"] is True
    assert rep["files"] == 3  # 2 klines + 1 funding
