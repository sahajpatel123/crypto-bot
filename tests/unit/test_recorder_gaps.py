"""D4: recorder gap % in the daily autopilot report + alert threshold."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptobot.cli import main
from cryptobot.ops.gaps import recorder_gap_report
from cryptobot.selftest import invoke


def _manifest(root: Path, entries: list[dict]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(json.dumps(
        {"format": "cryptobot-recorder-manifest/1", "entries": entries}))


def _entry(first: datetime, minutes: int, gaps: int = 0) -> dict:
    start = int(first.timestamp() * 1000)
    return {"first_ms": start, "last_ms": start + minutes * 60_000,
            "gaps": gaps, "records": 1000}


def test_gap_pct_detects_a_sleep_hole(tmp_path):
    now = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    start = now.replace(hour=0)
    _manifest(tmp_path, [
        _entry(start, 60),
        # 6-hour hole between 01:00 and 07:00
        _entry(start + timedelta(hours=7), 60),
    ])
    report = recorder_gap_report(tmp_path, day=now, notify=False)
    assert report["status"] == "OK"
    assert report["chunks"] == 2
    assert report["gap_pct"] > 5.0
    assert report["alert"] is True


def test_gap_pct_is_zero_when_covered(tmp_path):
    now = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    start = now.replace(hour=0)
    _manifest(tmp_path, [_entry(start, 720)])  # 12h covered of 12h span
    report = recorder_gap_report(tmp_path, day=now, notify=False)
    assert report["gap_pct"] == 0.0
    assert report["alert"] is False


def test_gap_report_without_manifest_is_explicit(tmp_path):
    report = recorder_gap_report(tmp_path / "missing", notify=False)
    assert report["status"] == "NO_MANIFEST"
    assert report["gap_pct"] is None


def test_autopilot_report_includes_recorder_gaps(tmp_path, monkeypatch):
    # Minimal registry so report works without any hypothesis artifacts.
    root = tmp_path / "ap"
    root.mkdir()
    (root / "registry.json").write_text(json.dumps(
        {"format": "cryptobot-autopilot-registry/1", "hypotheses": {}}))
    rec = tmp_path / "rec"
    now = datetime.now(UTC)
    _manifest(rec, [_entry(now.replace(hour=0, minute=0, second=0), 1)])
    code, text = invoke(["autopilot", "report", "--root", str(root),
                         "--recorder-root", str(rec), "--no-notify"])
    assert code == 0, text
    report = json.loads(text)
    assert "recorder" in report
    assert report["recorder"]["status"] in ("OK", "NO_CHUNKS_TODAY")
    assert main is not None
