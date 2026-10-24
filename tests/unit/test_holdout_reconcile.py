"""Z1.3: small holdout decodes must be subsets of the pre-analysis seal."""
from __future__ import annotations

import json

from cryptobot.research.holdout_reconcile import membership_by_kind, reconcile_chunks


def _file(sha: str, path: str) -> dict:
    return {"sha256": sha, "path": path, "bytes": 1, "filename_date": "2024-01"}


def test_child_files_map_into_parent_by_sha256(tmp_path):
    parent = tmp_path / "parent.json"
    child = tmp_path / "child.json"
    parent.write_text(json.dumps({
        "files": [
            _file("aa", "/lake/holdout_raw/klines/1d/BTCUSDT/a.zip"),
            _file("bb", "/lake/holdout_raw/fundingRate/na/ETHUSDT/b.zip"),
            _file("cc", "/lake/holdout_raw/spot/1d/BTCUSDT/c.zip"),
        ],
    }))
    child.write_text(json.dumps({
        "files": [
            _file("aa", "/elsewhere/holdout_raw/klines/1d/BTCUSDT/a.zip"),
            _file("bb", "/elsewhere/holdout_raw/fundingRate/na/ETHUSDT/b.zip"),
        ],
    }))
    report = reconcile_chunks(parent, [child])
    assert report["ok"] is True
    assert report["children"][0]["files"] == 2
    assert report["children"][0]["missing"] == []
    assert report["parent_files"] == 3


def test_a_sha_absent_from_the_parent_fails(tmp_path):
    parent = tmp_path / "parent.json"
    child = tmp_path / "child.json"
    parent.write_text(json.dumps({"files": [_file("aa", "/holdout_raw/a.zip")]}))
    child.write_text(json.dumps({"files": [_file("zz", "/holdout_raw/z.zip")]}))
    report = reconcile_chunks(parent, [child])
    assert report["ok"] is False
    assert report["children"][0]["missing"] == ["zz"]


def test_spot_files_are_classified_outside_a_perp_parent(tmp_path):
    parent = tmp_path / "parent.json"
    child = tmp_path / "child.json"
    parent.write_text(json.dumps({"files": [
        _file("aa", "/holdout_raw/klines/1d/BTCUSDT/a.zip")]}))
    child.write_text(json.dumps({"files": [
        _file("aa", "/holdout_raw/klines/1d/BTCUSDT/a.zip"),
        _file("ss", "/holdout_raw/spot/1d/BTCUSDT/s.zip"),
    ]}))
    report = membership_by_kind(parent, child)
    assert report["inside"] == {"klines": 1}
    assert report["outside"] == {"spot": 1}
