"""Live launch wiring: gate/arm binding, prod arming layers, canary,
stale-cache hold, liquidation gate (all offline, stubbed venue)."""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptobot import cli
from cryptobot.research.verdict import verdict_document


def _pass_verdict(tmp_path: Path) -> Path:
    result = {"verdict": "PASS", "n_trades": 400,
              "expectancy_bps": 12.0, "expectancy_adverse_bps": 4.0,
              "ci95": [2.0, 20.0], "nonneg_day_frac": 0.7,
              "max_dd_bps": 100.0, "family_size": 1}
    doc = verdict_document(hypothesis="HX", result=result,
                           config_path="configs/paper.toml",
                           data_manifest="trades.jsonl",
                           code_commit="test")
    path = tmp_path / "verdict.json"
    path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    return path


def _evidence(tmp_path: Path) -> dict[str, Path]:
    drill = tmp_path / "drill.json"
    drill.write_text(json.dumps({"verdict": "PASS"}) + "\n")
    latency = tmp_path / "latency.json"
    latency.write_text(json.dumps(
        {"verdict": "PASS", "ws_p99_ms": 120.0, "drop_rate": 0.0005,
         "rest_rtt_ms": 40.0}) + "\n")
    return {"verdict": _pass_verdict(tmp_path), "drill": drill,
            "latency": latency}


def _gate(tmp_path: Path) -> Path:
    ev = _evidence(tmp_path)
    out = tmp_path / "gate.json"
    rc = cli.cmd_gate(argparse.Namespace(
        verdict_json=str(ev["verdict"]), drill_json=str(ev["drill"]),
        latency_json=str(ev["latency"]), out=str(out)))
    assert rc == 0
    return out


def test_gate_go_binds_evidence_hashes(tmp_path):
    gate = json.loads(_gate(tmp_path).read_text())
    assert gate["gate"] == "GO"
    assert all(gate["evidence_sha256"].values())
    assert cli._gate_doc_valid(gate)


def test_gate_rest_only_latency_is_no_go(tmp_path):
    ev = _evidence(tmp_path)
    ev["latency"].write_text(json.dumps(
        {"verdict": "MEASURED-REST-ONLY", "rest_rtt_ms": 40.0}) + "\n")
    out = tmp_path / "gate.json"
    rc = cli.cmd_gate(argparse.Namespace(
        verdict_json=str(ev["verdict"]), drill_json=str(ev["drill"]),
        latency_json=str(ev["latency"]), out=str(out)))
    assert rc == 2
    assert json.loads(out.read_text())["gate"] == "NO-GO"


def test_gate_tampered_verdict_is_no_go(tmp_path):
    ev = _evidence(tmp_path)
    doc = json.loads(ev["verdict"].read_text())
    doc["expectancy_bps"] = 999.0  # digest no longer matches
    ev["verdict"].write_text(json.dumps(doc) + "\n")
    out = tmp_path / "gate.json"
    rc = cli.cmd_gate(argparse.Namespace(
        verdict_json=str(ev["verdict"]), drill_json=str(ev["drill"]),
        latency_json=str(ev["latency"]), out=str(out)))
    assert rc == 2


def test_arm_refuses_without_tty_and_binds_gate(tmp_path, monkeypatch):
    gate_path = _gate(tmp_path)
    monkeypatch.setenv("CRYPTOBOT_ARM_ACK", cli.ARM_ACK_PHRASE)
    out = tmp_path / "armed.json"
    rc = cli.cmd_arm(argparse.Namespace(
        capital_usdt=100.0, max_daily_loss=5.0,
        gate_json=str(gate_path), out=str(out)))
    assert rc == 2 and not out.exists()  # pytest stdin is not a TTY


def test_arm_rejects_bad_capital(tmp_path, monkeypatch):
    gate_path = _gate(tmp_path)
    monkeypatch.setenv("CRYPTOBOT_ARM_ACK", cli.ARM_ACK_PHRASE)
    rc = cli.cmd_arm(argparse.Namespace(
        capital_usdt=100.0, max_daily_loss=500.0,
        gate_json=str(gate_path), out=str(tmp_path / "armed.json")))
    assert rc == 2


def test_armed_binding_must_match_gate(tmp_path):
    gate = json.loads(_gate(tmp_path).read_text())
    armed = {"armed": True, "capital_usdt": 100.0, "max_daily_loss": 5.0,
             "canary_trades": 10, "gate_sha256": gate["gate_sha256"]}
    assert cli._armed_doc_valid(armed, gate)
    armed["gate_sha256"] = "0" * 64
    assert not cli._armed_doc_valid(armed, gate)


def test_expired_gate_invalid(tmp_path):
    gate = json.loads(_gate(tmp_path).read_text())
    gate["expires_utc"] = (datetime.now(UTC)
                           - timedelta(hours=1)).isoformat()
    assert not cli._gate_doc_valid(gate)


def test_prod_armed_layers_refuse_in_order(tmp_path, monkeypatch, capsys):
    """Switch ON but no gate/armed: prod still refuses (never trades)."""
    from tests.unit.test_cli_readiness import (
        _StubLiveEngine, _prod_config, _stub_factory, _stub_venue_status)

    monkeypatch.setenv("CRYPTOBOT_API_KEY", "k")
    monkeypatch.setenv("CRYPTOBOT_API_SECRET", "s")
    _StubLiveEngine.status = _stub_venue_status()
    cfg_path = Path(_prod_config(tmp_path))
    text = cfg_path.read_text().replace(
        "allow_live_submission = false", "allow_live_submission = true")
    cfg_path.write_text(text)
    rc = cli._run_prod(argparse.Namespace(
        config=str(cfg_path), run_id="prod-armed-1"), _stub_factory)
    assert rc == 2
    assert "need a valid GO gate" in capsys.readouterr().err
