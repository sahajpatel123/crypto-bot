"""E6: DEV eval counts every cell and refuses holdout paths and SYNTHETIC."""
from __future__ import annotations

import pandas as pd
import pytest

pytest.importorskip("pandas")


def _cfg():
    from cryptobot.research.family_b_eval import load_config
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    return load_config(root / "research" / "configs" / "B1.toml")


def test_grid_sizes_match_prereg():
    from cryptobot.research.family_b_eval import EXPECTED_CELLS, _cells_from, load_config
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    for name, n in EXPECTED_CELLS.items():
        cfg = load_config(root / "research" / "configs" / f"{name}.toml")
        assert len(_cells_from(name, cfg["grid"])) == n


def test_holdout_path_is_refused():
    from cryptobot.research.family_b import MarketData
    from cryptobot.research.family_b_eval import evaluate_hypothesis
    with pytest.raises(RuntimeError, match="holdout"):
        evaluate_hypothesis("B1", MarketData(), _cfg(),
                            paths=["data/lake/holdout_raw/klines/a.zip"])


def test_rebalance_weekly_is_monday():
    from cryptobot.research.family_b_eval import rebalance_dates
    idx = pd.date_range("2021-01-01", periods=14, freq="D", tz="UTC")
    days = rebalance_dates(idx, "weekly")
    assert days
    assert all(d.dayofweek == 0 for d in days)


def test_synthetic_noise_is_not_promoted():
    from cryptobot.research.family_b import MarketData
    from cryptobot.research.family_b_eval import evaluate_hypothesis
    import numpy as np
    rng = np.random.default_rng(0)
    idx = pd.date_range("2020-01-01", "2021-06-30", freq="D", tz="UTC")
    daily = {}
    for sym in ("AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT"):
        rets = rng.normal(0.0, 0.02, len(idx))
        close = 100.0 * np.exp(np.cumsum(rets))
        daily[sym] = pd.DataFrame({
            "open_time": idx, "open": close, "high": close * 1.01,
            "low": close * 0.99, "close": close,
            "quote_volume": np.full(len(idx), 5e8)})
    data = MarketData(daily=daily)
    report = evaluate_hypothesis(
        "B1", data, _cfg(), provenance="SYNTHETIC", equity=10_000.0)
    assert report["n_trials"] == 12
    assert report["promoted"] is False
    assert any("SYNTHETIC" in f for f in report["failures"])
    assert "cannot prove" in report["screen_not_proof"]
