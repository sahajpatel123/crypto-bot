"""E1.3: long-history lake — parquet store, hash manifest, DQ report.

DEV-side only: builds partitioned parquet from checksummed Vision zips
under data/lake/raw (DEV split). Holdout zips are never decoded here;
`research/verdict.py` alone decodes them at screen time (see the
HOLDOUT import lint in tests/unit/test_vault_holdout.py). This module
imports nothing from cryptobot.data.vault (lint would flag it).

Provenance: OBSERVED_PUBLIC. Schema version 1, recorded in parquet
metadata and the lake manifest.
"""
from __future__ import annotations

import hashlib
import json
import os
import zipfile
from datetime import timezone
from pathlib import Path
from typing import Any

import pandas as pd

SCHEMA_VERSION = 1
PROVENANCE = "OBSERVED_PUBLIC"
MANIFEST_FORMAT = "cryptobot-lake-manifest/1"

KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume",
              "close_time", "quote_volume", "trades", "taker_buy_base",
              "taker_buy_quote", "ignore"]
FUNDING_COLS = ["calc_time", "funding_interval_hours", "last_funding_rate"]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _chain_append(doc: dict, entry: dict) -> dict:
    entry = dict(entry)
    entry["prev"] = doc.get("chain_head", "genesis")
    entry["entry_hash"] = hashlib.sha256(
        json.dumps(entry, sort_keys=True).encode()).hexdigest()
    doc.setdefault("entries", []).append(entry)
    doc["chain_head"] = entry["entry_hash"]
    return entry


def _chain_verify(doc: dict) -> list[str]:
    problems: list[str] = []
    prev = "genesis"
    for i, entry in enumerate(doc.get("entries", [])):
        if entry.get("prev") != prev:
            problems.append(f"entry {i}: prev mismatch")
        body = {k: v for k, v in entry.items() if k != "entry_hash"}
        if hashlib.sha256(json.dumps(body, sort_keys=True).encode()
                           ).hexdigest() != entry.get("entry_hash"):
            problems.append(f"entry {i}: hash mismatch")
        prev = entry.get("entry_hash")
    if prev != doc.get("chain_head"):
        problems.append("chain_head mismatch")
    return problems


def _to_ms(values: pd.Series, name: str) -> pd.Series:
    med = float(values.median())
    if 1e11 < med < 1e14:
        return values.astype("int64")  # milliseconds
    if 1e8 < med < 1e11:
        return (values.astype("int64") * 1000)  # seconds -> ms
    raise ValueError(f"timestamp unit ambiguous for {name}: median={med}")


def _read_csv_from_zip(path: str | Path, *, header: bool) -> pd.DataFrame:
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if n.endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"{path}: expected 1 csv, found {names}")
        with zf.open(names[0]) as fh:
            return pd.read_csv(fh, header=0 if header else None)


def _finalize_time(df: pd.DataFrame, col: str) -> pd.DataFrame:
    df[col] = pd.to_datetime(_to_ms(pd.to_numeric(df[col], errors="raise"),
                                    col), unit="ms", utc=True)
    return df


def read_klines_zip(path: str | Path) -> pd.DataFrame:
    """Parse a Vision kline zip (spot/UM/mark/premium/rest-tail all match)."""
    df = _read_csv_from_zip(path, header=False)
    if df.shape[1] != 12:
        raise ValueError(f"{path}: expected 12 kline cols, got {df.shape[1]}")
    df.columns = KLINE_COLS
    for col in ("open", "high", "low", "close", "volume", "quote_volume",
                "trades", "taker_buy_base", "taker_buy_quote"):
        df[col] = pd.to_numeric(df[col], errors="raise")
    df = _finalize_time(df, "open_time")
    df = _finalize_time(df, "close_time")
    n = len(df)
    df = df.sort_values("open_time").drop_duplicates(
        subset="open_time", keep="first").reset_index(drop=True)
    df.attrs["dupes_removed"] = n - len(df)
    return df


