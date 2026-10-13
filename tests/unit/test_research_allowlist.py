"""Allowlist gate tests (Worker 4, CORR-STRAT)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.research.allowlist import (AllowlistError, enforce,  # noqa: E402
                                          resolve_config_arms,
                                          runtime_param_fingerprint, verify)

REPO = Path(__file__).resolve().parents[2]
REGISTRY = REPO / "trials" / "round-01.json"
PARAMS = REPO / "trials" / "round-01.params.json"


def test_resolve_base_and_all():
    assert resolve_config_arms(["S1", "S2", "S3", "S4"], "base") == \
        ["S1", "S2", "S3", "S4"]
    resolved = resolve_config_arms(["S1", "S2", "S3", "S4"], "all")
    assert len(resolved) == 11  # distinct S1-S4 arm IDs, not 18
    assert "S2-V" in resolved and "S2-F" in resolved


def test_resolve_s5_has_no_variants():
    assert resolve_config_arms(["S5"], "all") == ["S5"]
    with pytest.raises(AllowlistError, match="unknown strategy"):
        resolve_config_arms(["S9"], "base")
    with pytest.raises(AllowlistError, match="base\\|all"):
        resolve_config_arms(["S1"], "everything")


def test_resolve_allowlist_filters_and_rejects_unknown():
    allow = ["S1", "S2", "S3", "S4", "S1-V", "S1-F", "S3-R", "S3-C",
             "S4-S"]
    resolved = resolve_config_arms(["S1", "S2", "S3", "S4"], "all", allow)
    assert sorted(resolved) == sorted(allow)
    with pytest.raises(AllowlistError, match="unknown arms"):
        resolve_config_arms(["S1"], "all", ["S1", "S1-X"])


def test_verify_round01_config_passes():
    report = verify(REPO / "configs" / "round01.toml", REGISTRY, PARAMS)
    assert report["ok"] is True
    assert report["resolved_count"] == 9
    assert report["extra_arms"] == [] and report["missing_arms"] == []
    assert report["param_diffs"] == {}


def test_verify_arms_all_fails_on_s2_variants(tmp_path):
    config = tmp_path / "all.toml"
    config.write_text('[strategies]\nenabled = ["S1", "S2", "S3", "S4"]\n'
                      'arms = "all"\n', encoding="utf-8")
    report = verify(config, REGISTRY, PARAMS)
    assert report["ok"] is False
    assert report["extra_arms"] == ["S2-F", "S2-V"]
    with pytest.raises(AllowlistError, match="S2-V"):
        enforce(config, REGISTRY, PARAMS)


def test_verify_detects_param_drift(tmp_path):
    drifted = json.loads(PARAMS.read_text(encoding="utf-8"))
    drifted["families"]["S1"]["params"]["mom_min_bps"] = 99.0
    params = tmp_path / "drift.params.json"
    params.write_text(json.dumps(drifted), encoding="utf-8")
    report = verify(REPO / "configs" / "round01.toml", REGISTRY, params)
    assert report["ok"] is False
    assert list(report["param_diffs"]) == ["S1"]
    with pytest.raises(AllowlistError, match="param_drift"):
        enforce(REPO / "configs" / "round01.toml", REGISTRY, params)


def test_session_filter_follows_allowlist(tmp_path):
    from cryptobot.app.config import load_config
    from cryptobot.app.session import Session
    from cryptobot.app.store import RunStore

    text = (REPO / "configs" / "round01.toml").read_text(encoding="utf-8")
    config_path = tmp_path / "round01.toml"
    config_path.write_text(text, encoding="utf-8")
    cfg = load_config(config_path)
    assert cfg.strategies_arms_allowlist is not None
    store = RunStore(tmp_path / "store.db")
    session = Session(cfg, store, tmp_path / "run", "allow-test")
    adapters, modules = session._strategy_adapters()
    assert sorted(adapters) == ["S1", "S2", "S3", "S4"]
    # S2 has no allowlisted variants (S2-V/S2-F excluded), so no S2
    # variant module; S5 excluded entirely though its adapter exists.
    assert sorted(modules) == ["S1", "S3", "S4"]
    assert "S5" not in adapters


def test_allowlist_config_validation(tmp_path):
    from cryptobot.app.config import ConfigError, load_config

    text = (REPO / "configs" / "round01.toml").read_text(encoding="utf-8")
    bad = tmp_path / "bad.toml"
    bad.write_text(text.replace('"S4-S"]', '"S4-S", "S9"]'),
                   encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown arm"):
        load_config(bad)
    legacy = load_config(REPO / "configs" / "paper.toml")
    assert legacy.strategies_arms_allowlist is None


def test_live_fingerprint_shape():
    live = runtime_param_fingerprint()
    assert set(live) == {"S1", "S2", "S3", "S4"}
    assert live["S1"]["params"]["breakout_n"] == 120
    assert live["S3"]["params"]["cost_cover_bps"] == 26.0


def test_only_config_gates_single_arm(tmp_path):
    import json as _json

    from cryptobot.research.allowlist import config_arms
    registry = _json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert config_arms(registry, "R01-S1-V") == ["S1-V"]
    assert sorted(config_arms(registry, "R01-COMBINED")) == sorted(
        ["S1", "S2", "S3", "S4", "S1-V", "S1-F", "S3-R", "S3-C", "S4-S"])
    assert config_arms(registry, "R01-CASH") == []
    config = tmp_path / "s1v.toml"
    config.write_text('[strategies]\nenabled = ["S1"]\narms = "all"\n'
                      'arms_allowlist = ["S1-V"]\n', encoding="utf-8")
    report = verify(config, REGISTRY, PARAMS, only_config="R01-S1-V")
    assert report["ok"] is True
    with pytest.raises(AllowlistError, match="unknown config"):
        verify(config, REGISTRY, PARAMS, only_config="R01-NOPE")
    bad = verify(config, REGISTRY, PARAMS, only_config="R01-S1")
    assert bad["ok"] is False
    assert bad["missing_arms"] == ["S1"]
