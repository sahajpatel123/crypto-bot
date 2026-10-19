"""zone_status unit tests (manager-owned, self-contained).

No src/ imports: loads tools/zone_status.py by path; fixtures live in
tmp_path so the real ZONES.json is never touched.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "zone_status", REPO / "tools" / "zone_status.py")
assert SPEC and SPEC.loader
zone_status = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(zone_status)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_all_ok_and_empty_and_stale(tmp_path):
    _write(tmp_path / "a.txt", "x")
    _write(tmp_path / "v.json", json.dumps({"verdict": "NONE (deep) ok"}))
    manifest = {"zones": {
        "Z-a": {"status": "GREEN",
                "evidence": [{"kind": "exists", "path": "a.txt"},
                             {"kind": "verdict", "path": "v.json",
                              "key": "verdict", "contains": "NONE"}]},
        "Z-b": {"status": "RED", "evidence": []},
        "Z-c": {"status": "RED",
                "evidence": [{"kind": "exists", "path": "gone.txt"}]},
    }}
    res = zone_status.check_zones(manifest, tmp_path)
    assert res["zones"]["Z-a"]["evidence_state"] == "EVIDENCE-OK"
    assert res["zones"]["Z-b"]["evidence_state"] == "EVIDENCE-EMPTY"
    assert res["zones"]["Z-c"]["evidence_state"] == "EVIDENCE-STALE"
    assert "1/3" in res["summary"]


def test_verdict_mismatch_is_stale(tmp_path):
    _write(tmp_path / "v.json", json.dumps({"verdict": "QUALIFIED: P1"}))
    manifest = {"zones": {
        "Z": {"status": "RED",
              "evidence": [{"kind": "verdict", "path": "v.json",
                            "key": "verdict", "contains": "NONE"}]},
    }}
    res = zone_status.check_zones(manifest, tmp_path)
    assert res["zones"]["Z"]["evidence_state"] == "EVIDENCE-STALE"
    assert res["zones"]["Z"]["problems"]


def test_unknown_kind_and_bad_manifest_raise(tmp_path):
    with pytest.raises(ValueError):
        zone_status.check_zones(
            {"zones": {"Z": {"status": "?", "evidence": [
                {"kind": "suite", "path": "x"}]}}}, tmp_path)
    with pytest.raises(ValueError):
        zone_status.check_zones({"zones": {}}, tmp_path)
    with pytest.raises(ValueError):
        zone_status.check_zones({}, tmp_path)


def test_real_zones_manifest_shape():
    manifest = json.loads(
        (REPO / "coord" / "pivot" / "ZONES.json").read_text(
            encoding="utf-8"))
    assert set(manifest["zones"]) == {
        "Z0-safety", "Z1-data", "Z2-execution", "Z3-alpha",
        "Z4-risk", "Z5-validation", "Z6-liveops"}
    res = zone_status.check_zones(manifest, REPO)
    # All 7 zones cite existing, parseable evidence (Z6 cites the
    # 2026-10-16 sandbox drill report; it still stays RED until demo
    # validation — evidence_state is about evidence, not readiness).
    states = {z: v["evidence_state"]
              for z, v in res["zones"].items()}
    assert all(s == "EVIDENCE-OK" for s in states.values()), states
    assert states["Z6-liveops"] == "EVIDENCE-OK"
