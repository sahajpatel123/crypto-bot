"""F6.1 tests: dashboard renders recorder/autopilot/risk state."""
from __future__ import annotations

import json
from pathlib import Path

from cryptobot.reporting.status import collect_status, write_dashboard


def test_dashboard_collects_and_escapes(tmp_path):
    rec = tmp_path / "rec"
    rec.mkdir()
    (rec / "status.json").write_text(json.dumps({
        "state": "recording", "dropped": 2, "alerts": []}))
    (rec / "manifest.json").write_text(json.dumps({"entries": [
        {"records": 100, "gaps": 1}, {"records": 50, "gaps": 0}]}))
    auto = tmp_path / "auto"
    (auto / "state").mkdir(parents=True)
    (auto / "registry.json").write_text(json.dumps({
        "hypotheses": {"H1": {}, "H<script>": {}}}))
    (auto / "state" / "H1.json").write_text(json.dumps({
        "state": "AWAIT_CONFIRM_DATA",
        "power": {"days_required": 42.5}}))
    risk = tmp_path / "risk.json"
    risk.write_text(json.dumps({"emergency_latched": False}))
    status = collect_status(recorder_root=rec, autopilot_root=auto,
                            risk_state=risk)
    assert status["recorder"]["records"] == 150
    assert status["recorder"]["gaps"] == 1
    html = write_dashboard(tmp_path / "index.html", recorder_root=rec,
                           autopilot_root=auto, risk_state=risk)
    text = (tmp_path / "index.html").read_text()
    assert "AWAIT_CONFIRM_DATA" in text
    assert "42.5" in text
    assert "<script>" not in text
    assert html["recorder"]["dropped"] == 2
