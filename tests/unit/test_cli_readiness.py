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


def test_run_prod_blocked_without_owner_creds(monkeypatch, capsys):
    # Release §4: missing credentials are an explicit BLOCKED state
    # (refusal-at-submission is proven with injected creds below).
    _scrub(monkeypatch, "CRYPTOBOT_API_KEY", "CRYPTOBOT_API_SECRET")
    rc = cli.main(["run", "--mode", "prod", "--config", "configs/prod.toml"])
    out = capsys.readouterr().out
    assert rc == 3
    assert "BLOCKED" in out


def test_run_prod_rejects_wrong_mode_config(capsys):
    rc = cli.main(["run", "--mode", "prod", "--config", "configs/r2.toml"])
    assert rc == 2


def test_run_mode_choices_include_prod():
    parser = cli.build_parser()
    args = parser.parse_args(
        ["run", "--mode", "prod", "--config", "configs/prod.toml"])
    assert args.mode == "prod"


def _stub_status(**kw):
    base = {"base_url": "https://demo-fapi.binance.com",
            "account_tag": "abc123",
            "total_wallet_usdt": 100.0, "available_usdt": 99.0,
            "positions": [], "open_orders": []}
    base.update(kw)
    return base


class _StubEngine:
    status = None

    def __init__(self, **kw):
        pass

    def venue_status(self, symbols):
        return _StubEngine.status

    def close(self):
        pass


def _prod_config(tmp_path):
    text = open("configs/prod.toml").read()
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    path = tmp_path / "prod.toml"
    path.write_text(text)
    return str(path)


def _stub_venue_status(**kw):
    from cryptobot.adapters.binance_live import PROD_FAPI_URL
    base = {"base_url": PROD_FAPI_URL, "account_tag": "cafe01",
            "clock_skew_ms": 120, "can_trade": True, "fee_tier": "vip0",
            "position_mode": "one-way",
            "fees_bps": {"BTCUSDT": {"taker_bps": 5.0, "maker_bps": 2.0}},
            "filters": {"BTCUSDT": {"status": "TRADING"}},
            "positions": [], "open_orders": [],
            "total_wallet_usdt": 120.0, "available_usdt": 119.0}
    base.update(kw)
    return base


class _StubLiveEngine:
    status = None

    def __init__(self, **kw):
        pass

    def venue_status(self, symbols):
        return _StubLiveEngine.status

    def account_snapshot(self):
        from datetime import datetime, timezone
        from cryptobot.app.engine import AccountSnapshot
        st = _StubLiveEngine.status
        return AccountSnapshot(
            wallet_equity_usdt=st["total_wallet_usdt"],
            available_margin_usdt=st["available_usdt"],
            margin_balance_usdt=st["total_wallet_usdt"],
            positions=(), asof_utc=datetime(2026, 10, 14, tzinfo=timezone.utc),
            complete=True)

    def open_orders(self):
        return []

    def close(self):
        pass


def _stub_factory(config, key, secret, journal, run_tag, transport=None):
    assert key == "k" and secret == "s"
    return _StubLiveEngine()


def test_reconcile_no_creds_blocked(monkeypatch, capsys):
    _scrub(monkeypatch, "BINANCE_DEMO_KEY", "BINANCE_DEMO_SECRET")
    rc = cli.cmd_reconcile(argparse.Namespace(config="configs/demo.toml",
                                              expect_flat=False))
    assert rc == 3
    assert "BLOCKED" in capsys.readouterr().out


def test_reconcile_rejects_non_live_engine(capsys):
    rc = cli.cmd_reconcile(argparse.Namespace(config="configs/r2.toml",
                                              expect_flat=False))
    assert rc == 2


def test_reconcile_flat_pass(monkeypatch, capsys):
    monkeypatch.setenv("BINANCE_DEMO_KEY", "k")
    monkeypatch.setenv("BINANCE_DEMO_SECRET", "s")
    _StubEngine.status = _stub_status()
    import cryptobot.adapters.binance_live as live_mod
    monkeypatch.setattr(live_mod, "BinanceLiveEngine", _StubEngine)
    rc = cli.cmd_reconcile(argparse.Namespace(config="configs/demo.toml",
                                              expect_flat=True))
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "reconcile: FLAT" in out


