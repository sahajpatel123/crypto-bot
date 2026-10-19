"""F3.6: recorder CLI (offline paths; start/stop stub the service)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def test_recorder_status_not_running(tmp_path, capsys):
    from cryptobot import cli

    rc = cli.cmd_recorder(argparse.Namespace(
        recorder_cmd="status", run_dir=str(tmp_path / "run"),
        run_id="rec", duration_s=0.0, symbols="BTCUSDT,ETHUSDT"))
    assert rc == 2
    assert "not running" in capsys.readouterr().out.lower()


def test_recorder_status_running(tmp_path, capsys):
    from cryptobot import cli

    run = tmp_path / "run"
    run.mkdir()
    (run / "status.json").write_text(json.dumps(
        {"running": True, "run_id": "rec", "drops": 0}))
    (run / "recorder.pid").write_text("12345")
    rc = cli.cmd_recorder(argparse.Namespace(
        recorder_cmd="status", run_dir=str(run),
        run_id="rec", duration_s=0.0, symbols="BTCUSDT,ETHUSDT"))
    assert rc == 0
    assert "running" in capsys.readouterr().out.lower()


def test_recorder_verify_offline(tmp_path, capsys):
    from cryptobot import cli
    from cryptobot.recorder.writer import DurableWriter

    run = tmp_path / "run"
    writer = DurableWriter(run)
    writer.start()
    assert writer.append("BTCUSDT.aggTrade", {"u": 1})
    assert writer.wait_idle()
    writer.close()
    rc = cli.cmd_recorder(argparse.Namespace(
        recorder_cmd="verify", run_dir=str(run),
        run_id="rec", duration_s=0.0, symbols="BTCUSDT,ETHUSDT"))
    assert rc == 0
    assert "ok" in capsys.readouterr().out.lower()


def test_recorder_start_stop_stubbed(tmp_path, monkeypatch, capsys):
    from cryptobot import cli

    started = {}
    stopped = []

    class _FakeService:
        def __init__(self, config, run_dir):
            started["config"] = config
            started["run_dir"] = Path(run_dir)

        def start(self):
            started["run_dir"].mkdir(parents=True, exist_ok=True)
            (started["run_dir"] / "status.json").write_text("{}")

        def stop(self):
            stopped.append(True)

        def status(self):
            return {"running": True, "drops": 0, "run_id": "rec"}

    import cryptobot.recorder.service as svc

    monkeypatch.setattr(svc, "RecorderService", _FakeService)
    run = tmp_path / "run"
    rc = cli.cmd_recorder(argparse.Namespace(
        recorder_cmd="start", run_dir=str(run),
        run_id="rec", duration_s=0.05, symbols="BTCUSDT"))
    assert rc == 0
    assert started["config"].symbols == ("BTCUSDT",)
    assert stopped == [True]
    assert not (run / "recorder.pid").exists()  # clean stop removes pid
    assert (run / "status.json").exists()
