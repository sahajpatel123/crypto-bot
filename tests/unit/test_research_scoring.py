"""Scoring panel tests (Worker 4, CORR phase B)."""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.research.scoring import score_cell  # noqa: E402


def _mini_scored_run(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "rejections.jsonl").write_text(
        json.dumps({"ts_utc": "2026-10-11T10:00:01+00:00",
                    "stage": "strategy",
                    "reason": "breakout:fail|breakout:fail",
                    "strategy": "S1", "instrument": "BTCUSDT",
                    "side": "unknown"}) + "\n", encoding="utf-8")
    con = sqlite3.connect(run / "store.db")
    con.execute("create table intents (id integer primary key, run_id text,"
                "intent_id text,strategy text,instrument text,side text,"
                "decision text,reason text,ts_utc text)")
    con.execute("insert into intents values (1,'r','I1','S1','BTCUSDT',"
                "'LONG','selected','selection:admitted',"
                "'2026-10-11T10:00:02+00:00')")
    con.commit()
    con.close()
    journal = [
        {"event": "submitted",
         "detail": {"client_id": "e1", "role": "entry",
                    "reservation_id": "r1"}},
        {"event": "submitted",
         "detail": {"client_id": "x1", "role": "target",
                    "reservation_id": "r1"}},
        {"event": "fill",
         "detail": {"client_id": "e1", "reservation_id": "r1",
                    "exec_id": "T-1"}},
        {"event": "fill",
         "detail": {"client_id": "x1", "reservation_id": "r1",
                    "exec_id": "T-2"}},
    ]
    (run / "engine_journal.jsonl").write_text(
        "\n".join(json.dumps(e) for e in journal) + "\n", encoding="utf-8")
    (run / "fills.jsonl").write_text(
        json.dumps({"execution_id": "T-1", "client_order_id": "e1"}) + "\n"
        + json.dumps({"execution_id": "T-2",
                      "client_order_id": "x1"}) + "\n",
        encoding="utf-8")
    ledger = {"journal": [
        {"kind": "fill", "exec_id": "T-1", "side": "BUY", "qty": 0.01,
         "price": 60000.0, "fee": 0.03,
         "ts_utc": "2026-10-11T10:00:03+00:00"},
        {"kind": "fill", "exec_id": "T-2", "side": "SELL", "qty": 0.01,
         "price": 60100.0, "fee": 0.03,
         "ts_utc": "2026-10-11T10:01:03+00:00"},
    ]}
    (run / "ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
    equity = [
        {"ts_utc": "2026-10-11T10:00:00+00:00", "marked_equity": 120.0},
        {"ts_utc": "2026-10-11T10:02:00+00:00", "marked_equity": 120.94},
    ]
    (run / "equity.jsonl").write_text(
        "\n".join(json.dumps(e) for e in equity) + "\n", encoding="utf-8")
    return run


def test_scored_panel_links_one_trade(tmp_path):
    panel = score_cell(_mini_scored_run(tmp_path))
    assert panel["closed_trades"] == 1
    trade = panel["trades"][0]
    assert trade["direction"] == "LONG"
    assert trade["gross"] == 1.0
    assert trade["fees"] == 0.06
    assert trade["net"] == 0.94
    assert trade["hold_s"] == 60.0
    assert panel["booked"]["gross"] == 1.0
    assert panel["booked"]["net"] == 0.94
    assert panel["expectancy"]["n"] == 1
    assert panel["expectancy"]["ci95_lo"] is None
    assert panel["worst_trade"] == 0.94
    assert panel["daily_net"] == {"2026-10-11": 0.94}
    assert panel["drawdown"]["max_drawdown"] == 0.0
    assert panel["funnel_stages"]["closed_reservations"] == 1
    assert panel["watch"]["orphan_exit_reservations"] == []


def test_empty_run_reports_na_honestly(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "rejections.jsonl").write_text("", encoding="utf-8")
    con = sqlite3.connect(run / "store.db")
    con.execute("create table intents (id integer primary key, run_id text,"
                "intent_id text,strategy text,instrument text,side text,"
                "decision text,reason text,ts_utc text)")
    con.commit()
    con.close()
    (run / "engine_journal.jsonl").write_text("", encoding="utf-8")
    (run / "fills.jsonl").write_text("", encoding="utf-8")
    (run / "ledger.json").write_text(json.dumps({"journal": []}),
                                     encoding="utf-8")
    (run / "equity.jsonl").write_text("", encoding="utf-8")
    panel = score_cell(run)
    assert panel["closed_trades"] == 0
    assert panel["expectancy"]["n"] == 0
    assert panel["fill_rate"] is None
    assert panel["worst_trade"] is None
