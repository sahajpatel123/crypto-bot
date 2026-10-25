"""Daily P&L report: profitable/loss/funding/empty days and corrupt journals."""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from cryptobot.ops.daily_pnl import (
    build_ladder_evidence,
    cmd_pnl,
    daily_report,
    live_statistics,
    render_markdown,
)

PILOT = 10_000.0


def _fill(ts: str, side: str, qty: float, price: float, fee: float,
          exec_id: str, symbol: str = "BTCUSDT") -> dict:
    return {"kind": "fill", "side": side, "qty": qty, "price": price,
            "fee": fee, "ts_utc": ts, "exec_id": exec_id, "symbol": symbol}


def _write_run(root: Path, journal: list[dict], equity: list[dict] | None = None,
               *, name: str = "run-1", raw_lines: list[str] | None = None,
               ) -> Path:
    run = root / name
    run.mkdir(parents=True, exist_ok=True)
    (run / "ledger.json").write_text(json.dumps({
        "version": 1, "pilot_equity": PILOT, "seq": 0, "snapshot": {},
        "journal": journal}), encoding="utf-8")
    if equity is not None or raw_lines is not None:
        lines = [json.dumps(row) for row in equity or []]
        lines.extend(raw_lines or [])
        (run / "equity.jsonl").write_text("\n".join(lines) + "\n",
                                          encoding="utf-8")
    return run


def _equity(ts: str, marked: float, open_pnl: float, qty: float) -> dict:
    return {"ts_utc": ts, "marked_equity": marked, "open_pnl": open_pnl,
            "position_qty": qty, "position_symbol": "BTCUSDT"}


def _profitable_day(tmp_path: Path) -> Path:
    return _write_run(tmp_path / "runs", [
        _fill("2026-03-02T09:00:00+00:00", "BUY", 0.1, 50_000.0, 5.0, "f1"),
        _fill("2026-03-02T10:00:00+00:00", "SELL", 0.1, 50_200.0, 5.0, "f2"),
    ], [
        _equity("2026-03-02T09:30:00+00:00", 10_005.0, 5.0, 0.1),
        _equity("2026-03-02T10:00:00+00:00", 10_010.0, 0.0, 0.0),
    ])


def test_profitable_day_is_net_of_fees(tmp_path: Path) -> None:
    run = _profitable_day(tmp_path)
    doc = daily_report(run.parent, day=date(2026, 3, 2))
    assert doc["format"] == "cryptobot-daily-pnl/1"
    assert doc["gate"] == "NO-GO"
    assert doc["journal_present"] is True and doc["activity"] is True
    assert doc["complete"] is True and doc["corruption"] == []
    assert doc["realised"] == {"net_usdt": 10.0, "gross_usdt": 20.0,
                               "fees_usdt": 10.0, "funding_usdt": 0.0}
    assert doc["fills"] == 2
    assert doc["round_trips"] == {"count": 1, "wins": 1, "losses": 0,
                                  "win_rate": 1.0}
    assert doc["per_symbol"]["BTCUSDT"] == {
        "fills": 2, "realised_net_usdt": 10.0, "fees_usdt": 10.0,
        "round_trips": 1}
    assert doc["equity"]["basis"] == "equity_journal"
    assert doc["equity"]["start_usdt"] == PILOT
    assert doc["equity"]["end_usdt"] == 10_010.0
    assert doc["equity"]["unrealised_usdt"] == 0.0
    assert doc["drawdown"]["day_usdt"] == 0.0
    assert doc["drawdown"]["cumulative_usdt"] == 0.0
    assert doc["sources"] and all(item["sha256"] for item in doc["sources"])


def test_loss_day_reports_a_negative_realised_result(tmp_path: Path) -> None:
    run = _write_run(tmp_path / "runs", [
        _fill("2026-03-04T09:00:00+00:00", "BUY", 0.1, 50_000.0, 5.0, "f1"),
        _fill("2026-03-04T10:00:00+00:00", "SELL", 0.1, 49_800.0, 5.0, "f2"),
    ])
    doc = daily_report(run.parent, day=date(2026, 3, 4))
    assert doc["realised"]["net_usdt"] == -30.0
    assert doc["realised"]["gross_usdt"] == -20.0
    assert doc["round_trips"]["losses"] == 1
    assert doc["round_trips"]["win_rate"] == 0.0
    assert doc["equity"]["basis"] == "realised_only"
    assert doc["equity"]["end_usdt"] == PILOT - 30.0
    assert doc["drawdown"]["cumulative_usdt"] == 30.0
    assert doc["drawdown"]["cumulative_pct"] > 0


def test_funding_only_day_is_not_a_trading_day(tmp_path: Path) -> None:
    run = _write_run(tmp_path / "runs", [
        {"kind": "funding", "amount": 2.5,
         "ts_utc": "2026-03-03T00:00:00+00:00", "event_id": "fund-1"},
    ])
    doc = daily_report(run.parent, day=date(2026, 3, 3))
    assert doc["realised"] == {"net_usdt": 2.5, "gross_usdt": 0.0,
                               "fees_usdt": 0.0, "funding_usdt": 2.5}
    assert doc["fills"] == 0
    assert doc["round_trips"]["count"] == 0
    assert doc["round_trips"]["win_rate"] is None
    assert doc["per_symbol"] == {}
    assert doc["activity"] is True