def read_funding_zip(path: str | Path) -> pd.DataFrame:
    df = _read_csv_from_zip(path, header=True)
    if list(df.columns) != FUNDING_COLS:
        raise ValueError(f"{path}: funding cols {list(df.columns)}")
    df["last_funding_rate"] = pd.to_numeric(df["last_funding_rate"],
                                            errors="raise")
    df = _finalize_time(df.rename(columns={"calc_time": "calc_time"}),
                        "calc_time")
    n = len(df)
    df = df.sort_values("calc_time").drop_duplicates(
        subset="calc_time", keep="first").reset_index(drop=True)
    df.attrs["dupes_removed"] = n - len(df)
    return df


def read_metrics_zip(path: str | Path) -> pd.DataFrame:
    df = _read_csv_from_zip(path, header=True)
    # Vision documents create_time as venue local wall time; the venue
    # publishes in UTC. Recorded here as UTC explicitly.
    df["create_time"] = pd.to_datetime(df["create_time"], utc=True)
    for col in df.columns:
        if col not in ("create_time", "symbol"):
            df[col] = pd.to_numeric(df[col], errors="raise")
    n = len(df)
    df = df.sort_values("create_time").drop_duplicates(
        subset="create_time", keep="first").reset_index(drop=True)
    df.attrs["dupes_removed"] = n - len(df)
    return df


def read_rest_tail_csv(path: str | Path, kind: str) -> pd.DataFrame:
    """Parse a rest-tail CSV (E1.2 funding/klines October tail)."""
    path = Path(path)
    if kind == "funding":
        df = pd.read_csv(path)
        df["fundingTime"] = pd.to_datetime(
            _to_ms(pd.to_numeric(df["fundingTime"], errors="raise"),
                   "fundingTime"), unit="ms", utc=True)
        df["fundingRate"] = pd.to_numeric(df["fundingRate"], errors="raise")
        return df.sort_values("fundingTime").reset_index(drop=True)
    df = pd.read_csv(path, header=None)
    if df.shape[1] != 12:
        raise ValueError(f"{path}: expected 12 kline cols")
    df.columns = KLINE_COLS
    for col in ("open", "high", "low", "close", "volume", "quote_volume"):
        df[col] = pd.to_numeric(df[col], errors="raise")
    df = _finalize_time(df, "open_time")
    df = _finalize_time(df, "close_time")
    return df.sort_values("open_time").reset_index(drop=True)