def test_preflight_no_creds_blocked(monkeypatch, tmp_path, capsys):
    _scrub(monkeypatch, "CRYPTOBOT_API_KEY", "CRYPTOBOT_API_SECRET")
    rc = cli.cmd_preflight(argparse.Namespace(
        config=_prod_config(tmp_path), _engine_factory=_stub_factory))
    out = capsys.readouterr().out
    assert rc == 3, out
    assert "BLOCKED" in out


def test_preflight_all_green_offline(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CRYPTOBOT_API_KEY", "k")
    monkeypatch.setenv("CRYPTOBOT_API_SECRET", "s")
    _StubLiveEngine.status = _stub_venue_status()
    rc = cli.cmd_preflight(argparse.Namespace(
        config=_prod_config(tmp_path), _engine_factory=_stub_factory))
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "READY-EXCEPT-SUBMISSION" in out
    assert "ARMED-OFF" in out
    assert "FLAT" in out


def test_preflight_rejects_non_live_engine(tmp_path, capsys):
    rc = cli.cmd_preflight(argparse.Namespace(config="configs/r2.toml"))
    assert rc == 2


def test_prod_no_creds_blocked_before_build(monkeypatch, tmp_path, capsys):
    _scrub(monkeypatch, "CRYPTOBOT_API_KEY", "CRYPTOBOT_API_SECRET")
    called = []

    def _factory(*a, **k):
        called.append(True)
        raise AssertionError("must not build before creds")
    rc = cli._run_prod(argparse.Namespace(config=_prod_config(tmp_path),
                                          run_id=None), _factory)
    assert rc == 3
    assert called == []


def test_prod_full_driver_refuses_only_at_submission(monkeypatch, tmp_path,
                                                     capsys):
    monkeypatch.setenv("CRYPTOBOT_API_KEY", "k")
    monkeypatch.setenv("CRYPTOBOT_API_SECRET", "s")
    _StubLiveEngine.status = _stub_venue_status()
    rc = cli._run_prod(argparse.Namespace(config=_prod_config(tmp_path),
                                          run_id="prod-probe-1"),
                       _stub_factory)
    captured = capsys.readouterr()
    out, err = captured.out, captured.err
    assert rc == 2, out
    assert "prod driver: Session prod-probe-1 constructed" in out
    assert "FLAT" in out
    assert "submission disabled" in err


def test_prod_signed_failure_refuses(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CRYPTOBOT_API_KEY", "k")
    monkeypatch.setenv("CRYPTOBOT_API_SECRET", "s")
    _StubLiveEngine.status = _stub_venue_status(position_mode="hedge")
    rc = cli._run_prod(argparse.Namespace(config=_prod_config(tmp_path),
                                          run_id=None), _stub_factory)
    assert rc == 2
    assert "signed-check failures" in capsys.readouterr().err


def test_reconcile_exposed_expect_flat_fails(monkeypatch, capsys):
    monkeypatch.setenv("BINANCE_DEMO_KEY", "k")
    monkeypatch.setenv("BINANCE_DEMO_SECRET", "s")
    _StubEngine.status = _stub_status(
        positions=[{"symbol": "BTCUSDT", "positionAmt": "0.001",
                    "entryPrice": "100.0", "unRealizedProfit": "0.01"}],
        open_orders=[{"symbol": "BTCUSDT", "type": "STOP_MARKET",
                      "side": "SELL", "origQty": "0.001",
                      "origClientOrderId": "c1"}])
    import cryptobot.adapters.binance_live as live_mod
    monkeypatch.setattr(live_mod, "BinanceLiveEngine", _StubEngine)
    rc = cli.cmd_reconcile(argparse.Namespace(config="configs/demo.toml",
                                              expect_flat=True))
    assert rc == 2
    rc = cli.cmd_reconcile(argparse.Namespace(config="configs/demo.toml",
                                              expect_flat=False))
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "reconcile: EXPOSED" in out
    assert "0.001" in out and "c1" in out