def test_day_with_no_entries_is_an_empty_report(tmp_path: Path) -> None:
    run = _profitable_day(tmp_path)
    doc = daily_report(run.parent, day=date(2026, 3, 5))
    assert doc["journal_present"] is True
    assert doc["activity"] is False
    assert doc["empty"] is True
    assert doc["realised"]["net_usdt"] is None
    assert doc["fills"] == 0
    assert any("no journal entry falls on this date" in note
               for note in doc["notes"])
    text = render_markdown(doc)
    assert "No activity on this date" in text


def test_missing_journals_never_fabricate_a_result(tmp_path: Path) -> None:
    doc = daily_report(tmp_path / "does-not-exist",
                       day=date(2026, 3, 2))
    assert doc["journal_present"] is False
    assert doc["empty"] is True
    assert doc["realised"] == {"net_usdt": None, "gross_usdt": None,
                               "fees_usdt": None, "funding_usdt": None}
    assert doc["equity"] == {"start_usdt": None, "end_usdt": None,
                             "unrealised_usdt": None, "basis": "none"}
    assert doc["drawdown"]["day_usdt"] is None
    text = render_markdown(doc)
    assert "Empty report" in text
    assert "profit" not in text.lower()


def test_a_corrupt_journal_line_is_reported_not_dropped(
        tmp_path: Path) -> None:
    day = date(2026, 3, 2)
    run = _write_run(tmp_path / "runs", [
        _fill("2026-03-02T09:00:00+00:00", "BUY", 0.1, 50_000.0, 5.0, "f1"),
        {"kind": "fill", "side": "HODL", "qty": 0.1, "price": 50_000.0,
         "fee": 5.0, "ts_utc": "2026-03-02T09:30:00+00:00", "exec_id": "bad"},
        _fill("2026-03-02T10:00:00+00:00", "SELL", 0.1, 50_200.0, 5.0, "f2"),
    ], raw_lines=["{not json at all"])
    doc = daily_report(run.parent, day=day)
    assert doc["complete"] is False
    assert len(doc["corruption"]) == 2
    files = {Path(item["file"]).name for item in doc["corruption"]}
    assert files == {"ledger.json", "equity.jsonl"}
    assert all(item["error"] for item in doc["corruption"])
    assert any(item["line"] == 1 for item in doc["corruption"])
    # The valid entries still produce the true result.
    assert doc["fills"] == 2
    assert doc["realised"]["net_usdt"] == 10.0
    text = render_markdown(doc)
    assert "Corrupt journal entries" in text
    assert "not dropped" in " ".join(doc["notes"])


def test_cli_writes_json_and_flags_corruption(tmp_path: Path, capsys) -> None:
    day = date(2026, 3, 2)
    run = _write_run(tmp_path / "runs", [
        _fill("2026-03-02T09:00:00+00:00", "BUY", 0.1, 50_000.0, 5.0, "f1"),
    ], raw_lines=["oops"])
    out = tmp_path / "report.json"
    code = cmd_pnl(argparse.Namespace(
        pnl_cmd="daily", root=str(run.parent), date=day.isoformat(),
        json=True, out=str(out)))
    assert code == 1  # corruption is a non-zero exit, not a silent pass
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["date"] == "2026-03-02"
    assert doc["complete"] is False
    printed = json.loads(capsys.readouterr().out)
    assert printed["date"] == "2026-03-02"


def test_cli_rejects_a_bad_date(tmp_path: Path, capsys) -> None:
    code = cmd_pnl(argparse.Namespace(
        pnl_cmd="daily", root=str(tmp_path), date="02-03-2026",
        json=False, out=None))
    assert code == 2
    assert "want YYYY-MM-DD" in capsys.readouterr().err


def test_live_statistics_and_evidence_are_derived_from_journals(
        tmp_path: Path) -> None:
    _profitable_day(tmp_path)
    live, detail, files = live_statistics(tmp_path / "runs")
    assert live.round_trips == 1
    assert live.days == 1.0
    assert live.sharpe is None  # one day cannot carry a Sharpe
    assert live.cost_bps is None  # no measured slippage file
    assert live.max_drawdown_frac == 0.0
    assert detail["active_days"] == ["2026-03-02"]
    assert files and all(Path(path).is_file() for path in files)

    reference = tmp_path / "backtest.json"
    reference.write_text(json.dumps({
        "format": "cryptobot-backtest-reference/1", "study": "B4b",
        "sharpe": 0.8, "cost_bps": 3.5, "max_drawdown_frac": 0.015}),
        encoding="utf-8")
    doc = build_ladder_evidence(tmp_path / "runs", backtest_reference=reference,
                                out=tmp_path / "evidence.json", study="B4b")
    assert doc["live"]["round_trips"] == 1
    assert doc["live"]["cost_bps"] is None
    assert doc["backtest"]["sharpe"] == 0.8
    assert len(doc["sources"]) >= 2
    assert (tmp_path / "evidence.json").is_file()