def _write_parquet(df: pd.DataFrame, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(dest, index=False, compression="zstd")


def build_lake(raw_dir: str | Path, lake_dir: str | Path) -> dict:
    """Decode DEV zips -> partitioned parquet + hash-chained manifest."""
    from datetime import datetime

    raw, lake = Path(raw_dir), Path(lake_dir)
    manifest: dict[str, Any] = {
        "format": MANIFEST_FORMAT, "schema_version": SCHEMA_VERSION,
        "provenance": PROVENANCE, "chain_head": "genesis", "entries": [],
        "created_utc": datetime.now(timezone.utc).isoformat()}
    for dataset in ("klines", "markPriceKlines", "premiumIndexKlines"):
        for iv_dir in sorted((raw / dataset).glob("*")) if (raw / dataset).exists() else []:
            for sym_dir in sorted(iv_dir.glob("*")):
                frames = [read_klines_zip(z) for z in sorted(sym_dir.glob("*.zip"))]
                if not frames:
                    continue
                df = pd.concat(frames, ignore_index=True)
                df = df.sort_values("open_time").drop_duplicates(
                    subset="open_time", keep="first").reset_index(drop=True)
                dest = lake / dataset / f"interval={iv_dir.name}" / f"symbol={sym_dir.name}" / "data.parquet"
                _write_parquet(df, dest)
                _chain_append(manifest, _file_entry(lake, dest, rows=len(df)))
    for dataset, reader in (("fundingRate", read_funding_zip),
                            ("metrics", read_metrics_zip)):
        base = raw / dataset
        if not base.exists():
            continue
        for sym_dir in sorted(p for p in base.rglob("*") if p.is_dir()
                              and list(p.glob("*.zip"))):
            sym = sym_dir.name
            frames = [reader(z) for z in sorted(sym_dir.glob("*.zip"))]
            key = "calc_time" if dataset == "fundingRate" else "create_time"
            df = pd.concat(frames, ignore_index=True)
            df = df.sort_values(key).drop_duplicates(
                subset=key, keep="first").reset_index(drop=True)
            dest = lake / ("funding" if dataset == "fundingRate" else "metrics") \
                / f"symbol={sym}" / "data.parquet"
            _write_parquet(df, dest)
            _chain_append(manifest, _file_entry(lake, dest, rows=len(df)))
    mp = lake / "manifest.json"
    mp.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    return manifest


def _file_entry(lake: Path, dest: Path, *, rows: int) -> dict:
    return {"path": str(dest.relative_to(lake)), "sha256": _sha256_file(dest),
            "bytes": dest.stat().st_size, "rows": rows}


def verify_lake_manifest(lake_dir: str | Path) -> dict:
    lake = Path(lake_dir)
    manifest = json.loads((lake / "manifest.json").read_text(encoding="utf-8"))
    problems = _chain_verify(manifest)
    bad: list[str] = []
    for e in manifest.get("entries", []):
        p = lake / e["path"]
        if not p.exists() or _sha256_file(p) != e["sha256"]:
            bad.append(e["path"])
    problems += [f"file: {b}" for b in bad]
    return {"ok": not problems, "problems": problems,
            "files": len(manifest.get("entries", []))}


def data_quality_report(frames: dict[str, pd.DataFrame], *,
                        interval: str = "1d") -> dict:
    """Per-symbol DQ: gaps on the expected grid, outliers, monotonicity."""
    step = {"1d": pd.Timedelta(days=1), "1h": pd.Timedelta(hours=1),
            "1m": pd.Timedelta(minutes=1)}[interval]
    out: dict[str, dict] = {}
    for sym, df in frames.items():
        df = df.sort_values("open_time").reset_index(drop=True)
        first, last = df["open_time"].iloc[0], df["open_time"].iloc[-1]
        expected = int((last - first) / step) + 1
        gaps = max(0, expected - len(df))
        rng = (df["high"] - df["low"]) / df["close"].replace(0, float("nan"))
        logret = df["close"].astype(float).apply(
            __import__("math").log).diff().abs()
        wick = rng > 0.5
        jump = logret > (0.30 if interval == "1d" else 0.10)
        flagged = df[wick | jump.fillna(False)]
        worst = flagged.assign(_s=rng).nlargest(5, "_s")["open_time"].dt.strftime(
            "%Y-%m-%dT%H:%M:%SZ").tolist()
        out[sym] = {"rows": len(df), "first": first.isoformat(),
                    "last": last.isoformat(), "gaps": gaps,
                    "dupes_removed": int(df.attrs.get("dupes_removed", 0)),
                    "outliers": int((wick | jump.fillna(False)).sum()),
                    "outlier_bars": worst,
                    "monotonic": bool(df["open_time"].is_monotonic_increasing)}
    return out


def load_dev_frames(lake_dir: str | Path, dataset: str,
                    symbols: list[str], *, interval: str = "1d"
                    ) -> dict[str, pd.DataFrame]:
    """Load DEV parquet frames. Lake dir holds DEV splits only."""
    lake = Path(lake_dir)
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        if dataset in ("klines", "markPriceKlines", "premiumIndexKlines"):
            p = lake / dataset / f"interval={interval}" / f"symbol={sym}" / "data.parquet"
        elif dataset in ("funding", "fundingRate"):
            p = lake / "funding" / f"symbol={sym}" / "data.parquet"
        elif dataset == "metrics":
            p = lake / "metrics" / f"symbol={sym}" / "data.parquet"
        else:
            raise ValueError(f"unknown dataset {dataset!r}")
        if p.exists():
            out[sym] = pd.read_parquet(p)
    return out


__all__ = ["SCHEMA_VERSION", "PROVENANCE", "KLINE_COLS", "FUNDING_COLS",
           "read_klines_zip", "read_funding_zip", "read_metrics_zip",
           "read_rest_tail_csv", "build_lake", "verify_lake_manifest",
           "data_quality_report", "load_dev_frames"]
