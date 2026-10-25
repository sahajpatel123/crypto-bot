"""`cryptobot keys check` and the prod permission gate, all offline.

The transport is injected everywhere: the point is that each venue answer
maps to a specific PASS/FAIL row and a specific exit code, and that a prod
start refuses on a violating key before the order path exists.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode

import pytest

from cryptobot import cli
from cryptobot.adapters.binance_live import VenueHttpError, sign_params
from cryptobot.ops import credentials as cred
from cryptobot.ops import keys

API_KEY = ("K3yS3nt1nel" * 6)[:32]
API_SECRET = ("S3cretS3nt1nel" * 6)[:64]
REPO_ROOT = Path(__file__).resolve().parents[2]

CLEAN = {
    "ipRestrict": True,
    "enableReading": True,
    "enableWithdrawals": False,
    "enableInternalTransfer": False,
    "permitsUniversalTransfer": False,
    "enableMargin": False,
    "enableSpotAndMarginTrading": False,
    "enableFutures": True,
}


class FakeTransport:
    """The venue's answer, or the failure it raises, without a socket."""

    def __init__(self, document=None, error=None):
        self.document = dict(document or {})
        self.error = error
        self.calls: list[dict] = []

    def request(self, method, path, params, headers):
        self.calls.append({"method": method, "path": path,
                           "params": dict(params), "headers": dict(headers)})
        if self.error is not None:
            raise self.error
        return dict(self.document)


@pytest.fixture
def no_credentials(monkeypatch):
    for name in cred.SECRET_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def env_credentials(monkeypatch):
    monkeypatch.setenv(cred.API_KEY_ENV, API_KEY)
    monkeypatch.setenv(cred.API_SECRET_ENV, API_SECRET)


def _args(**kwargs) -> argparse.Namespace:
    base = {"market": "futures", "require_ip": True, "base_url": None,
            "json": False, "env": None}
    base.update(kwargs)
    return argparse.Namespace(**base)


def _report(document, **kwargs):
    return keys.check_permissions(API_KEY, API_SECRET,
                                  transport=FakeTransport(document), **kwargs)


def _row(report, name):
    for row in report.rows:
        if row.name == name:
            return row
    raise AssertionError(f"no row {name} in {[r.name for r in report.rows]}")


# ---------------------------------------------------------------------------
# The clean case
# ---------------------------------------------------------------------------
def test_clean_restricted_key_passes_and_reports_every_permission():
    report = _report(CLEAN)
    assert report.exit_code == keys.EXIT_PASS
    assert report.verdict == "PASS"
    assert report.outcome == keys.OUTCOME_PASS
    for name in ("api-reading", "withdrawals-disabled",
                 "internal-transfer-disabled", "universal-transfer-disabled",
                 "futures-trading-enabled", "ip-restrict"):
        assert _row(report, name).status == "PASS", name
    # The full permission set is reported, not only the rules checked.
    assert _row(report, "enableMargin").status == "INFO"
    assert _row(report, "enableSpotAndMarginTrading").status == "INFO"


def test_request_is_signed_by_the_existing_helper():
    transport = FakeTransport(CLEAN)
    keys.check_permissions(API_KEY, API_SECRET, transport=transport,
                           now_ms=1_700_000_000_000)
    call = transport.calls[0]
    assert call["method"] == "GET"
    assert call["path"] == keys.RESTRICTIONS_PATH
    assert call["headers"] == {"X-MBX-APIKEY": API_KEY}
    params = call["params"]
    assert params["timestamp"] == 1_700_000_000_000
    assert params["recvWindow"] == keys.RECV_WINDOW_MS
    unsigned = {k: v for k, v in params.items() if k != "signature"}
    expected = hmac.new(API_SECRET.encode("utf-8"),
                        urlencode(unsigned).encode("utf-8"),
                        hashlib.sha256).hexdigest()
    assert params["signature"] == expected
    # The same helper the order path uses, not a second implementation.
    assert sign_params(API_SECRET.encode("utf-8"), {},
                       timestamp_ms=1_700_000_000_000,
                       recv_window_ms=keys.RECV_WINDOW_MS) == params


