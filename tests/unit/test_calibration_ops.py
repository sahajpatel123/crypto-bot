"""F2.2–F2.6: calibration, fixtures, credential safety, clock, host-check."""
from __future__ import annotations

import json

import pytest

from cryptobot.research.calibration import (
    FillSample,
    fit_cost_model,
    parse_fills,
    relaxations,
    update_cost_model,
)
from cryptobot.risk.clock_guard import ClockGuard
from cryptobot.security import CredentialError, credential_readiness, load_credentials


def _rows():
    return [
        {"side": "BUY", "expected_price": 100.0, "fill_price": 100.05,
         "qty": 1.0, "latency_ms": 100, "fee_bps": 5.0,
         "spread_bps": 2.0, "day": "d1"},
        {"side": "SELL", "expected_price": 100.0, "fill_price": 99.98,
         "qty": 1.0, "latency_ms": 200, "fee_bps": 6.0,
         "spread_bps": 3.0, "day": "d2"},
    ]


def test_fit_cost_model_is_pessimistic_and_versioned():
    samples = parse_fills(_rows())
    model = fit_cost_model(samples)
    assert model["samples"] == 2
    # BUY 5bps adverse + SELL 2bps adverse => mean 3.5bps.
    assert model["slippage_bps"] == pytest.approx(3.5)
    assert model["latency_ms"] == pytest.approx(200)
    assert model["taker_bps"] == pytest.approx(6.0)
    assert model["spread_bps"] == pytest.approx(3.0)
    first = update_cost_model(None, model)
    assert first["version"] == 1
    second = update_cost_model(first, {**model, "slippage_bps": 5.0})
    assert second["version"] == 2
    assert second["relaxations"] == []


def test_cost_relaxation_requires_matching_pass_verdict(tmp_path):
    samples = parse_fills(_rows())
    model = fit_cost_model(samples)
    first = update_cost_model(None, model)
    with pytest.raises(ValueError, match="relaxation refused"):
        update_cost_model(first, {**model, "slippage_bps": 1.0})
    verdict = tmp_path / "verdict.json"
    verdict.write_text(json.dumps({
        "verdict": "PASS",
        "hashes": {"config_sha256_16": model["config_sha256"][:16]}}))
    allowed = update_cost_model(first, {**model, "slippage_bps": 1.0},
                                verdict_path=verdict)
    assert allowed["approved_by_verdict"] is True
    assert relaxations(first, allowed)


def test_fill_sample_never_credits_favourable_fill():
    s = FillSample(side="BUY", expected_price=100.0, fill_price=99.9,
                   qty=1.0, latency_ms=1, fee_bps=0, funding_bps=0,
                   spread_bps=0)
    assert s.slippage_bps == 0.0


def test_fixtures_ingest_rejects_secrets_and_installs(tmp_path):
    from cryptobot.fixtures import FixtureError, ingest_fixtures

    src = tmp_path / "src"
    src.mkdir()
    (src / "account.json").write_text(json.dumps(
        {"totalWalletBalance": "100", "positions": []}))
    (src / "bad.json").write_text(json.dumps({"apiKey": "do-not-store"}))
    with pytest.raises(FixtureError, match="credential-like"):
        ingest_fixtures(src, tmp_path / "out")
    (src / "bad.json").unlink()
    index = ingest_fixtures(src, tmp_path / "out")
    assert index["fixtures"][0]["provenance"] == "demo-recorded"
    assert (tmp_path / "out" / "index.json").exists()
    assert (tmp_path / "out" / "account.json").exists()


def test_credential_file_mode_enforced(tmp_path):
    p = tmp_path / "secret"
    p.write_text("value")
    p.chmod(0o644)
    with pytest.raises(CredentialError, match="0600"):
        load_credentials(key_env="NOPE", secret_env="NOPE",
                         key_file=str(p), secret_file=str(p))
    p.chmod(0o600)
    key, secret = load_credentials(key_env="NOPE", secret_env="NOPE",
                                   key_file=str(p), secret_file=str(p))
    assert key == secret == "value"
    report = credential_readiness(key_env="NOPE", secret_env="NOPE",
                                  key_file=str(p), secret_file=str(p))
    assert report["verdict"] == "PASS"
    assert "MANUAL" in {r["status"] for r in report["rows"]}


def test_clock_guard_trips_and_stays_tripped():
    guard = ClockGuard(max_skew_ms=250.0)
    assert guard.allows_entries(100.0) is True
    assert guard.allows_entries(251.0) is False
    assert guard.allows_entries(0.0) is False  # latched
    with pytest.raises(ValueError, match="clock:skew"):
        ClockGuard(max_skew_ms=10.0).require(11.0)
    assert ClockGuard(max_skew_ms=250).recv_window_safe_ms(5000) is True
    assert ClockGuard(max_skew_ms=4500).recv_window_safe_ms(5000) is False


def test_host_check_offline_cannot_pass_and_writes_json(tmp_path):
    from cryptobot.ops.host_check import run_host_check

    out = tmp_path / "host.json"
    report = run_host_check(min_free_gb=0.0, check_network=False,
                            out=str(out))
    assert report["verdict"] == "FAIL"
    statuses = {r["check"]: r["status"] for r in report["rows"]}
    assert statuses["venue-rtt"] == "UNKNOWN"
    assert statuses["clock-skew"] == "UNKNOWN"
    assert json.loads(out.read_text())["verdict"] == "FAIL"


def test_host_check_disk_boundary():
    from cryptobot.ops.host_check import run_host_check

    assert run_host_check(min_free_gb=10.0, check_network=False,
                          free_gb=10.0)["rows"][2]["status"] == "PASS"
    assert run_host_check(min_free_gb=10.0, check_network=False,
                          free_gb=9.9)["rows"][2]["status"] == "FAIL"
