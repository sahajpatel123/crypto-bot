import argparse, json
import pytest

from cryptobot import cli
from cryptobot.research.calibrate import calibrate


def test_calibrate_never_relaxes(tmp_path):
    fills = tmp_path / "f.jsonl"
    fills.write_text(json.dumps(
        {"slippage_bps": 1.0, "spread_bps": 1.0, "latency_ms": 10}) + "\n")
    out = tmp_path / "c.json"
    doc = calibrate(fills, out, previous={"fill_params": {
        "spread_bps": 3.0, "depth_bps": 5.0, "latency_bps": 4.0,
        "adverse_bps": 12.0}})
    assert doc["fill_params"]["adverse_bps"] == 12.0  # kept conservative
    assert doc["fill_params"]["spread_bps"] == 3.0


def test_fixtures_ingest_rejects_bad_json(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    (src / "bad.json").write_text("{oops\n")
    assert cli.cmd_fixtures(argparse.Namespace(
        fixtures_cmd="ingest", dir=str(src),
        dest=str(tmp_path / "d"))) == 2
    (src / "bad.json").write_text('{"a": 1}\n')
    assert cli.cmd_fixtures(argparse.Namespace(
        fixtures_cmd="ingest", dir=str(src),
        dest=str(tmp_path / "d"))) == 0


def test_host_check_reports_verdict(tmp_path, capsys):
    rc = cli.cmd_host_check(argparse.Namespace(
        out=str(tmp_path / "h.json")))
    doc = json.loads((tmp_path / "h.json").read_text())
    assert doc["verdict"] in ("PASS", "FAIL")
    assert rc == (0 if doc["verdict"] == "PASS" else 2)


def test_research_register_budget(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "research/prereg").mkdir(parents=True)
    for i in range(1, 9):
        (tmp_path / f"research/prereg/H{i}-x.md").write_text("x")
    assert cli.cmd_research(argparse.Namespace(
        research_cmd="register", hypothesis="H9", title="x")) == 2


def test_verdict_refuses_synthetic(tmp_path):
    trades = tmp_path / "t.jsonl"
    trades.write_text(json.dumps(
        {"net_bps": 5.0, "provenance": "SYNTHETIC"}) + "\n")
    assert cli.cmd_verdict(argparse.Namespace(
        trades=str(trades), hypothesis="H1", config="configs/paper.toml",
        family_size=1, out=None)) == 2