# ---------------------------------------------------------------------------
# One test per violation
# ---------------------------------------------------------------------------
def test_withdrawals_enabled_fails():
    report = _report({**CLEAN, "enableWithdrawals": True})
    assert report.verdict == "FAIL"
    assert report.exit_code == keys.EXIT_VIOLATION
    assert report.outcome == keys.OUTCOME_VIOLATION
    assert _row(report, "withdrawals-disabled").status == "FAIL"


def test_internal_transfer_enabled_fails():
    report = _report({**CLEAN, "enableInternalTransfer": True})
    assert report.exit_code == keys.EXIT_VIOLATION
    assert _row(report, "internal-transfer-disabled").status == "FAIL"


def test_universal_transfer_enabled_fails():
    report = _report({**CLEAN, "permitsUniversalTransfer": True})
    assert report.exit_code == keys.EXIT_VIOLATION
    assert _row(report, "universal-transfer-disabled").status == "FAIL"


def test_unrestricted_ip_fails_by_default():
    report = _report({**CLEAN, "ipRestrict": False})
    assert report.exit_code == keys.EXIT_VIOLATION
    assert _row(report, "ip-restrict").status == "FAIL"
    assert "NOT IP-restricted" in _row(report, "ip-restrict").detail


def test_unrestricted_ip_is_reported_when_not_required():
    report = _report({**CLEAN, "ipRestrict": False}, require_ip=False)
    assert report.exit_code == keys.EXIT_PASS
    assert _row(report, "ip-restrict").status == "INFO"


def test_futures_disabled_fails():
    report = _report({**CLEAN, "enableFutures": False})
    assert report.exit_code == keys.EXIT_VIOLATION
    assert _row(report, "futures-trading-enabled").status == "FAIL"


def test_spot_market_requires_spot_permission():
    spot_only = {**CLEAN, "enableSpotAndMarginTrading": True,
                 "enableFutures": False}
    assert _report(spot_only, market="spot").exit_code == keys.EXIT_PASS
    assert _report(spot_only, market="futures").exit_code == keys.EXIT_VIOLATION
    assert _report(spot_only, market="both").exit_code == keys.EXIT_VIOLATION


def test_reading_disabled_fails():
    report = _report({**CLEAN, "enableReading": False})
    assert report.exit_code == keys.EXIT_VIOLATION
    assert _row(report, "api-reading").status == "FAIL"


def test_unknown_market_is_refused():
    with pytest.raises(ValueError):
        keys.evaluate_restrictions(CLEAN, market="options")


# ---------------------------------------------------------------------------
# Auth and network failures are never a pass
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("error", [
    VenueHttpError(401, -2015, "Invalid API-key, IP, or permissions for action."),
    VenueHttpError(403, -2015, "Invalid API-key"),
    VenueHttpError(400, -2015, "Invalid API-key, IP, or permissions for action."),
    VenueHttpError(401, -2014, "API-key format invalid."),
])
def test_invalid_key_is_an_auth_failure(error):
    report = keys.check_permissions(
        API_KEY, API_SECRET, transport=FakeTransport(error=error))
    assert report.outcome == keys.OUTCOME_AUTH
    assert report.exit_code == keys.EXIT_UNAVAILABLE
    assert report.verdict == "FAIL"
    assert all(row.status != "PASS" for row in report.rows)


def test_network_error_is_not_a_pass():
    report = keys.check_permissions(
        API_KEY, API_SECRET,
        transport=FakeTransport(error=VenueHttpError(0, None, "transport")))
    assert report.outcome == keys.OUTCOME_NETWORK
    assert report.exit_code == keys.EXIT_UNAVAILABLE
    assert report.verdict == "FAIL"


