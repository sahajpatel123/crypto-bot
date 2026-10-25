"""CORR exchange boundary: readiness command + disabled prod route.

No network, no real keys. Signed-venue behavior is covered with a stub
engine; credential-absent paths use env scrubbing.
"""
import argparse
from datetime import UTC
from pathlib import Path

import pytest

from cryptobot import cli
from cryptobot.app.config import load_config


def _scrub(monkeypatch, *names):
    for name in names:
        monkeypatch.delenv(name, raising=False)


def _ready_venue_status(**updates):
    status = {
        "base_url": "https://demo-fapi.binance.com",
        "account_tag": "abc123",
        "clock_skew_ms": 120,
        "can_trade": True,
        "account_can_withdraw": False,
        "fee_tier": 0,
        "position_mode": "one-way",
        "fees_bps": {"BTCUSDT": {"taker_bps": 5.0,
                                    "maker_bps": 2.0}},
        "filters": {"BTCUSDT": {"status": "TRADING", "filters": {}}},
        "positions": [],
        "open_orders": [],
        "total_wallet_usdt": 100.0,
        "available_usdt": 99.0,
    }
    status.update(updates)
    return status


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


def test_readiness_account_withdrawal_flag_is_not_key_permission(
        monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("BINANCE_DEMO_KEY", "k")
    monkeypatch.setenv("BINANCE_DEMO_SECRET", "s")

    class StubEngine:
        def __init__(self, **kw):
            assert kw["demo"] is True
            assert kw["live_enable"] is True

        def venue_status(self, symbols):
            assert symbols == ["BTCUSDT"]
            return _ready_venue_status()

        def close(self):
            pass

    import cryptobot.adapters.binance_live as live_mod
    monkeypatch.setattr(live_mod, "BinanceLiveEngine", StubEngine)
    rc = cli.cmd_readiness(argparse.Namespace(config="configs/demo.toml"))
    out = capsys.readouterr().out
    assert rc == 3, out
    assert "readiness: UNVERIFIED" in out
    assert "[PASS] venue-connect" in out
    assert "[UNVERIFIED] withdrawals" in out
    assert "does not verify the API-key restriction" in out
    assert "readiness: READY" not in out


@pytest.mark.parametrize(
    ("account_can_withdraw", "row_state", "exit_code"),
    [(True, "FAIL", 2), (None, "UNVERIFIED", 3)],
)
def test_readiness_refuses_risk_or_unverified_withdrawal_signal(
        monkeypatch, capsys, account_can_withdraw, row_state, exit_code):
    monkeypatch.setenv("BINANCE_DEMO_KEY", "k")
    monkeypatch.setenv("BINANCE_DEMO_SECRET", "s")

    class StubEngine:
        def __init__(self, **_kw):
            pass

        def venue_status(self, _symbols):
            return _ready_venue_status(
                account_can_withdraw=account_can_withdraw)

        def close(self):
            pass

    import cryptobot.adapters.binance_live as live_mod
    monkeypatch.setattr(live_mod, "BinanceLiveEngine", StubEngine)
    rc = cli.cmd_readiness(argparse.Namespace(config="configs/demo.toml"))
    out = capsys.readouterr().out
    assert rc == exit_code
    assert f"[{row_state}] withdrawals" in out
    if account_can_withdraw is None:
        assert "readiness: UNVERIFIED" in out
        assert "readiness: READY" not in out
    else:
        assert "account reports canWithdraw=true" in out
        assert "readiness: READY" not in out


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


class _CleanRestrictions:
    """apiRestrictions answer for a safe, capital-bearing key.

    Injected into `_run_prod` so the pre-trade permission gate never dials a
    public host from a unit test.
    """

    DOCUMENT = {
        "ipRestrict": True,
        "enableReading": True,
        "enableWithdrawals": False,
        "enableInternalTransfer": False,
        "permitsUniversalTransfer": False,
        "enableMargin": False,
        "enableSpotAndMarginTrading": False,
        "enableFutures": True,
    }

    def __init__(self, document=None):
        self.document = dict(document or self.DOCUMENT)
        self.calls = []

    def request(self, method, path, params, headers):
        self.calls.append((method, path, dict(params), dict(headers)))
        return dict(self.document)


def _clean_permissions():
    return _CleanRestrictions()


def _prod_config(tmp_path):
    text = Path("configs/prod.toml").read_text()
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
        from datetime import datetime

        from cryptobot.app.engine import AccountSnapshot
        st = _StubLiveEngine.status
        return AccountSnapshot(
            wallet_equity_usdt=st["total_wallet_usdt"],
            available_margin_usdt=st["available_usdt"],
            margin_balance_usdt=st["total_wallet_usdt"],
            positions=(), asof_utc=datetime(2026, 10, 14, tzinfo=UTC),
            complete=True)

    def open_orders(self):
        return []

    def verify_account_modes(self, symbols, *, leverage_cap):
        # T1.1 stub: account already in the required modes.
        return {"position_mode": "one-way", "multi_assets": False,
                "margin_type": "ISOLATED", "leverage": 3,
                "symbols": list(symbols)}

    def journal_client_ids(self):
        return ()

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


class _StubWsClient:
    dialed = None

    def __init__(self, script):
        self._script = list(script)
        self.closed = False

    @classmethod
    def connect(cls, url, timeout_s=10.0):
        cls.dialed = (url, timeout_s)
        return cls(cls.script)

    def recv_message(self, timeout_s):
        from cryptobot.market_data.ws import WsClosed
        kind, payload = self._script.pop(0)
        if kind == "timeout":
            raise WsClosed(f"read timeout after {timeout_s} s with no message")
        if kind == "dead":
            raise WsClosed("socket error while waiting: EOF")
        return kind, payload

    def close(self, code=1000, reason=""):
        self.closed = True


class _StubLiveForStream:
    def user_stream_url(self, key):
        return f"wss://demo-fstream.binance.com/ws/{key}"


def test_ws_socket_factory_dials_key_url(monkeypatch):
    import cryptobot.market_data.ws as ws_mod
    _StubWsClient.script = [("text", b'{"e":"x"}')]
    monkeypatch.setattr(ws_mod, "WsClient", _StubWsClient)
    factory = cli._ws_socket_factory_for(_StubLiveForStream())
    sock = factory("KEY123")
    assert _StubWsClient.dialed[0] == \
        "wss://demo-fstream.binance.com/ws/KEY123"
    assert sock.recv(1.0) == {"e": "x"}


def test_ws_socket_timeout_idle_binary_ignored_death_raises(monkeypatch):
    import cryptobot.market_data.ws as ws_mod
    from cryptobot.market_data.ws import WsClosed
    _StubWsClient.script = [("timeout", None), ("binary", b"\x00"),
                            ("dead", None)]
    monkeypatch.setattr(ws_mod, "WsClient", _StubWsClient)
    factory = cli._ws_socket_factory_for(_StubLiveForStream())
    sock = factory("K")
    assert sock.recv(1.0) is None
    assert sock.recv(1.0) is None
    with pytest.raises(WsClosed):
        sock.recv(1.0)


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
    # Contract changed with the live launch: prod now refuses at the
    # arming layer (config switch + GO gate + armed record) instead of
    # constructing a driver it would never run. Read-only verification
    # (guards, signed reads, FLAT state) still happens first.
    monkeypatch.setenv("CRYPTOBOT_API_KEY", "k")
    monkeypatch.setenv("CRYPTOBOT_API_SECRET", "s")
    _StubLiveEngine.status = _stub_venue_status()
    rc = cli._run_prod(argparse.Namespace(config=_prod_config(tmp_path),
                                          run_id="prod-probe-1"),
                       _stub_factory,
                       _permission_transport=_clean_permissions())
    captured = capsys.readouterr()
    out, err = captured.out, captured.err
    assert rc == 2, out
    assert "FLAT" in out
    assert "allow_live_submission is false" in err


def test_prod_signed_failure_refuses(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CRYPTOBOT_API_KEY", "k")
    monkeypatch.setenv("CRYPTOBOT_API_SECRET", "s")
    _StubLiveEngine.status = _stub_venue_status(position_mode="hedge")
    rc = cli._run_prod(argparse.Namespace(config=_prod_config(tmp_path),
                                          run_id=None), _stub_factory,
                       _permission_transport=_clean_permissions())
    assert rc == 2
    assert "signed-check failures" in capsys.readouterr().err


def test_paper_run_interrupted_prints_resume_hint(monkeypatch, tmp_path,
                                                  capsys):
    # A venue/connection death mid-run (e.g. routes-exhausted, observed
    # on paper-proof-30m) must leave a resume hint, not a bare traceback.
    text = Path("configs/paper-protected.toml").read_text()
    text = text.replace('symbols = []',
                        'symbols = ["BTCUSDT"]', 1)
    text = text.replace('dir = "runs"', f'dir = "{tmp_path}"', 1)
    cfg_path = tmp_path / "paper.toml"
    cfg_path.write_text(text)
    from cryptobot.app.session import Session

    def _dead(self, *a, **k):
        raise ConnectionError("routes-exhausted: test")
    monkeypatch.setattr(Session, "run_live", _dead)
    # Explicit symbols must skip discovery entirely (no network).
    import cryptobot.market_data.collector as collector_mod

    def _no_discovery(*a, **k):
        raise AssertionError("discovery must not run with explicit symbols")
    monkeypatch.setattr(collector_mod, "select_capture_set",
                        _no_discovery)
    rc = cli._run_paper(argparse.Namespace(
        config=str(cfg_path), duration="60s",
        run_id="crash-1", resume=False))
    out = capsys.readouterr()
    assert rc == 3
    assert "interrupted" in out.err and "ConnectionError" in out.err
    assert "--resume" in out.out and "crash-1" in out.out


def test_paper_run_records_discovery(monkeypatch, tmp_path, capsys):
    # Empty symbols resolve via discovery (stubbed, no network) and the
    # resolved universe is recorded in the run dir for audit.
    import json

    import cryptobot.market_data.collector as collector_mod
    import cryptobot.market_data.discovery as discovery_mod
    from cryptobot.app.session import Session

    text = Path("configs/paper-protected.toml").read_text()
    text = text.replace('dir = "runs"', f'dir = "{tmp_path}"', 1)
    cfg_path = tmp_path / "paper.toml"
    cfg_path.write_text(text)
    monkeypatch.setattr(
        discovery_mod, "fetch_exchange_info",
        lambda *a, **k: ({"symbols": []}, 1.0, "t"))
    monkeypatch.setattr(
        collector_mod, "select_capture_set",
        lambda *a, **k: (("BTCUSDT",), "top-1 test", {}))

    def _ok(self, *a, **k):
        return {"opening_equity": 120.0, "closing_equity": 120.0,
                "net_return_pct": 0.0, "intents_admitted": 0,
                "events_seen": 0}
    monkeypatch.setattr(Session, "run_live", _ok)
    rc = cli._run_paper(argparse.Namespace(
        config=str(cfg_path), duration="60s",
        run_id="disc-1", resume=False))
    assert rc == 0, capsys.readouterr().err
    record = json.loads(
        (tmp_path / "disc-1" / "discovery.json").read_text())
    assert record["symbols"] == ["BTCUSDT"]
    assert "top-1" in record["rule"]


def test_paper_resume_reuses_recorded_universe(monkeypatch, tmp_path,
                                               capsys):
    # Resume must not re-discover: rotation mid-run would desync books
    # from the store. Recorded discovery.json wins; discovery raising
    # proves it is never called.
    import json

    import cryptobot.market_data.collector as collector_mod
    from cryptobot.app.session import Session

    text = Path("configs/paper-protected.toml").read_text()
    text = text.replace('dir = "runs"', f'dir = "{tmp_path}"', 1)
    cfg_path = tmp_path / "paper.toml"
    cfg_path.write_text(text)
    rundir = tmp_path / "res-1"
    rundir.mkdir()
    (rundir / "discovery.json").write_text(json.dumps(
        {"rule": "recorded", "symbols": ["BTCUSDT", "ETHUSDT"]}))
    monkeypatch.setattr(
        collector_mod, "select_capture_set",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("fresh discovery on resume")))
    seen = {}

    def _ok(self, *a, **k):
        seen["symbols"] = list(self.config.symbols)
        return {"opening_equity": 120.0, "closing_equity": 120.0,
                "net_return_pct": 0.0, "intents_admitted": 0,
                "events_seen": 0}
    monkeypatch.setattr(Session, "run_live", _ok)
    rc = cli._run_paper(argparse.Namespace(
        config=str(cfg_path), duration="60s",
        run_id="res-1", resume=True))
    assert rc == 0, capsys.readouterr().err
    assert seen["symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert "resumed universe" in capsys.readouterr().out


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
