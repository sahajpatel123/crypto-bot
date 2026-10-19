"""E6.2: holdout decode + screen decision (synthetic zips)."""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("pandas")


def _zip(path: Path, name: str, text) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(text) + "\n" if isinstance(text, list) else text
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, body)
    return path


def _holdout_tree(tmp_path: Path):
    root = tmp_path / "holdout_raw"
    k1 = ("1577836800000,100,101,99,100.5,10,1577840399999,1005,5,5,502.5,0\n"
          "1577923200000,100.5,102,100,101.5,11,1577926799999,1116,6,6,660,0\n")
    a = _zip(root / "klines" / "1d" / "BTCUSDT" / "f.zip", "f.csv", k1)
    b = _zip(root / "klines" / "1d" / "BTCUSDT" / "g.zip", "g.csv", k1)
    f = _zip(root / "fundingRate" / "na" / "BTCUSDT" / "h.zip", "h.csv",
             "calc_time,funding_interval_hours,last_funding_rate\n"
             "1577836800000,8,0.0001\n")
    m = _zip(root / "metrics" / "BTCUSDT" / "m.zip", "m.csv",
             "create_time,symbol,sum_open_interest\n"
             "2024-01-01 00:00:00,BTCUSDT,100\n"
             "2024-01-01 00:05:00,BTCUSDT,101\n"
             "2024-01-02 00:00:00,BTCUSDT,110\n")
    files = []
    for p in (a, b, f, m):
        h = hashlib.sha256()
        h.update(p.read_bytes())
        files.append({"path": str(p), "sha256": h.hexdigest()})
    return files


def test_holdout_frames_decode_concat_dedupe(tmp_path):
    from cryptobot.research.verdict import holdout_frames_for_verdict

    frames = holdout_frames_for_verdict(_holdout_tree(tmp_path))
    assert len(frames["daily"]["BTCUSDT"]) == 2  # dupes across zips removed
    assert len(frames["funding"]["BTCUSDT"]) == 1
    oi = frames["oi"]["BTCUSDT"]
    assert oi.iloc[0] == 100.0 and oi.iloc[1] == 110.0  # daily 00:00 prints


def test_holdout_decode_refuses_tampered_bytes(tmp_path):
    from cryptobot.research.verdict import holdout_frames_for_verdict

    files = _holdout_tree(tmp_path)
    files[0] = dict(files[0], sha256="0" * 64)
    with pytest.raises(ValueError, match="integrity failure"):
        holdout_frames_for_verdict(files)


def test_screen_decision_gates():
    from cryptobot.research.verdict import screen_decision

    good = dict(point_sharpe=0.9, dev_sharpe=1.2, lb80=0.1, sharpe_2x=0.4,
                max_dd=0.2, n_rebalances=140)
    assert screen_decision(**good)["verdict"] == "SCREEN_PASS"
    assert screen_decision(**{**good, "point_sharpe": 0.2})["verdict"] == "FAIL"
    assert screen_decision(**{**good, "point_sharpe": 0.5})["verdict"] == "FAIL"  # <50% dev
    assert screen_decision(**{**good, "lb80": -0.5})["verdict"] == "FAIL"
    assert screen_decision(**{**good, "sharpe_2x": -0.1})["verdict"] == "FAIL"
    assert screen_decision(**{**good, "max_dd": 0.5})["verdict"] == "FAIL"
    assert screen_decision(**{**good, "n_rebalances": 12})["verdict"] == "UNDERPOWERED"
    assert "cannot PROVE" in screen_decision(**good)["screen_caveat"]


def _dev_lake(tmp_path: Path):
    import pandas as pd

    from cryptobot.research.lake import build_lake

    raw = tmp_path / "raw"
    idx = pd.date_range("2023-07-01", "2023-12-31", freq="D", tz="UTC")
    lines = [f"{int(t.timestamp() * 1000)},100,101,99,100.5,1000,"
             f"{int(t.timestamp() * 1000) + 86399999},100500,50,500,50250,0"
             for t in idx]
    _zip(raw / "klines" / "1d" / "BTCUSDT" / "d1.zip", "d1.csv", lines)
    _zip(raw / "klines" / "1h" / "BTCUSDT" / "h1.zip", "h1.csv", lines)
    lake = tmp_path / "lake"
    build_lake(raw, lake)
    return lake


