"""D1/D4: external-root alias, disk projection, gap alert fields."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from cryptobot.research.data_root import resolve_data_roots
from cryptobot.selftest import invoke


def _manifest(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    start = int(now.replace(hour=0, minute=0, second=0).timestamp() * 1000)
    (root / "manifest.json").write_text(json.dumps({
        "format": "cryptobot-recorder-manifest/1",
        "entries": [{"first_ms": start, "last_ms": start + 3_600_000,
                     "bytes": 58 * 1024 * 1024, "gaps": 0,
                     "sealed_utc": now.isoformat()}],
    }))


def test_background_status_reports_projection(tmp_path):
    rec = tmp_path / "rec"
    _manifest(rec)
    code, text = invoke(["background", "status", "--recorder", str(rec),
                         "--no-notify"])
    assert code == 0, text
    doc = json.loads(text)
    for key in ("free_mb", "mb_per_hour", "projected_disk_days",
                "days_to_adjudication", "disk_alert", "gap_pct",
                "adjudication_final_utc"):
        assert key in doc, key
    assert doc["mb_per_hour"] > 0
    assert doc["gap_pct"] is not None


def test_external_data_root_alias(monkeypatch, tmp_path):
    ext = tmp_path / "ext"
    (ext / "data" / "lake").mkdir(parents=True)
    monkeypatch.setenv("EXTERNAL_DATA_ROOT", str(ext))
    monkeypatch.delenv("CRYPTOBOT_EXTERNAL_ROOT", raising=False)
    monkeypatch.delenv("CRYPTOBOT_DATA_ROOT", raising=False)
    roots = resolve_data_roots(tmp_path)
    assert roots.lake_source == "external"
    assert roots.lake == ext / "data" / "lake"
