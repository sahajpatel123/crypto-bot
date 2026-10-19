import argparse, json
from cryptobot import cli


def _ns(tmp, **kw):
    base = dict(verdict_json=None, drill_json=None, latency_json=None,
                autopilot_state=None, calibration_json=None,
                host_check_json=None, watchdog_json=None,
                out=str(tmp / "gate.json"))
    base.update(kw)
    return argparse.Namespace(**base)


def test_gate_rejects_synthetic_verdict(tmp_path):
    v = tmp_path / "v.json"
    v.write_text(json.dumps({"verdict": "PASS", "provenance": "SYNTHETIC",
                             "hypothesis": "H1"}))
    rc = cli.cmd_gate(_ns(tmp_path, verdict_json=str(v)))
    doc = json.loads((tmp_path / "gate.json").read_text())
    assert rc == 2 and doc["checks"]["verdict_not_synthetic"] is False


def test_gate_requires_autopilot_and_freshness(tmp_path):
    rc = cli.cmd_gate(_ns(tmp_path))
    doc = json.loads((tmp_path / "gate.json").read_text())
    assert doc["gate"] == "NO-GO"
    for k in ("autopilot_gate_ready", "calibration_fresh",
              "host_check_pass", "demo_drill_fresh",
              "watchdog_heartbeat"):
        assert doc["checks"][k] is False


def test_arm_refuses_non_tty(tmp_path, monkeypatch):
    monkeypatch.setenv("CRYPTOBOT_ARM_ACK", cli.ARM_ACK_PHRASE)
    g = tmp_path / "g.json"
    g.write_text(json.dumps({"gate": "GO",
                             "expires_utc": "2999-01-01T00:00:00+00:00"}))
    rc = cli.cmd_arm(argparse.Namespace(
        capital_usdt=100.0, max_daily_loss=5.0, gate_json=str(g),
        out=str(tmp_path / "armed.json")))
    assert rc == 2 and not (tmp_path / "armed.json").exists()
