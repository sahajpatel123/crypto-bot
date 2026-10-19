"""E6.1: frozen runner on a synthetic micro-lake (schema, counts, determinism)."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pandas")


def _micro_lake(root: Path, *, seed: int = 7) -> Path:
    from cryptobot.research.lake import build_lake

    rng = np.random.default_rng(seed)
    raw = root / "raw"
    idx = pd.date_range("2020-01-01", "2023-12-31", freq="D", tz="UTC")
    for sym in ("AAAUSDT", "BBBUSDT"):
        drift = 0.004 if sym == "AAAUSDT" else -0.002
        rets = rng.normal(drift, 0.02, len(idx))
        closes = 100.0 * np.exp(np.cumsum(rets))
        lines = [f"{int(t.timestamp() * 1000)},{c:.4f},{c * 1.001:.4f},"
                 f"{c * 0.999:.4f},{c:.4f},1000000,"
                 f"{int(t.timestamp() * 1000) + 86399999},{c * 1000000:.1f},"
                 f"100,500000,{c * 500000:.1f},0"
                 for t, c in zip(idx, closes)]
        zp = raw / "klines" / "1d" / sym / "all.zip"
        zp.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("all.csv", "\n".join(lines) + "\n")
        # 1h leg: reuse daily rows (schedule-only; hourly unused by B2).
        zp = raw / "klines" / "1h" / sym / "all.zip"
        zp.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("all.csv", "\n".join(lines) + "\n")
        flines = ["calc_time,funding_interval_hours,last_funding_rate"]
        for t in idx[::30]:
            flines.append(f"{int(t.timestamp() * 1000)},8,0.0001")
        zp = raw / "fundingRate" / "na" / sym / "f.zip"
        zp.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("f.csv", "\n".join(flines) + "\n")
    lake = root / "lake"
    build_lake(raw, lake)
    return lake


def test_runner_b2_schema_counts_determinism(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "run_family_b",
        Path(__file__).resolve().parents[2] / "tools" / "run_family_b.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.chdir(tmp_path)
    lake = _micro_lake(tmp_path)
    (tmp_path / "research" / "configs").mkdir(parents=True)
    real = Path(__file__).resolve().parents[2] / "research" / "configs"
    for b in ("B2.toml",):
        (tmp_path / "research" / "configs" / b).write_text(
            (real / b).read_text())
    r1 = mod.evaluate_hypothesis("B2", lake, equity=1000.0)
    r2 = mod.evaluate_hypothesis("B2", lake, equity=1000.0)
    assert r1["n_trials"] == 6
    assert r1["gates"] == r2["gates"]  # deterministic
    assert set(r1["gates"]) >= {"pass", "best_oos_sharpe", "dsr", "pbo"}
    assert r1["config_sha256"]
    path = mod.write_dev_artifact(tmp_path / "auto_b", r1)
    doc = json.loads(path.read_text())
    assert doc["provenance"] == "OBSERVED_PUBLIC"
    assert doc["vault_frozen"] is None
    assert len(doc["cell_sharpes"]) == 6


def test_universe_tripwire_aborts_on_settlement_symbol(tmp_path, monkeypatch):
    import importlib.util

    import pandas as pd

    spec = importlib.util.spec_from_file_location(
        "run_family_b",
        Path(__file__).resolve().parents[2] / "tools" / "run_family_b.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.chdir(tmp_path)
    lake = _micro_lake(tmp_path)
    # Inject a fake high-volume SETTLED symbol into the built lake.
    idx = pd.date_range("2020-01-01", "2023-12-31", freq="D", tz="UTC")
    df = pd.DataFrame({"open_time": idx, "open": 1.0, "high": 1.0,
                       "low": 1.0, "close": 1.0, "quote_volume": 1e12})
    dest = lake / "klines" / "interval=1d" / "symbol=FAKEUSDTSETTLED"
    dest.mkdir(parents=True, exist_ok=True)
    df.to_parquet(dest / "data.parquet", index=False)
    (tmp_path / "research" / "configs").mkdir(parents=True)
    real = Path(__file__).resolve().parents[2] / "research" / "configs"
    (tmp_path / "research" / "configs" / "B2.toml").write_text(
        (real / "B2.toml").read_text())
    import pytest

    with pytest.raises(ValueError, match="untradeable"):
        mod.evaluate_hypothesis("B2", lake, equity=1000.0)