def test_unexpected_exception_is_not_a_pass():
    report = keys.check_permissions(
        API_KEY, API_SECRET,
        transport=FakeTransport(error=RuntimeError("boom")))
    assert report.exit_code == keys.EXIT_UNAVAILABLE
    assert report.verdict == "FAIL"


# ---------------------------------------------------------------------------
# The command itself: output and exit codes
# ---------------------------------------------------------------------------
def test_run_check_prints_a_table_and_no_secret(env_credentials, capsys):
    rc = keys.run_check(_args(), transport=FakeTransport(CLEAN))
    out = capsys.readouterr().out
    assert rc == 0
    assert "keys check: PASS" in out
    assert "[PASS] withdrawals-disabled" in out
    assert API_KEY not in out and API_SECRET not in out


def test_run_check_prints_fail_table(env_credentials, capsys):
    rc = keys.run_check(_args(),
                        transport=FakeTransport({**CLEAN,
                                                 "enableWithdrawals": True}))
    out = capsys.readouterr().out
    assert rc == keys.EXIT_VIOLATION
    assert "keys check: FAIL" in out
    assert "[FAIL] withdrawals-disabled" in out


def test_run_check_json_has_no_secret(env_credentials, capsys):
    rc = keys.run_check(_args(json=True),
                        transport=FakeTransport({**CLEAN,
                                                 "enableFutures": False}))
    payload = json.loads(capsys.readouterr().out)
    assert rc == keys.EXIT_VIOLATION
    assert payload["verdict"] == "FAIL"
    assert payload["exit_code"] == keys.EXIT_VIOLATION
    assert any(r["name"] == "futures-trading-enabled"
               and r["status"] == "FAIL" for r in payload["rows"])
    assert API_KEY not in json.dumps(payload)
    assert API_SECRET not in json.dumps(payload)


def test_missing_credentials_is_not_a_pass(no_credentials, capsys, tmp_path):
    rc = keys.run_check(_args(env=str(tmp_path / "absent.env")),
                        transport=FakeTransport(CLEAN))
    out = capsys.readouterr().out
    assert rc == keys.EXIT_UNAVAILABLE
    assert "missing-credentials" in out
    assert "keys check: PASS" not in out


def test_cli_wires_the_check_and_its_exit_codes(env_credentials, monkeypatch,
                                               capsys, tmp_path):
    monkeypatch.setattr(keys, "make_transport",
                        lambda base_url=None: FakeTransport(
                            {**CLEAN, "enableWithdrawals": True}))
    rc = cli.main(["keys", "check", "--env", str(tmp_path / "absent.env")])
    out = capsys.readouterr().out
    assert rc == keys.EXIT_VIOLATION
    assert "[FAIL] withdrawals-disabled" in out

    monkeypatch.setattr(keys, "make_transport",
                        lambda base_url=None: FakeTransport(CLEAN))
    rc = cli.main(["keys", "check", "--env", str(tmp_path / "absent.env"),
                   "--market", "futures"])
    assert rc == keys.EXIT_PASS


def test_cli_auth_failure_exits_three(env_credentials, monkeypatch, capsys,
                                      tmp_path):
    monkeypatch.setattr(
        keys, "make_transport",
        lambda base_url=None: FakeTransport(
            error=VenueHttpError(401, -2015, "Invalid API-key")))
    rc = cli.main(["keys", "check", "--env", str(tmp_path / "absent.env")])
    out = capsys.readouterr().out
    assert rc == keys.EXIT_UNAVAILABLE
    assert "auth-failure" in out
    assert "keys check: PASS" not in out


