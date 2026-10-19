"""F2.3: fixtures ingest — validate + install recorded venue fixtures."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _valid_dir(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "account.json").write_text(json.dumps({
        "totalWalletBalance": "100.0", "availableBalance": "90.0",
        "totalMarginBalance": "100.0", "totalInitialMargin": "0",
        "positions": []}))
    (root / "income.json").write_text(json.dumps([
        {"symbol": "BTCUSDT", "incomeType": "FUNDING_FEE",
         "income": "-1.25", "time": 1728720000000, "tranId": 111}]))
    (root / "openOrders.json").write_text(json.dumps([]))
    (root / "openAlgoOrders.json").write_text(json.dumps([]))
    (root / "leverageBracket.json").write_text(json.dumps([
        {"symbol": "BTCUSDT", "brackets": [
            {"bracket": 1, "notionalCap": 50000,
             "maintMarginRatio": 0.004, "cum": 0}]}]))
    (root / "commissionRate.json").write_text(json.dumps(
        {"symbol": "BTCUSDT", "makerCommissionRate": "0.0002",
         "takerCommissionRate": "0.0005"}))
    return root


def test_ingest_valid_installs(tmp_path, monkeypatch, capsys):
    from cryptobot import cli
    from cryptobot.testing import fixtures as fx

    monkeypatch.setattr(fx, "RECORDED_DIR", tmp_path / "recorded")
    src = _valid_dir(tmp_path / "src")
    rc = cli.cmd_fixtures(argparse.Namespace(
        fixtures_cmd="ingest", dir=str(src), force=False))
    assert rc == 0
    installed = sorted(p.name for p in (tmp_path / "recorded").iterdir())
    assert installed == ["account.json", "commissionRate.json",
                         "income.json", "leverageBracket.json",
                         "openAlgoOrders.json", "openOrders.json"]
    assert "installed 6" in capsys.readouterr().out


def test_ingest_refuses_secrets(tmp_path, monkeypatch, capsys):
    from cryptobot import cli
    from cryptobot.testing import fixtures as fx

    monkeypatch.setattr(fx, "RECORDED_DIR", tmp_path / "recorded")
    src = _valid_dir(tmp_path / "src")
    (src / "account.json").write_text(json.dumps(
        {"totalWalletBalance": "100.0", "apiSecret": "live-secret-abc"}))
    rc = cli.cmd_fixtures(argparse.Namespace(
        fixtures_cmd="ingest", dir=str(src), force=False))
    assert rc == 2
    assert "secret" in capsys.readouterr().err.lower()
    assert not (tmp_path / "recorded").exists()


def test_ingest_refuses_bad_shape(tmp_path, monkeypatch, capsys):
    from cryptobot import cli
    from cryptobot.testing import fixtures as fx

    monkeypatch.setattr(fx, "RECORDED_DIR", tmp_path / "recorded")
    src = _valid_dir(tmp_path / "src")
    (src / "leverageBracket.json").write_text(json.dumps(
        [{"symbol": "BTCUSDT", "brackets": []}]))
    rc = cli.cmd_fixtures(argparse.Namespace(
        fixtures_cmd="ingest", dir=str(src), force=False))
    assert rc == 2
    assert not (tmp_path / "recorded").exists()


def test_recorded_contract_skips_when_empty(tmp_path, monkeypatch):
    from cryptobot.testing import fixtures as fx

    monkeypatch.setattr(fx, "RECORDED_DIR", tmp_path / "empty")
    assert fx.recorded_contract_cases() == []


def test_recorded_contract_runs_when_present(tmp_path, monkeypatch):
    from cryptobot.testing import fixtures as fx

    target = tmp_path / "recorded"
    monkeypatch.setattr(fx, "RECORDED_DIR", target)
    _valid_dir(target)
    cases = fx.recorded_contract_cases()
    assert {c["name"] for c in cases} == {"account", "income",
                                          "openOrders", "openAlgoOrders",
                                          "leverageBracket",
                                          "commissionRate"}
    for case in cases:
        fx.check_recorded_case(case)  # raises on contract breach
