"""F4.6/F5.1/F5.2: autopilot transitions, gate evidence, arm refusals."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptobot import cli
from cryptobot.research.autopilot import Autopilot


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "autopilot"
    (root / "dev").mkdir(parents=True)
    (root / "confirm").mkdir(parents=True)
    (root / "paper").mkdir(parents=True)
    return root


def _register(root: Path, prereg: Path, config: Path) -> Autopilot:
    bot = Autopilot(root)
    bot.register("H1", prereg=str(prereg), config_sha256=hashlib.sha256(
        config.read_bytes()).hexdigest(), commit="c1", family_size=6)
    return bot


def _trades(n: int, net: float) -> list[dict]:
    return [{"net_bps": net, "adverse_bps": net - 1.0,
             "day": f"d{i % 20}"} for i in range(n)]


def _write(path: Path, doc: dict) -> None:
    path.write_text(json.dumps(doc))


def test_autopilot_full_path_and_idempotence(tmp_path):
    root = _root(tmp_path)
    prereg = tmp_path / "H1.md"
    prereg.write_text("# H1")
    config = tmp_path / "h1.toml"
    config.write_text("x=1\n")
    bot = _register(root, prereg, config)
    assert bot.run_once()["hypotheses"]["H1"]["state"] == "DEV_EVAL"
    # Idempotent: no state change, no duplicate transition.
    before = len(bot.verify_log())
    assert bot.run_once()["hypotheses"]["H1"]["state"] == "DEV_EVAL"
    assert len(bot.verify_log()) == before

    _write(root / "dev" / "H1.json",
           {"trades": _trades(120, 8.0), "trades_per_day": 10.0})
    assert bot.run_once()["hypotheses"]["H1"]["state"] == "AWAIT_CONFIRM_DATA"
    state = bot.read_state("H1")
    assert state["power"]["status"] == "FEASIBLE"
    assert state["power"]["days_required"] is not None

    _write(root / "confirm" / "H1.json", {"trades": _trades(300, 7.0)})
    assert bot.run_once()["hypotheses"]["H1"]["state"] == "CONFIRM"
    assert bot.run_once()["hypotheses"]["H1"]["state"] == "PASS"
    assert bot.run_once()["hypotheses"]["H1"]["state"] == "PAPER_14D"

    # Fast-forward the paper clock (test-only state edit).
    state = bot.read_state("H1")
    state["paper_started_utc"] = (
        datetime.now(UTC) - timedelta(days=15)).isoformat()
    bot.state_path("H1").write_text(json.dumps(state))
    _write(root / "paper" / "H1.json",
           {"trades": _trades(100, 8.0), "tolerance_bps": 5.0})
    assert bot.run_once()["hypotheses"]["H1"]["state"] == "PAPER_COMPARE"
    assert bot.run_once()["hypotheses"]["H1"]["state"] == "GATE_READY"
    assert bot.verify_log() == []
    assert (root / "reports").exists()


def test_autopilot_kills_failed_dev(tmp_path):
    root = _root(tmp_path)
    prereg = tmp_path / "H1.md"
    prereg.write_text("# H1")
    config = tmp_path / "h1.toml"
    config.write_text("x=1\n")
    bot = _register(root, prereg, config)
    bot.run_once()
    _write(root / "dev" / "H1.json", {"trades": _trades(120, 1.0)})
    assert bot.run_once()["hypotheses"]["H1"]["state"] == "KILLED"
    assert bot.run_once()["hypotheses"]["H1"]["state"] == "KILLED"


def test_autopilot_refuses_synthetic_without_acceptance_flag(tmp_path):
    root = _root(tmp_path)
    prereg = tmp_path / "H1.md"
    prereg.write_text("# H1")
    config = tmp_path / "h1.toml"
    config.write_text("x=1\n")
    bot = _register(root, prereg, config)
    bot.run_once()
    _write(root / "dev" / "H1.json",
           {"trades": _trades(120, 8.0), "provenance": "SYNTHETIC",
            "trades_per_day": 10.0})
    result = bot.run_once()
    assert result["hypotheses"]["H1"]["state"] == "DEV_EVAL"
    assert "synthetic" in result["hypotheses"]["H1"]["blocked"]


def _sign(doc: dict) -> dict:
    """Recompute the verdict document digest over the final body.

    The gate verifies this digest; a fixture that edits a verdict must
    re-sign it or the gate correctly reports tampering.
    """
    body = {k: v for k, v in doc.items() if k != "document_sha256"}
    doc["document_sha256"] = hashlib.sha256(
        json.dumps(body, sort_keys=True).encode()).hexdigest()
    return doc


def _gate_artifacts(tmp_path: Path, *, synthetic=False):
    config = tmp_path / "h1.toml"
    config.write_text("x=1\n")
    cfg_sha = hashlib.sha256(config.read_bytes()).hexdigest()[:16]
    now = datetime.now(UTC).isoformat()
    verdict = _sign({"verdict": "PASS", "data_provenance": "SEALED-CONFIRM",
                     "strategies": ["H1"],
                     "hashes": {"config_sha256_16": cfg_sha,
                                "code_commit": "unknown"}})
    state = {"hypothesis": "H1", "state": "GATE_READY",
             "provenance": "SYNTHETIC" if synthetic else "OBSERVED",
             "config_sha256": cfg_sha + "0" * 48}
    cost = {"version": 1, "created_utc": now}
    host = {"verdict": "PASS", "generated_utc": now}
    drill = {"verdict": "PASS", "created_utc": now}
    latency = {"verdict": "PASS", "p99_feed_age_ms": 100,
               "drop_rate": 0.0}
    hb = {"ts_utc": now, "has_exposure": False}
    names = {"verdict": verdict, "state": state, "cost": cost,
             "host": host, "drill": drill, "latency": latency, "hb": hb}
    paths = {}
    for name, doc in names.items():
        path = tmp_path / f"{name}.json"
        _write(path, doc)
        paths[name] = str(path)
    paths["config"] = str(config)
    paths["cfg_sha"] = cfg_sha
    return paths


def _run_gate(paths, out):
    return cli.cmd_gate(argparse.Namespace(
        verdict_json=paths["verdict"], drill_json=paths["drill"],
        latency_json=paths["latency"], autopilot_state=paths["state"],
        cost_model=paths["cost"], host_check=paths["host"],
        watchdog_heartbeat=paths["hb"], hypothesis="H1",
        config=paths["config"], require_commit=False, out=str(out)))


def test_gate_go_on_complete_evidence_and_rejects_synthetic(tmp_path):
    paths = _gate_artifacts(tmp_path)
    assert _run_gate(paths, tmp_path / "gate.json") == 0
    assert json.loads((tmp_path / "gate.json").read_text())["gate"] == "GO"

    (tmp_path / "synth").mkdir(exist_ok=True)
    synth = _gate_artifacts(tmp_path / "synth", synthetic=True)
    assert _run_gate(synth, tmp_path / "gate-synth.json") == 2
    assert json.loads((tmp_path / "gate-synth.json").read_text())[
        "gate"] == "NO-GO"


def test_gate_rejects_stale_cost_and_missing_heartbeat(tmp_path):
    paths = _gate_artifacts(tmp_path)
    old = (datetime.now(UTC) - timedelta(days=40)).isoformat()
    _write(Path(paths["cost"]), {"version": 1, "created_utc": old})
    assert _run_gate(paths, tmp_path / "g1.json") == 2
    (tmp_path / "fresh").mkdir(exist_ok=True)
    paths = _gate_artifacts(tmp_path / "fresh")
    _write(Path(paths["hb"]), {"has_exposure": True})
    assert _run_gate(paths, tmp_path / "g2.json") == 2


def _arm_args(tmp_path, gate_path):
    return argparse.Namespace(
        capital_usdt=100.0, max_daily_loss=5.0,
        gate_json=str(gate_path), out=str(tmp_path / "armed.json"))


def _valid_gate(tmp_path):
    """A real GO gate: arm refuses one that does not bind evidence hashes."""
    path = tmp_path / "arm-gate.json"
    paths = _gate_artifacts(tmp_path)
    assert _run_gate(paths, path) == 0
    return path


def test_arm_requires_tty_and_ci_absence(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CRYPTOBOT_ARM_ACK", cli.ARM_ACK_PHRASE)
    gate = _valid_gate(tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cli.cmd_arm(_arm_args(tmp_path, gate)) == 2
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setenv("CI", "1")
    assert cli.cmd_arm(_arm_args(tmp_path, gate)) == 2
    monkeypatch.delenv("CI")
    monkeypatch.setattr("builtins.input", lambda _prompt: cli.ARM_ACK_PHRASE)
    assert cli.cmd_arm(_arm_args(tmp_path, gate)) == 0
    armed = json.loads((tmp_path / "armed.json").read_text())
    assert armed["armed"] is True and armed["canary_trades"] == 10


def test_arm_refuses_expired_gate_even_interactive(tmp_path, monkeypatch):
    monkeypatch.setenv("CRYPTOBOT_ARM_ACK", cli.ARM_ACK_PHRASE)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    gate = tmp_path / "expired.json"
    _write(gate, {"gate": "GO",
                  "expires_utc": (datetime.now(UTC)
                                  - timedelta(hours=1)).isoformat()})
    assert cli.cmd_arm(_arm_args(tmp_path, gate)) == 2
    assert not (tmp_path / "armed.json").exists()


def test_gate_family_b_screen_pass_holdout_coupling(tmp_path):

    paths = _gate_artifacts(tmp_path)
    verdict = json.loads(Path(paths["verdict"]).read_text())
    verdict["verdict"] = "SCREEN_PASS"
    verdict["data_provenance"] = "SEALED-HOLDOUT"
    _write(Path(paths["verdict"]), _sign(verdict))
    assert _run_gate(paths, tmp_path / "gate-b.json") == 0
    assert json.loads((tmp_path / "gate-b.json").read_text())["gate"] == "GO"
    # Same SCREEN_PASS claimed from OBSERVED/dev data: NO-GO.
    verdict["data_provenance"] = "OBSERVED"
    _write(Path(paths["verdict"]), _sign(verdict))
    assert _run_gate(paths, tmp_path / "gate-b2.json") == 2
    doc = json.loads((tmp_path / "gate-b2.json").read_text())
    assert doc["gate"] == "NO-GO"
    assert doc["checks"]["screen_requires_holdout"] is False