# ---------------------------------------------------------------------------
# `keys set` / `keys status` through the CLI
# ---------------------------------------------------------------------------
def test_cli_set_from_stdin_then_status(monkeypatch, capsys, tmp_path):
    env_path = tmp_path / ".env"
    monkeypatch.setattr("sys.stdin",
                        __import__("io").StringIO(f"{API_KEY}\n{API_SECRET}\n"))
    rc = cli.main(["keys", "set", "--from-stdin", "--env", str(env_path)])
    captured = capsys.readouterr()
    assert rc == 0
    assert API_KEY not in captured.out + captured.err
    assert API_SECRET not in captured.out + captured.err
    assert env_path.stat().st_mode & 0o777 == 0o600

    monkeypatch.delenv(cred.API_KEY_ENV, raising=False)
    monkeypatch.delenv(cred.API_SECRET_ENV, raising=False)
    rc = cli.main(["keys", "status", "--env", str(env_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "CRYPTOBOT_API_KEY: present (source=dotenv)" in out
    assert API_KEY not in out and API_SECRET not in out


def test_cli_status_is_non_zero_when_credentials_are_missing(
        no_credentials, capsys, tmp_path):
    rc = cli.main(["keys", "status", "--env", str(tmp_path / "absent.env")])
    out = capsys.readouterr().out
    assert rc != 0
    assert "MISSING" in out


def test_cli_status_json_never_leaks_a_value(env_credentials, capsys, tmp_path):
    rc = cli.main(["keys", "status", "--json", "--env",
                   str(tmp_path / "absent.env")])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0  # present, from the environment
    assert payload["complete"] is True
    assert {c["source"] for c in payload["credentials"]} == {
        cred.SOURCE_ENVIRONMENT}
    dumped = json.dumps(payload)
    assert API_KEY not in dumped and API_SECRET not in dumped
    assert API_KEY[:8] not in dumped and API_SECRET[-8:] not in dumped


def test_cli_set_refuses_a_tracked_path(monkeypatch, capsys, tmp_path):
    import io
    import subprocess
    monkeypatch.setattr("sys.stdin",
                        io.StringIO(f"{API_KEY}\n{API_SECRET}\n"))
    tracked = tmp_path / "tracked.env"
    tracked.write_text("x=1\n")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "tracked.env"],
                   check=True)
    rc = cli.main(["keys", "set", "--from-stdin", "--env", str(tracked)])
    err = capsys.readouterr().err
    assert rc != 0
    assert "REFUSED" in err
    assert "tracks this file" in err
    assert tracked.read_text() == "x=1\n"


def test_parser_registers_the_keys_subcommands():
    parser = cli.build_parser()
    set_args = parser.parse_args(["keys", "set", "--backend", "keychain",
                                  "--env", "/tmp/x.env"])
    assert set_args.func is keys.cmd_keys_set
    assert set_args.backend == "keychain"
    status_args = parser.parse_args(["keys", "status", "--json"])
    assert status_args.func is keys.cmd_keys_status
    check_args = parser.parse_args(["keys", "check", "--no-require-ip",
                                    "--market", "both"])
    assert check_args.func is keys.cmd_keys_check
    assert check_args.require_ip is False
    assert check_args.market == "both"
    default_check = parser.parse_args(["keys", "check"])
    assert default_check.require_ip is True
    assert default_check.market == "futures"


# ---------------------------------------------------------------------------
# Profiles: demo keys are checked against the demo host, prod against spot
# ---------------------------------------------------------------------------
def test_demo_profile_targets_the_demo_host(monkeypatch, tmp_path, capsys):
    from cryptobot.adapters.binance_live import DEMO_FAPI_URL
    # The demo host constant must stay the one configs/demo.toml trades on.
    assert keys.DEMO_REST_URL == DEMO_FAPI_URL
    assert keys.PROFILE_BASE_URLS[cred.PROFILE_PROD] == keys.SPOT_REST_URL
    assert keys.PROFILE_BASE_URLS[cred.PROFILE_DEMO] == keys.DEMO_REST_URL
    monkeypatch.setenv(cred.DEMO_KEY_ENV, API_KEY)
    monkeypatch.setenv(cred.DEMO_SECRET_ENV, API_SECRET)
    transport = FakeTransport(CLEAN)
    rc = keys.run_check(_args(profile="demo", json=True,
                              env=str(tmp_path / "absent.env")),
                        transport=transport)
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["profile"] == "demo"
    assert payload["base_url"] == DEMO_FAPI_URL
    assert transport.calls and API_KEY not in json.dumps(payload)


def test_prod_profile_targets_the_spot_host(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(cred.API_KEY_ENV, API_KEY)
    monkeypatch.setenv(cred.API_SECRET_ENV, API_SECRET)
    transport = FakeTransport(CLEAN)
    rc = keys.run_check(_args(json=True, env=str(tmp_path / "absent.env")),
                        transport=transport)
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["profile"] == "prod"
    assert payload["base_url"] == keys.SPOT_REST_URL


def test_demo_profile_reports_missing_demo_credentials(monkeypatch, tmp_path,
                                                       capsys):
    # Prod keys present, demo profile asked for: still a clear miss.
    monkeypatch.setenv(cred.API_KEY_ENV, API_KEY)
    monkeypatch.setenv(cred.API_SECRET_ENV, API_SECRET)
    rc = keys.run_check(_args(profile="demo",
                              env=str(tmp_path / "absent.env")),
                        transport=FakeTransport(CLEAN))
    out = capsys.readouterr().out
    assert rc == keys.EXIT_UNAVAILABLE
    assert cred.DEMO_KEY_ENV in out
    assert "keys check: PASS" not in out


def test_parser_exposes_the_profile_flag():
    parser = cli.build_parser()
    assert parser.parse_args(["keys", "set"]).profile == cred.PROFILE_PROD
    assert parser.parse_args(
        ["keys", "set", "--profile", "demo"]).profile == cred.PROFILE_DEMO
    assert parser.parse_args(
        ["keys", "status", "--profile", "demo"]).profile == cred.PROFILE_DEMO
    check = parser.parse_args(["keys", "check", "--profile", "demo"])
    assert check.profile == cred.PROFILE_DEMO
    assert check.market == "futures"


def test_cli_set_demo_profile_writes_only_demo_names(monkeypatch, capsys,
                                                     tmp_path):
    import io
    env_path = tmp_path / ".env"
    monkeypatch.setattr("sys.stdin", io.StringIO(f"{API_KEY}\n{API_SECRET}\n"))
    rc = cli.main(["keys", "set", "--from-stdin", "--profile", "demo",
                   "--env", str(env_path)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "profile=demo" in captured.out
    text = env_path.read_text()
    assert cred.DEMO_KEY_ENV in text
    assert cred.API_KEY_ENV not in text  # prod names untouched
    assert API_KEY not in captured.out + captured.err
    assert API_SECRET not in captured.out + captured.err


def test_demo_drill_refuses_when_only_prod_keys_exist(tmp_path):
    """The owner flow: keys set --profile prod must not unlock the drill."""
    env = {k: v for k, v in __import__("os").environ.items()
           if k not in cred.SECRET_ENV_NAMES
           and k not in ("BINANCE_DEMO_KEY", "BINANCE_DEMO_SECRET")}
    env[cred.API_KEY_ENV] = API_KEY
    env[cred.API_SECRET_ENV] = API_SECRET
    out = tmp_path / "drill.json"
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "demo_drill_live.py"),
         "--out", str(out)],
        cwd=str(REPO_ROOT), env=env, capture_output=True, text=True,
        check=False, timeout=120)
    report = json.loads(out.read_text())
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert report["verdict"] == "BLOCKED"
    detail = report["steps"][0]["detail"]
    assert cred.DEMO_KEY_ENV in detail
    assert cred.DEMO_SECRET_ENV in detail
    assert "keys set --profile demo" in detail
    assert API_KEY not in json.dumps(report) + proc.stdout + proc.stderr


def test_demo_drill_accepts_the_legacy_demo_env(tmp_path):
    env = {k: v for k, v in __import__("os").environ.items()
           if k not in cred.SECRET_ENV_NAMES}
    env["BINANCE_DEMO_KEY"] = API_KEY
    env["BINANCE_DEMO_SECRET"] = API_SECRET
    out = tmp_path / "drill.json"
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "demo_drill_live.py"),
         "--out", str(out)],
        cwd=str(REPO_ROOT), env=env, capture_output=True, text=True,
        check=False, timeout=120)
    report = json.loads(out.read_text())
    # Read-only without --execute-orders: credentials resolved, still BLOCKED.
    assert proc.returncode == 2
    assert report["steps"][0]["step"] == "read-only"
    assert report["steps"][0]["status"] == "PASS"
    assert API_KEY not in json.dumps(report)


