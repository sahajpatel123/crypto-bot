"""C1: invalidated verdicts are refused, and a broken chain is detected."""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from cryptobot.research.invalidation import (
    append_invalidation,
    verdict_consumption,
    verify_invalidation_chain,
)


def _gate_bundle(tmp: Path, verdict: dict) -> dict:
    now = datetime.now(UTC).isoformat()
    files = {
        "verdict": verdict,
        "state": {"state": "GATE_READY", "provenance": "OBSERVED",
                  "config_sha256": "abc" + "0" * 61},
        "cost": {"version": 1, "created_utc": now},
        "host": {"verdict": "PASS", "generated_utc": now},
        "drill": {"verdict": "PASS", "created_utc": now},
        "latency": {"verdict": "PASS", "p99_feed_age_ms": 10, "drop_rate": 0},
        "hb": {"ts_utc": now, "has_exposure": False},
    }
    # config hash must match the 3-char prefix the state uses... gate
    # compares first 16 of autopilot config to verdict config_sha256_16.
    files["state"]["config_sha256"] = "abc" + "d" * 61
    verdict["hashes"]["config_sha256_16"] = "abc" + "d" * 13
    paths = {}
    for name, doc in files.items():
        dest = tmp / f"{name}.json"
        dest.write_text(json.dumps(doc))
        paths[name] = str(dest)
    cfg = tmp / "cfg.toml"
    cfg.write_bytes(b"hypothesis='B4'\n")
    import hashlib
    sha = hashlib.sha256(cfg.read_bytes()).hexdigest()
    verdict["hashes"]["config_sha256_16"] = sha[:16]
    files["state"]["config_sha256"] = sha
    (tmp / "verdict.json").write_text(json.dumps(verdict))
    (tmp / "state.json").write_text(json.dumps(files["state"]))
    paths["config"] = str(cfg)
    paths["verdict"] = str(tmp / "verdict.json")
    paths["state"] = str(tmp / "state.json")
    return paths


def _run(paths, out):
    from cryptobot import cli
    return cli.cmd_gate(argparse.Namespace(
        verdict_json=paths["verdict"], drill_json=paths["drill"],
        latency_json=paths["latency"], autopilot_state=paths["state"],
        cost_model=paths["cost"], host_check=paths["host"],
        watchdog_heartbeat=paths["hb"], hypothesis="B4",
        config=paths["config"], require_commit=False, out=str(out)))


def test_gate_nogo_when_pass_looking_verdict_is_invalidated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "STATE.md").write_text("# closeout test state\n")
    digest = "b" * 64
    verdict = {"hypothesis": "B4", "verdict": "PASS",
               "data_provenance": "SEALED-HOLDOUT",
               "document_sha256": digest, "hashes": {}}
    paths = _gate_bundle(tmp_path, verdict)
    # Without a chain the same artifact is not invalidated.
    assert _run(paths, tmp_path / "gate-ok.json") == 0
    append_invalidation(tmp_path / "invalidations.json", {
        "action": "invalidate",
        "verdict_sha256": digest,
        "decision": "D-042",
        "hypothesis": "B4",
        "holdout": "BURNED",
        "burned_hypotheses": ["B4"],
        "rule": "B4 and any B4 variant; FORWARD only",
    })
    assert _run(paths, tmp_path / "gate-no.json") == 2
    doc = json.loads((tmp_path / "gate-no.json").read_text())
    assert doc["gate"] == "NO-GO"
    assert doc["checks"]["verdict_not_invalidated"] is False


def test_editing_or_removing_an_entry_breaks_the_chain(tmp_path):
    path = tmp_path / "invalidations.json"
    append_invalidation(path, {
        "action": "invalidate", "verdict_sha256": "c" * 64,
        "decision": "D-042", "hypothesis": "B4", "holdout": "BURNED",
        "burned_hypotheses": ["B4"], "rule": "B4"})
    intact = json.loads(path.read_text())
    assert verify_invalidation_chain(intact) == []
    edited = json.loads(path.read_text())
    edited["entries"][0]["decision"] = "D-999"
    assert any("hash mismatch" in p for p in verify_invalidation_chain(edited))
    removed = json.loads(path.read_text())
    removed["entries"] = []
    assert any("chain_head" in p for p in verify_invalidation_chain(removed))
    allowed, why = verdict_consumption(
        {"document_sha256": "c" * 64, "verdict": "PASS"}, edited)
    assert allowed is False and "broken" in why


def test_autopilot_refuses_invalidated_screen(tmp_path):
    from cryptobot.research.autopilot import Autopilot

    root = tmp_path / "auto"
    prereg = tmp_path / "B4.md"
    prereg.write_text("# B4\n")
    bot = Autopilot(root, family="B")
    bot.register("B4", prereg=str(prereg), config_sha256="abc",
                 commit="c", family_size=7)
    bot._transition("B4", "DEV_EVAL", reason="test")
    bot._transition("B4", "FROZEN", reason="test")
    digest = "d" * 64
    verdicts = tmp_path / "verdicts_b"
    verdicts.mkdir()
    (verdicts / "B4.json").write_text(json.dumps({
        "hypothesis": "B4", "verdict": "SCREEN_PASS",
        "data_provenance": "SEALED-HOLDOUT", "document_sha256": digest}))
    # Point the autopilot root's parent at this verdicts dir.
    # Autopilot looks at root.parent / verdicts_b. root is tmp/auto,
    # parent is tmp, so place the file at tmp/verdicts_b (done) and
    # the chain beside it.
    append_invalidation(verdicts / "invalidations.json", {
        "action": "invalidate", "verdict_sha256": digest,
        "decision": "D-042", "hypothesis": "B4", "holdout": "BURNED",
        "burned_hypotheses": ["B4"], "rule": "B4"})
    # The code looks beside the verdict path, which is
    # root.parent / verdicts_b. root is tmp/auto, parent tmp. Good.
    out = bot.run_once()
    assert out["hypotheses"]["B4"]["state"] == "FROZEN"
    assert "refused" in out["hypotheses"]["B4"].get("blocked", "")


def test_family_a_missing_dev_data_is_await_not_killed(tmp_path):
    from cryptobot.research.autopilot import Autopilot

    root = tmp_path / "auto"
    prereg = tmp_path / "H1.md"
    prereg.write_text("# H1\n")
    bot = Autopilot(root, family="A")
    bot.register("H1", prereg=str(prereg), config_sha256="abc",
                 commit="c", family_size=6)
    assert bot.run_once()["hypotheses"]["H1"]["state"] == "DEV_EVAL"
    dev = root / "dev" / "H1.json"
    dev.parent.mkdir(parents=True)
    dev.write_text(json.dumps({
        "hypothesis": "H1", "provenance": "OBSERVED",
        "outcome": "UNDERPOWERED", "status": "AWAIT_DATA",
        "reason": "no L2 history", "trades": [],
        "power": {"status": "IMPOSSIBLE", "required_trades": None},
        "required_confirm_trades": 300, "required_dev_trades": 100}))
    assert bot.run_once()["hypotheses"]["H1"]["state"] == "AWAIT_DATA"
    assert bot.run_once()["hypotheses"]["H1"]["state"] == "AWAIT_DATA"
