"""V-007: report builder — artifacts, standalone HTML, determinism."""
from __future__ import annotations

import csv
import json

import pytest
from pathlib import Path

from cryptobot.reporting import charts
from cryptobot.reporting.build import build_report

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "v007_run"
ARTIFACTS = ("summary.json", "trades.csv", "equity.csv", "daily_returns.csv",
             "rejections.csv", "report.html")


def test_build_writes_all_artifacts(tmp_path):
    out = build_report(FIX, tmp_path / "rep")
    assert sorted(out) == sorted(ARTIFACTS)
    for name in ARTIFACTS:
        assert Path(out[name]).is_file()


def test_summary_matches_rebuilt_metrics(tmp_path):
    out = build_report(FIX, tmp_path / "rep")
    summary = json.loads(Path(out["summary.json"]).read_text())
    assert summary["reconciliation"]["status"] == "agree"
    assert summary["net_return"]["net_return"] == pytest.approx(5.3 / 10000)
    assert summary["n_episodes"] == 1
    assert summary["provenance"]["run_strategy"] == "S1"


def test_csv_shapes(tmp_path):
    out = build_report(FIX, tmp_path / "rep")
    trades = list(csv.DictReader(open(out["trades.csv"])))
    assert len(trades) == 1 and float(trades[0]["net"]) == 5.3
    equity = list(csv.DictReader(open(out["equity.csv"])))
    assert {"drawdown_usdt", "drawdown_pct", "date_ist"} <= set(equity[0])
    assert len(equity) == 5
    daily = list(csv.DictReader(open(out["daily_returns.csv"])))
    assert daily[0]["label"] in ("trade", "no-trade", "no-coverage")
    rej = list(csv.DictReader(open(out["rejections.csv"])))
    assert len(rej) == 2


def test_html_is_standalone_and_labeled(tmp_path):
    out = build_report(FIX, tmp_path / "rep")
    html = Path(out["report.html"]).read_text()
    assert "<svg" in html and html.count("<svg") == 4
    for banned in ("http://", "https://", "<script", "src=", "href="):
        assert banned not in html
    for needle in ("synthetic-v007", "agree", "Methods and assumptions",
                   "First page", "insufficient", "undefined"):
        assert needle in html


def test_build_is_deterministic(tmp_path):
    a = build_report(FIX, tmp_path / "a")
    b = build_report(FIX, tmp_path / "b")
    for name in ARTIFACTS:
        assert Path(a[name]).read_bytes() == Path(b[name]).read_bytes()


def test_empty_series_charts_render_placeholder():
    assert "no data" in charts.line_chart("t", "c", [])
    assert "no data" in charts.bar_chart("t", "c", [], [])
    assert "no data" in charts.strategy_chart("t", "c", [], [])