# ---------------------------------------------------------------------------
# The prod gate: refused before the order path exists
# ---------------------------------------------------------------------------
def _prod_args(tmp_path):
    from tests.unit.test_cli_readiness import _prod_config
    return argparse.Namespace(config=_prod_config(tmp_path), run_id=None)


def _prod_stubs():
    from tests.unit.test_cli_readiness import (
        _stub_factory,
        _stub_venue_status,
        _StubLiveEngine,
    )
    _StubLiveEngine.status = _stub_venue_status()
    return _stub_factory


def test_prod_refuses_a_violating_permission_document(monkeypatch, tmp_path,
                                                      capsys):
    monkeypatch.setenv(cred.API_KEY_ENV, "k")  # the shared stub's contract
    monkeypatch.setenv(cred.API_SECRET_ENV, "s")
    factory = _prod_stubs()
    transport = FakeTransport({**CLEAN, "enableWithdrawals": True})
    rc = cli._run_prod(_prod_args(tmp_path), factory,
                       _permission_transport=transport)
    captured = capsys.readouterr()
    assert rc != 0
    assert "credential permission check" in captured.err
    assert "[FAIL] withdrawals-disabled" in captured.out
    assert transport.calls  # the venue was actually asked


def test_prod_refuses_an_unrestricted_key(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(cred.API_KEY_ENV, "k")
    monkeypatch.setenv(cred.API_SECRET_ENV, "s")
    rc = cli._run_prod(
        _prod_args(tmp_path), _prod_stubs(),
        _permission_transport=FakeTransport({**CLEAN, "ipRestrict": False}))
    captured = capsys.readouterr()
    assert rc != 0
    assert "[FAIL] ip-restrict" in captured.out
    assert "credential permission check" in captured.err


def test_prod_refuses_when_the_key_cannot_authenticate(monkeypatch, tmp_path,
                                                       capsys):
    monkeypatch.setenv(cred.API_KEY_ENV, "k")
    monkeypatch.setenv(cred.API_SECRET_ENV, "s")
    rc = cli._run_prod(
        _prod_args(tmp_path), _prod_stubs(),
        _permission_transport=FakeTransport(
            error=VenueHttpError(401, -2015, "Invalid API-key")))
    captured = capsys.readouterr()
    assert rc != 0
    assert "auth-failure" in captured.err
    assert "REAL orders" not in captured.out


def test_prod_clean_document_does_not_block_the_route(monkeypatch, tmp_path,
                                                      capsys):
    # A clean key passes the gate; the route then refuses at the arming
    # layer exactly as before (the permission check never weakens it).
    monkeypatch.setenv(cred.API_KEY_ENV, "k")
    monkeypatch.setenv(cred.API_SECRET_ENV, "s")
    rc = cli._run_prod(_prod_args(tmp_path), _prod_stubs(),
                       _permission_transport=FakeTransport(CLEAN))
    captured = capsys.readouterr()
    assert rc == 2  # the arming layer still refuses, gate or no gate
    assert "[PASS] futures-trading-enabled" in captured.out
    assert "allow_live_submission is false" in captured.err
    assert "credential permission check" not in captured.err
