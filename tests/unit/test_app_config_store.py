"""App config + store tests (manager-owned, A-001)."""
from pathlib import Path

import pytest

from cryptobot.app.config import ConfigError, load_config, with_resolved_symbols
from cryptobot.app.store import RunStore

SAMPLE = "configs/paper.toml"


def test_sample_config_loads():
    cfg = load_config(SAMPLE)
    assert cfg.mode == "replay"
    assert cfg.engine_kind == "reference"
    assert cfg.paper_capital_usdt == 120.0
    assert cfg.accounting_tz == "Asia/Kolkata"
    assert len(cfg.fingerprint) == 16
    assert load_config(SAMPLE).fingerprint == cfg.fingerprint


def test_paper_mode_refuses_reference_engine(tmp_path):
    text = (Path(SAMPLE).read_text()
            .replace('mode = "replay"', 'mode = "paper"', 1))
    path = tmp_path / "paper.toml"
    path.write_text(text)
    with pytest.raises(ConfigError, match="requires engine.kind"):
        load_config(path)


def test_invalid_values_rejected(tmp_path):
    base = Path(SAMPLE).read_text()
    cases = [
        ('mode = "replay"', 'mode = "live"'),
        ("leverage_cap = 3.0", "leverage_cap = 0"),
        ("operating_stop_pct = 0.005", "operating_stop_pct = 2"),
        ("emergency_stop_pct = 0.01", "emergency_stop_pct = -1"),
        ('accounting_tz = "Asia/Kolkata"', 'accounting_tz = "UTC"'),
        ('enabled = ["S1", "S2", "S3", "S4", "S5"]', 'enabled = ["S9"]'),
    ]
    for old, new in cases:
        path = tmp_path / "bad.toml"
        path.write_text(base.replace(old, new, 1))
        with pytest.raises(ConfigError):
            load_config(path)


def test_missing_config_rejected(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.toml")


def test_store_run_lifecycle(tmp_path):
    store = RunStore(tmp_path / "s.db")
    try:
        store.create_run("r1", "replay", "fp", str(tmp_path), 123)
        run = store.get_run("r1")
        assert run["state"] == "starting" and run["pid"] == 123
        store.set_state("r1", "ready", "t")
        assert store.get_run("r1")["state"] == "ready"
        store.heartbeat("r1")
        store.record_intent("r1", "i1", "S1", "BTCUSDT", "LONG",
                            "rejected", "strategy:no-fire:x")
        assert store.record_event("r1", "e1", "fill", {"a": 1}) is True
        assert store.record_event("r1", "e1", "fill", {"a": 1}) is False
        store.checkpoint("r1", "cursor", {"last_seq": 9})
        counts = store.counts("r1")
        assert counts == {"intents": 1, "execution_events": 1,
                          "risk_transitions": 1, "checkpoints": 1}
        assert store.stop_requested("r1") is None
        store.request_stop("r1", "flatten")
        assert store.stop_requested("r1") == "flatten"
        assert store.get_run("zz") is None
    finally:
        store.close()


def test_with_resolved_symbols_recomputes_fingerprint():
    cfg = load_config(SAMPLE)
    assert list(cfg.symbols) == []
    resolved = with_resolved_symbols(cfg, ["btcusdt", "ethusdt"])
    assert list(resolved.symbols) == ["BTCUSDT", "ETHUSDT"]
    assert len(resolved.fingerprint) == 16
    assert resolved.fingerprint != cfg.fingerprint
    # Same universe loaded from TOML gets the same fingerprint.
    text = Path(SAMPLE).read_text().replace(
        "symbols = []", 'symbols = ["BTCUSDT", "ETHUSDT"]', 1)
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".toml",
                                     delete=False) as fh:
        fh.write(text)
    try:
        assert load_config(fh.name).fingerprint == resolved.fingerprint
    finally:
        import os
        os.unlink(fh.name)
    with pytest.raises(ConfigError, match="non-empty"):
        with_resolved_symbols(cfg, [])
