"""CORR exchange boundary: readiness command + disabled prod route.

No network, no real keys. Signed-venue behavior is covered with a stub
engine; credential-absent paths use env scrubbing.
"""
import argparse
import os

import pytest

from cryptobot import cli
from cryptobot.app.config import load_config


def _scrub(monkeypatch, *names):
    for name in names:
        monkeypatch.delenv(name, raising=False)


def test_demo_config_is_credentialed_demo_paper():
    cfg = load_config("configs/demo.toml")
    assert cfg.mode == "paper"
    assert cfg.engine_kind == "live"
    assert cfg.engine_demo is True
    assert cfg.engine_base_url == "https://demo-fapi.binance.com"
    assert cfg.allow_live_submission is False


def test_public_paper_config_needs_no_keys():
    cfg = load_config("configs/r2.toml")
    assert cfg.mode == "paper"
    assert cfg.engine_kind == "nautilus"
    # The nautilus paper branch builds NautilusPaperEngine only; it never
    # consults demo/prod credential env vars (cli._run_paper else-branch).
    import inspect
    src = inspect.getsource(cli._run_paper)
    nautilus_branch = src.split("else:", 1)[1]
    assert "BINANCE_DEMO_KEY" not in nautilus_branch
    assert "CRYPTOBOT_API_KEY" not in nautilus_branch


def test_readiness_demo_no_creds_blocked_only_signed(monkeypatch, capsys):
    _scrub(monkeypatch, "BINANCE_DEMO_KEY", "BINANCE_DEMO_SECRET")
    rc = cli.cmd_readiness(argparse.Namespace(config="configs/demo.toml"))
    out = capsys.readouterr().out
    assert rc == 3
    assert "[PASS] config-loads" in out
    assert "[PASS] host-pinned-demo" in out
    assert "[PASS] no-inline-secrets" in out
    assert "BLOCKED" in out
    assert "BINANCE_DEMO_KEY" in out  # env NAME shown...
    # ...but values never echoed (sentinel would appear if echoed).


def test_readiness_prod_no_creds_blocked(monkeypatch, capsys):
    _scrub(monkeypatch, "CRYPTOBOT_API_KEY", "CRYPTOBOT_API_SECRET")
    rc = cli.cmd_readiness(argparse.Namespace(config="configs/prod.toml"))
    out = capsys.readouterr().out
    assert rc == 3
    assert "[PASS] host-pinned-prod" in out
    assert "BLOCKED" in out


def test_readiness_rejects_non_live_engine(capsys):
    rc = cli.cmd_readiness(argparse.Namespace(config="configs/r2.toml"))
    out = capsys.readouterr().out
    assert rc == 2
    assert "[FAIL] live-engine" in out


def test_readiness_signed_ready_with_stub_engine(monkeypatch, tmp_path,
                                                 capsys):
    monkeypatch.setenv("BINANCE_DEMO_KEY", "k")
    monkeypatch.setenv("BINANCE_DEMO_SECRET", "s")

    class StubEngine:
        def __init__(self, **kw):
            assert kw["demo"] is True
            assert kw["live_enable"] is True

        def venue_status(self, symbols):
            assert symbols == ["BTCUSDT"]
            return {
                "base_url": "https://demo-fapi.binance.com",
                "account_tag": "abc123",
                "clock_skew_ms": 120,
                "can_trade": True,
                "fee_tier": 0,
                "position_mode": "one-way",
                "fees_bps": {"BTCUSDT": {"taker_bps": 5.0,
                                         "maker_bps": 2.0}},
                "filters": {"BTCUSDT": {"status": "TRADING",
                                        "filters": {}}},
                "positions": [],
                "open_orders": [],
                "total_wallet_usdt": 100.0,
                "available_usdt": 99.0,
            }

        def close(self):
            pass

    import cryptobot.adapters.binance_live as live_mod
    monkeypatch.setattr(live_mod, "BinanceLiveEngine", StubEngine)
    rc = cli.cmd_readiness(argparse.Namespace(config="configs/demo.toml"))
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "readiness: READY" in out
    assert "[PASS] venue-connect" in out


def test_readiness_never_echoes_values(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("BINANCE_DEMO_KEY", "sk-live-sentinel")
    monkeypatch.setenv("BINANCE_DEMO_SECRET", "shh-sentinel")

    class FailEngine:
        def __init__(self, **kw):
            pass

        def venue_status(self, symbols):
            from cryptobot.adapters.binance_live import VenueHttpError
            raise VenueHttpError(0, None, "simulated down")

        def close(self):
            pass

    import cryptobot.adapters.binance_live as live_mod
    monkeypatch.setattr(live_mod, "BinanceLiveEngine", FailEngine)
    rc = cli.cmd_readiness(argparse.Namespace(config="configs/demo.toml"))
    out = capsys.readouterr().out + capsys.readouterr().err
    assert rc == 2
    assert "sk-live-sentinel" not in out
    assert "shh-sentinel" not in out


def test_run_prod_refuses_even_when_guards_pass(capsys):
    rc = cli.main(["run", "--mode", "prod", "--config", "configs/prod.toml"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "disabled for this assignment" in err


def test_run_prod_rejects_wrong_mode_config(capsys):
    rc = cli.main(["run", "--mode", "prod", "--config", "configs/r2.toml"])
    assert rc == 2


def test_run_mode_choices_include_prod():
    parser = cli.build_parser()
    args = parser.parse_args(
        ["run", "--mode", "prod", "--config", "configs/prod.toml"])
    assert args.mode == "prod"
