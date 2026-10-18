"""E1.3/E2.2: lake_finalize dq/scope/seal-holdout (synthetic lake)."""
from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("pandas")

REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "lake_finalize", REPO / "tools" / "lake_finalize.py")
assert SPEC and SPEC.loader
lake_finalize = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lake_finalize)


def _synth_lake(root: Path) -> Path:
    from cryptobot.research.lake import build_lake

    raw = root / "raw"
    idx = pd.date_range("2023-01-01", periods=120, freq="D", tz="UTC")
    for sym, vol in (("AAAUSDT", 1e8), ("BBBUSDT", 1e6)):
        lines = [f"{int(t.timestamp() * 1000)},100,101,99,100.5,{vol},"
                 f"{int(t.timestamp() * 1000) + 86399999},{100.5 * vol},"
                 f"10,5,{502.5},0" for t in idx]
        zp = raw / "klines" / "1d" / sym / "f.zip"
        zp.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("f.csv", "\n".join(lines) + "\n")
    lake = root / "lake"
    build_lake(raw, lake)
    return lake


def test_dq_and_scope(tmp_path):
    import argparse

    lake = _synth_lake(tmp_path)
    ns = argparse.Namespace(lake=str(lake), out=str(tmp_path / "dq.json"))
    assert lake_finalize.cmd_dq(ns) == 0
    dq = json.loads((tmp_path / "dq.json").read_text())
    assert dq["symbols"] == 2 and dq["total_rows"] == 240
    ns = argparse.Namespace(lake=str(lake), out_dir=str(tmp_path / "scope"))
    assert lake_finalize.cmd_scope(ns) == 0
    scope = json.loads((tmp_path / "scope" / "scope.json").read_text())
    assert scope["m1_top20"][0] == "AAAUSDT"  # higher DEV volume ranks first
    assert "AAAUSDT" in (tmp_path / "scope" / "metrics-symbols.txt"
                         ).read_text()


def test_seal_holdout_never_decodes(tmp_path):
    import argparse

    hold = tmp_path / "holdout_raw" / "klines"
    hold.mkdir(parents=True)
    raw = hold / "blob.zip"
    raw.write_bytes(b"\x00\x01binary-not-csv-at-all")
    ns = argparse.Namespace(holdout=str(tmp_path / "holdout_raw"),
                            vault_root=str(tmp_path / "vault"))
    assert lake_finalize.cmd_seal_holdout(ns) == 0
    access = json.loads((tmp_path / "vault" / "access_log.json").read_text())
    assert [e["action"] for e in access["entries"]] == ["seal"]
