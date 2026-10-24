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
              "max_dd_bps": 100.0, "family_size": 1, "strategies": ["HX"]}
    doc = verdict_document(hypothesis="HX", result=result,
                           config_path="configs/paper.toml",
                           data_manifest="trades.jsonl",
                           code_commit=cli._git_head() or "test")
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


def test_gate_binds_strategies_and_commit(tmp_path):
    gate = json.loads(_gate(tmp_path).read_text())
    assert gate["strategies"] == ["HX"]
    assert gate["checks"]["verdict_names_strategies"] is True
    assert cli._commit_matches(gate["code_commit"], gate["code_commit"])
    assert not cli._commit_matches("unknown", "abc123")
    assert not cli._commit_matches("abc123", "")


def test_gate_no_go_when_verdict_names_no_strategy(tmp_path):
    ev = _evidence(tmp_path)
    doc = json.loads(ev["verdict"].read_text())
    doc.pop("document_sha256")
    doc["strategies"] = []
    import hashlib
    doc["document_sha256"] = hashlib.sha256(
        json.dumps(doc, sort_keys=True).encode()).hexdigest()
    ev["verdict"].write_text(json.dumps(doc) + "\n")
    out = tmp_path / "gate.json"
    rc = cli.cmd_gate(argparse.Namespace(
        verdict_json=str(ev["verdict"]), drill_json=str(ev["drill"]),
        latency_json=str(ev["latency"]), out=str(out)))
    assert rc == 2


def _armed_prod(tmp_path, monkeypatch):
    from tests.unit.test_cli_readiness import (
        _StubLiveEngine, _prod_config, _stub_venue_status)

    monkeypatch.setenv("CRYPTOBOT_API_KEY", "k")
    monkeypatch.setenv("CRYPTOBOT_API_SECRET", "s")
    _StubLiveEngine.status = _stub_venue_status()
    cfg_path = Path(_prod_config(tmp_path))
    cfg_path.write_text(cfg_path.read_text().replace(
        "allow_live_submission = false", "allow_live_submission = true"))
    gate_path = _gate(tmp_path)
    gate = json.loads(gate_path.read_text())
    armed_path = tmp_path / "armed.json"
    armed_path.write_text(json.dumps(
        {"armed": True, "capital_usdt": 100.0, "max_daily_loss": 5.0,
         "canary_trades": 10, "gate_sha256": gate["gate_sha256"]}))
    return cfg_path, gate_path, armed_path


def test_prod_refuses_strategies_without_verdict(tmp_path, monkeypatch, capsys):
    """A GO gate for HX never authorises the config's S1-S5 live."""
    from tests.unit.test_cli_readiness import _stub_factory

    cfg_path, gate_path, armed_path = _armed_prod(tmp_path, monkeypatch)
    rc = cli._run_prod(argparse.Namespace(
        config=str(cfg_path), run_id="prod-armed-2",
        gate_json=str(gate_path), armed_json=str(armed_path)), _stub_factory)
    assert rc == 2
    assert "have no PASS verdict behind this gate" in capsys.readouterr().err


def test_armed_daily_loss_tightens_risk_stops(tmp_path):
    from cryptobot.app.config import load_config
    from cryptobot.app.session import Session
    from cryptobot.app.store import RunStore

    config = load_config("configs/paper.toml")
    store = RunStore(tmp_path / "db.sqlite")
    session = Session(config, store, tmp_path / "run", "armed-limits-1",
                      pid=1)
    base = session.policy.config
    session.apply_armed_limits(capital_usdt=200.0, max_daily_loss_usdt=1.0,
                               canary_trades=10, equity_usdt=200.0)
    cfg = session.policy.config
    assert cfg.emergency_stop_pct == 1.0 / 200.0 < base.emergency_stop_pct
    assert cfg.operating_stop_pct < cfg.emergency_stop_pct
    assert session.armed_capital_usdt == 200.0
    # Resume (no venue seed) uses the 1.5x ceiling: never looser.
    session.apply_armed_limits(capital_usdt=200.0, max_daily_loss_usdt=1.0,
                               canary_trades=10)
    assert session.policy.config.emergency_stop_pct == 1.0 / 300.0
