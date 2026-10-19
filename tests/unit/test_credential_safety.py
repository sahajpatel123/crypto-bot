"""F2.5: credential safety — env/0600-file keys, permission checks."""
from __future__ import annotations

import json
import os
from pathlib import Path


def _write_key_file(path: Path, mode=0o600) -> Path:
    path.write_text(json.dumps({"api_key": "K", "api_secret": "S"}))
    os.chmod(path, mode)
    return path


def test_key_file_0600_accepted(tmp_path, monkeypatch):
    from cryptobot.cli import load_api_keys

    monkeypatch.delenv("CRYPTOBOT_API_KEY", raising=False)
    monkeypatch.delenv("CRYPTOBOT_API_SECRET", raising=False)
    key_file = _write_key_file(tmp_path / "keys.json", 0o600)
    key, secret = load_api_keys("CRYPTOBOT_API_KEY",
                                "CRYPTOBOT_API_SECRET",
                                key_file=str(key_file))
    assert (key, secret) == ("K", "S")


def test_key_file_group_readable_refused(tmp_path, monkeypatch):
    import pytest

    from cryptobot.cli import load_api_keys

    monkeypatch.delenv("CRYPTOBOT_API_KEY", raising=False)
    monkeypatch.delenv("CRYPTOBOT_API_SECRET", raising=False)
    key_file = _write_key_file(tmp_path / "keys.json", 0o640)
    with pytest.raises(ValueError, match="0600|permissions"):
        load_api_keys("CRYPTOBOT_API_KEY", "CRYPTOBOT_API_SECRET",
                      key_file=str(key_file))


def test_env_wins_over_missing_file(monkeypatch):
    from cryptobot.cli import load_api_keys

    monkeypatch.setenv("CRYPTOBOT_API_KEY", "EK")
    monkeypatch.setenv("CRYPTOBOT_API_SECRET", "ES")
    key, secret = load_api_keys("CRYPTOBOT_API_KEY",
                                "CRYPTOBOT_API_SECRET",
                                key_file="/nonexistent/keys.json")
    assert (key, secret) == ("EK", "ES")


def test_missing_everywhere_raises(monkeypatch):
    import pytest

    from cryptobot.cli import load_api_keys

    monkeypatch.delenv("CRYPTOBOT_API_KEY", raising=False)
    monkeypatch.delenv("CRYPTOBOT_API_SECRET", raising=False)
    monkeypatch.delenv("CRYPTOBOT_KEY_FILE", raising=False)
    with pytest.raises(ValueError, match="[Cc]redential"):
        load_api_keys("CRYPTOBOT_API_KEY", "CRYPTOBOT_API_SECRET")


def test_restrictions_deny_withdrawals():
    from cryptobot.adapters.binance_live import check_api_restrictions

    ok, detail = check_api_restrictions(
        {"enableWithdrawals": False, "enableFutures": True,
         "ipRestrict": True})
    assert ok is True, detail
    ok, detail = check_api_restrictions(
        {"enableWithdrawals": True, "enableFutures": True})
    assert ok is False and "withdraw" in detail.lower()
    ok, detail = check_api_restrictions(
        {"enableWithdrawals": False, "enableFutures": False})
    assert ok is False and "futures" in detail.lower()


def test_restrictions_unavailable_is_manual():
    from cryptobot.adapters.binance_live import check_api_restrictions

    ok, detail = check_api_restrictions(None)
    assert ok is False
    assert "manual" in detail.lower()


def test_fetch_restrictions_uses_injected_http():
    from cryptobot.adapters.binance_live import fetch_api_restrictions

    calls = []

    def _fake_http(url, headers, timeout_s):
        calls.append((url, headers))
        assert "signature=" in url
        assert headers["X-MBX-APIKEY"] == "K"
        return {"enableWithdrawals": False, "enableFutures": True}

    doc = fetch_api_restrictions("K", "S", http_get=_fake_http)
    assert doc["enableFutures"] is True
    assert calls and calls[0][0].startswith("https://api.binance.com/")