def _holdout_case(tmp_path: Path):
    import pandas as pd

    from cryptobot.data.vault import Vault, build_holdout_manifest

    hold = tmp_path / "holdout_raw"
    idx = pd.date_range("2024-01-01", "2024-12-31", freq="D", tz="UTC")
    # Steady uptrend so B1-20d holds long all year (machinery test).
    closes = 100.0 * (1.002 ** __import__("numpy").arange(len(idx)))
    lines = [f"{int(t.timestamp() * 1000)},{c:.4f},{c * 1.001:.4f},"
             f"{c * 0.999:.4f},{c:.4f},1000,"
             f"{int(t.timestamp() * 1000) + 86399999},{c * 1000:.1f},"
             f"50,500,{c * 500:.1f},0"
             for t, c in zip(idx, closes)]
    zips = []
    for i in range(0, len(lines), 100):
        zips.append(_zip(hold / f"h{i}.zip", f"h{i}.csv", lines[i:i + 100]))
    manifest = build_holdout_manifest(zips, tmp_path / "hold.manifest.json")
    vault = Vault(tmp_path / "vault")
    chunk = vault.seal_chunk(manifest["manifest_path"], class_="HOLDOUT",
                             input_class="OBSERVED_PUBLIC")
    return vault, chunk


def test_cli_holdout_screen_end_to_end(tmp_path):
    import argparse
    import shutil

    from cryptobot import cli

    lake = _dev_lake(tmp_path)
    vault, chunk = _holdout_case(tmp_path)
    repo = Path(__file__).resolve().parents[2]
    cfg_src = repo / "research" / "configs" / "B1.toml"
    cfg = tmp_path / "B1.toml"
    shutil.copy(cfg_src, cfg)
    import hashlib
    digest = hashlib.sha256(cfg.read_bytes()).hexdigest()
    vault.freeze_hypothesis("B1", config_sha256=digest, commit="test",
                            prereg_path="research/prereg/B1.md")
    token = vault.issue_token("B1")
    cell = tmp_path / "cell.json"
    cell.write_text(json.dumps({"lookback_d": 20, "vol_window_d": 20,
                                "target_vol": 0.20}))
    out = tmp_path / "B1.screen.json"
    ns = argparse.Namespace(
        holdout_screen=True, hypothesis="B1", config=str(cfg),
        family_size=7, vault_root=str(tmp_path / "vault"),
        vault_token=token, vault_chunk=None, holdout_chunk=chunk.chunk_id,
        cell_params=str(cell), lake=str(lake), dev_sharpe=1.0, equity=1000.0,
        trades=None, out=str(out))
    rc = cli.cmd_verdict(ns)
    assert rc in (0, 1)
    doc = json.loads(out.read_text())
    assert doc["data_provenance"] == "SEALED-HOLDOUT"
    assert doc["hashes"]["sealed_chunk_sha256"] == chunk.sha256
    assert doc["verdict"] in ("SCREEN_PASS", "FAIL", "UNDERPOWERED")
    assert "cannot PROVE" in doc["screen_caveat"]
    # One-shot token burned: second screen refuses.
    out2 = tmp_path / "B1.screen2.json"
    ns.out = str(out2)
    assert cli.cmd_verdict(ns) == 2
    assert not out2.exists()


def test_cli_holdout_screen_refuses_ineligible(tmp_path):
    import argparse

    from cryptobot import cli

    lake = _dev_lake(tmp_path)
    vault, chunk = _holdout_case(tmp_path)
    # B9 never frozen -> ineligible (no token needed to refuse).
    ns = argparse.Namespace(
        holdout_screen=True, hypothesis="B9", config=str(tmp_path / "c.toml"),
        family_size=7, vault_root=str(tmp_path / "vault"),
        vault_token="bogus", vault_chunk=None, holdout_chunk=chunk.chunk_id,
        cell_params=str(tmp_path / "cell.json"), lake=str(lake),
        dev_sharpe=1.0, equity=1000.0, trades=None, out=str(tmp_path / "o.json"))
    assert cli.cmd_verdict(ns) == 2
