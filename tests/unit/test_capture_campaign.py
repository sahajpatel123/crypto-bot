"""Campaign supervisor tests: planning, preflight refusal, settle,
resume, retry-same-chunk, disk guard, stop. No network anywhere.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import capture_campaign as cc  # noqa: E402


def _fake_executor(log, fail_calls: set[int] | None = None,
                   no_snaps: bool = False):
    fail_calls = fail_calls or set()

    def run(chunk_dir, seconds):
        log.append((str(chunk_dir), seconds))
        if len(log) in fail_calls:
            raise RuntimeError("boom")
        (chunk_dir / "events.jsonl").write_text(
            '{"channel":"aggTrade","symbol":"BTCUSDT"}\n' * 20)
        (chunk_dir / "raw.jsonl").write_text("raw\n" * 50)
        if not no_snaps:
            (chunk_dir / "depth_snapshots.jsonl").write_text(
                '{"outcome":"synced"}\n')
        (chunk_dir / "bars.jsonl").write_text('{"type":"bar"}\n')
        (chunk_dir / "run_stats.json").write_text(json.dumps(
            {"stop_reason": "duration-reached", "events_total": 20}))
        return {"stop_reason": "duration-reached", "events_total": 20}

    return run


def _campaign(dest, executor, free, **kw):
    args = dict(days=10, chunk_hours=6, symbols=["BTCUSDT"],
                chunk_executor=executor, disk_free=lambda p: free,
                probe_s=1.0, cooldown_s=0.0)
    args.update(kw)
    return cc.Campaign(dest, **args)


# -- planning ----------------------------------------------------------------


def test_plan_chunks():
    assert cc.plan_chunks(10, 6) == 40
    assert cc.plan_chunks(1, 24) == 1
    assert cc.plan_chunks(0.1, 6) == 1
    with pytest.raises(ValueError):
        cc.plan_chunks(0, 6)


def test_profiles_and_default():
    assert set(cc.PROFILES) == {"lean500", "minimal", "full"}
    # lean500: 500ms depth, no bookTicker — the disk-fitting default.
    assert cc.PROFILES["lean500"]["public"] == ("depth@500ms",)
    assert cc.PROFILES["lean500"]["market"] == ("aggTrade", "markPrice@1s")
    c = cc.Campaign("x", days=1, chunk_hours=24, symbols=["BTCUSDT"])
    assert c.profile == "lean500"
    with pytest.raises(ValueError):
        cc.Campaign("x", days=1, chunk_hours=24, symbols=["BTCUSDT"],
                    profile="nope")


def test_projected_footprint_math():
    proj = cc.projected_footprint(1000.0, 500.0, 0.1, 10.0, 3600.0, 4)
    assert proj["events_bytes_per_s"] == 100.0
    assert proj["per_chunk_plain_bytes"] == (100.0 + 50.0) * 3600.0
    assert proj["settled_total_bytes"] == int(100.0 * 0.1 * 3600 * 1.03) * 4
    assert proj["peak_bytes"] > proj["settled_total_bytes"]


# -- settle ------------------------------------------------------------------


def test_settle_gz_sha_delete_raw_idempotent(tmp_path):
    d = tmp_path / "chunk-000"
    d.mkdir()
    (d / "events.jsonl").write_text("e" * 1000)
    (d / "raw.jsonl").write_text("r" * 100)
    (d / "bars.jsonl").write_text("b" * 10)
    (d / "depth_snapshots.jsonl").write_text('{"outcome":"synced"}\n')
    (d / "run_stats.json").write_text(json.dumps(
        {"stop_reason": "duration-reached", "events_total": 5}))
    info = cc.settle_chunk(d)
    assert info["status"] == "settled" and info["complete"] is True
    assert (d / "events.jsonl.gz").exists()
    assert not (d / "events.jsonl").exists()
    assert not (d / "raw.jsonl").exists()
    assert info["files"]["events.jsonl"]["sha256"]
    assert info["raw_deleted_bytes"] == 100
    again = cc.settle_chunk(d)
    assert again == info  # idempotent marker


def test_settle_partial_without_stats_is_honest(tmp_path):
    d = tmp_path / "chunk-001"
    d.mkdir()
    (d / "events.jsonl").write_text("e" * 500)
    info = cc.settle_chunk(d)
    assert info["status"] == "settled" and info["complete"] is False
    assert "run_stats" not in info


def test_settle_empty_chunk(tmp_path):
    d = tmp_path / "chunk-002"
    d.mkdir()
    (d / "events.jsonl").write_text("")
    info = cc.settle_chunk(d)
    assert info["status"] == "empty" and info["complete"] is False


# -- preflight ---------------------------------------------------------------


def test_preflight_refuses_small_disk_and_allows_big(tmp_path):
    log = []
    c = _campaign(tmp_path / "small", _fake_executor(log),
                  free=100 * (1 << 20))
    assert c.preflight()["verdict"] == "REFUSED"
    c2 = _campaign(tmp_path / "big", _fake_executor(log), free=1 << 40)
    assert c2.preflight()["verdict"] == "OK"
    c3 = _campaign(tmp_path / "tight", _fake_executor(log),
                   free=100 * (1 << 20), allow_tight=True)
    assert c3.preflight()["verdict"] == "OK_TIGHT"


def test_preflight_blocks_without_depth_sync(tmp_path):
    log = []
    c = _campaign(tmp_path / "nosnaps",
                  _fake_executor(log, no_snaps=True), free=1 << 40)
    assert c.preflight()["verdict"] == "BLOCKED_DEPTH"


# -- run loop ----------------------------------------------------------------


def test_run_settles_chunks_then_resumes_without_reprobe(tmp_path):
    dest = tmp_path / "camp"
    log = []
    c = _campaign(dest, _fake_executor(log), free=1 << 40,
                  days=1, chunk_hours=6)
    st = c.run(max_chunks=2)
    assert st["status"] == "capped"
    assert [ch["idx"] for ch in st["chunks"]] == [0, 1]
    assert len(log) == 3          # probe + two chunks
    log2 = []
    c2 = _campaign(dest, _fake_executor(log2), free=1 << 40,
                   days=1, chunk_hours=6)
    st2 = c2.run()
    assert st2["status"] == "complete"
    assert [ch["idx"] for ch in st2["chunks"]] == [0, 1, 2, 3]
    assert len(log2) == 2         # only idx 2,3; no probe


def test_failed_chunk_retries_same_idx(tmp_path):
    dest = tmp_path / "camp"
    log = []
    # call 1 = probe, call 2 = first chunk attempt (fails), call 3 = retry
    c = _campaign(dest, _fake_executor(log, fail_calls={2}),
                  free=1 << 40, days=0.25, chunk_hours=6)
    st = c.run(max_chunks=1)
    assert st["status"] == "complete"
    assert [ch["idx"] for ch in st["chunks"]] == [0]
    assert st["chunks"][0]["status"] == "settled"
    assert len(log) == 3
    assert st["gaps"][0]["idx"] == 0 and st["gaps"][0]["attempt"] == 1


def test_disk_floor_stops_before_any_chunk(tmp_path):
    dest = tmp_path / "camp"
    dest.mkdir()
    cc.save_state(dest, {"format": "cryptobot-campaign/1",
                         "chunks_total": 2, "chunks": [], "gaps": [],
                         "status": "running", "days": 1,
                         "chunk_hours": 12})
    log = []
    c = _campaign(dest, _fake_executor(log), free=10 * (1 << 20),
                  days=1, chunk_hours=12)
    c.disk_pause_s = 0.0
    c.disk_pause_limit = 1     # pause once, then give up (test mode)
    st = c.run()
    assert st["status"] == "disk-floor"
    assert log == []              # no probe, no chunks


def test_stop_file_honoured(tmp_path):
    dest = tmp_path / "camp"
    dest.mkdir()
    cc.save_state(dest, {"format": "cryptobot-campaign/1",
                         "chunks_total": 2, "chunks": [], "gaps": [],
                         "status": "running", "days": 1,
                         "chunk_hours": 12})
    (dest / cc.STOP_FILE).write_text("stop")
    log = []
    c = _campaign(dest, _fake_executor(log), free=1 << 40,
                  days=1, chunk_hours=12)
    st = c.run()
    assert st["status"] == "stopped"
    assert log == []


def test_stop_and_status_subcommands(tmp_path):
    dest = tmp_path / "camp"
    assert cc.main(["stop", "--dest", str(dest)]) == 0
    assert (dest / cc.STOP_FILE).exists()
    assert cc.main(["status", "--dest", str(dest)]) == 0
