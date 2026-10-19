"""A/B/C acceptance: matrix help, emulator sockets, ops refusals, C1 clock."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta

from cryptobot.adapters.mockex_server import DEFAULT_SECRET, MockEx
from cryptobot.cli import main
from cryptobot.emulator.drill import run_drill
from cryptobot.ops.manual import prod_arm_refusal
from cryptobot.research.adjudicate import c1_final_utc
from cryptobot.selftest import command_rows, invoke


def test_every_command_help_has_no_traceback():
    rows = command_rows()
    assert len(rows) >= 20
    for row in rows:
        parts = row["command"].split()[1:]
        code, text = invoke(parts + ["--help"])
        assert code == 0, row["command"]
        assert "usage" in text.lower()
        assert "Traceback" not in text
        code, text = invoke(parts + ["--not-a-real-flag"])
        assert code != 0
        assert "Traceback" not in text


def test_unknown_command_prints_help():
    code, text = invoke(["nope"])
    assert code != 0
    assert "Traceback" not in text
    assert "usage" in text.lower()


def test_mockex_http_signature_and_label():
    mock = MockEx()
    port = mock.serve()
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/fapi/v1/time") as resp:
            body = json.loads(resp.read().decode())
            assert resp.headers["X-Cryptobot-Provenance"] == "EMULATED"
        assert body["emulated"] is True
        assert "serverTime" in body
        bad = urllib.request.Request(
            f"http://127.0.0.1:{port}/fapi/v1/account?timestamp=1"
            "&recvWindow=5000&signature=00")
        try:
            urllib.request.urlopen(bad)
            raise AssertionError("bad signature was accepted")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
    finally:
        mock.close()
    assert DEFAULT_SECRET


def test_emulator_drill_is_labelled_and_passes(tmp_path):
    doc = run_drill(tmp_path)
    assert doc["provenance"] == "EMULATED"
    assert doc["verdict"] == "PASS", doc["cells"]


def test_emulated_drill_cannot_make_the_gate_go(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "STATE.md").write_text("# state\n")
    now = datetime.now(UTC).isoformat()
    verdict = {"verdict": "PASS", "data_provenance": "SEALED-HOLDOUT",
               "document_sha256": "a" * 64,
               "hashes": {"config_sha256_16": "abc"}}
    drill = {"verdict": "PASS", "provenance": "EMULATED", "emulated": True,
             "created_utc": now}
    files = {
        "verdict": verdict,
        "drill": drill,
        "latency": {"verdict": "PASS", "p99_feed_age_ms": 1, "drop_rate": 0},
        "state": {"state": "GATE_READY", "provenance": "OBSERVED",
                  "config_sha256": "abc"},
        "cost": {"version": 1, "created_utc": now},
        "host": {"verdict": "PASS", "generated_utc": now},
        "hb": {"ts_utc": now, "has_exposure": False},
    }
    paths = {}
    for name, doc in files.items():
        dest = tmp_path / f"{name}.json"
        dest.write_text(json.dumps(doc))
        paths[name] = str(dest)
    cfg = tmp_path / "c.toml"
    cfg.write_bytes(b"x")
    import argparse

    from cryptobot.cli import cmd_gate
    rc = cmd_gate(argparse.Namespace(
        verdict_json=paths["verdict"], drill_json=paths["drill"],
        latency_json=paths["latency"], autopilot_state=paths["state"],
        cost_model=paths["cost"], host_check=paths["host"],
        watchdog_heartbeat=paths["hb"], hypothesis="B1",
        config=str(cfg), require_commit=False,
        out=str(tmp_path / "gate.json")))
    assert rc == 2
    gate = json.loads((tmp_path / "gate.json").read_text())
    assert gate["gate"] == "NO-GO"
    assert gate["checks"]["demo_drill_pass_fresh"] is False


def test_ops_prod_refuses_without_arm(tmp_path):
    assert prod_arm_refusal("prod", tmp_path / "a.json", tmp_path / "g.json")
    code, text = invoke(["ops", "order", "--mode", "prod", "--qty", "0.01",
                         "--symbol", "BTCUSDT", "--side", "BUY",
                         "--journal", str(tmp_path / "j.jsonl"),
                         "--book", str(tmp_path / "b.json"),
                         "--risk-state", str(tmp_path / "r.json"),
                         "--armed", str(tmp_path / "a.json"),
                         "--gate", str(tmp_path / "g.json")])
    assert code == 2
    assert "REFUSED" in text
    assert "Traceback" not in text


def test_c1_final_date_never_passes_the_grace():
    t0 = datetime(2026, 10, 18, tzinfo=UTC)
    t = t0 + timedelta(days=90)
    early = t0 + timedelta(days=10)
    assert c1_final_utc(t0, early) == t
    late = t + timedelta(days=7)
    assert c1_final_utc(t0, late) == late
    too_late = t + timedelta(days=40)
    assert c1_final_utc(t0, too_late) == t + timedelta(days=14)
    assert c1_final_utc(t0, None) == t + timedelta(days=14)
    assert main is not None
