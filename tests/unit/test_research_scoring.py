"""Scoring panel tests (Worker 4, CORR phase B; W2 READY)."""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

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
                    "exec_id": "T-1", "qty": 0.01}},
        {"event": "fill",
         "detail": {"client_id": "x1", "reservation_id": "r1",
                    "exec_id": "T-2", "qty": 0.01}},
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


def _mutate_ledger(run, mutate):
    path = run / "ledger.json"
    ledger = json.loads(path.read_text(encoding="utf-8"))
    mutate(ledger)
    path.write_text(json.dumps(ledger), encoding="utf-8")


def test_partial_close_is_not_a_closed_trade(tmp_path):
    run = _mini_scored_run(tmp_path)

    def mutate(ledger):
        ledger["journal"][1]["qty"] = 0.005
        ledger["journal"][1]["fee"] = 0.015

    _mutate_ledger(run, mutate)
    journal_path = run / "engine_journal.jsonl"
    events = [json.loads(line) for line in
              journal_path.read_text(encoding="utf-8").splitlines()
              if line.strip()]
    for event in events:
        if event.get("event") == "fill" and \
                event.get("detail", {}).get("client_id") == "x1":
            event["detail"]["qty"] = 0.005
    journal_path.write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    panel = score_cell(run)
    assert panel["closed_trades"] == 0
    assert panel["expectancy"]["n"] == 0
    assert panel["partial_episodes"] == 1
    episode = panel["partial_episode_list"][0]
    assert episode["status"] == "partial"
    assert episode["closed_qty"] == 0.005
    assert episode["open_qty"] == 0.005
    assert episode["gross"] == 0.5
    assert episode["fees"] == 0.045
    assert episode["net"] == 0.455
    assert episode["open_basis_flow"] == -300.0
    assert panel["booked"]["net"] == 0.455
    assert panel["reconciliation"]["identity_holds"] is True
    assert panel["flat_valid"] is False
    assert panel["funnel_stages"]["closed_reservations"] == 0


def test_funded_trade_reports_ist_day_in_every_view(tmp_path):
    run = _mini_scored_run(tmp_path)

    def mutate(ledger):
        ledger["journal"][0]["ts_utc"] = "2026-10-11T18:31:00+00:00"
        ledger["journal"][1]["ts_utc"] = "2026-10-11T18:32:00+00:00"
        ledger["journal"].append({"kind": "funding", "amount": -0.20,
                                  "ts_utc": "2026-10-11T18:31:30+00:00"})

    _mutate_ledger(run, mutate)
    equity = [
        {"ts_utc": "2026-10-11T18:30:45+00:00", "marked_equity": 120.0},
        {"ts_utc": "2026-10-11T18:32:45+00:00", "marked_equity": 120.74},
    ]
    (run / "equity.jsonl").write_text(
        "\n".join(json.dumps(e) for e in equity) + "\n", encoding="utf-8")
    panel = score_cell(run)
    assert panel["closed_trades"] == 1
    assert panel["trades"][0]["funding"] == -0.20
    assert panel["trades"][0]["net"] == 0.74
    assert panel["daily_net"] == {"2026-10-12": 0.74}
    assert panel["booked"]["net"] == 0.74
    assert panel["booked"]["funding"] == -0.20
    marked = panel["daily_marked"]["2026-10-12"]
    assert marked["first"] == 120.0
    assert marked["last"] == 120.74
    assert marked["change"] == pytest.approx(0.74)
    assert panel["reconciliation"]["identity_holds"] is True
    assert panel["account_check"]["gap"] == pytest.approx(0.0)
    assert panel["flat_valid"] is True


def test_funding_without_trades_preserved_on_zero_trade_day(tmp_path):
    run = _mini_scored_run(tmp_path)

    def mutate(ledger):
        ledger["journal"] = [e for e in ledger["journal"]
                             if e.get("kind") != "fill"]
        ledger["journal"].append({"kind": "funding", "amount": -0.20,
                                  "ts_utc": "2026-10-11T18:31:30+00:00"})

    _mutate_ledger(run, mutate)
    (run / "fills.jsonl").write_text("", encoding="utf-8")
    (run / "engine_journal.jsonl").write_text("", encoding="utf-8")
    panel = score_cell(run)
    assert panel["closed_trades"] == 0
    assert panel["open_episodes"] == 0
    assert panel["daily_net"] == {"2026-10-11": 0.0,
                                  "2026-10-12": -0.2}
    assert panel["booked"]["net"] == -0.20
    assert panel["reconciliation"]["unattributed_funding"] == -0.20
    assert panel["reconciliation"]["identity_holds"] is True
    assert panel["flat_valid"] is True


def test_missing_ledger_never_valid_flat(tmp_path):
    run = _mini_scored_run(tmp_path)
    (run / "ledger.json").unlink()
    panel = score_cell(run)
    assert panel["ledger_status"] == "missing"
    assert panel["booked"]["net"] is None
    assert panel["closed_trades"] == 0
    assert panel["flat_valid"] is False
    assert "unverifiable" in panel["flat_reason"]
    assert panel["reconciliation"]["identity_holds"] is False


def test_expectancy_labels_descriptive_only(tmp_path):
    panel = score_cell(_mini_scored_run(tmp_path))
    assert "descriptive only" in panel["expectancy"]["method"]
    assert "promotion gate" in panel["expectancy"]["method"]


def test_watch_reads_risk_state_and_protection_checkpoints(tmp_path):
    run = _mini_scored_run(tmp_path)
    (run / "risk_state.json").write_text(json.dumps({
        "reservations": {},
        "unresolved": {"r9": {"reservation": {"qty": 0.5}}},
        "booked": {"r9": {"net_qty": 0.0, "exec_ids": [],
                          "symbol": "BTCUSDT"}},
        "open_position": True}), encoding="utf-8")
    journal = [
        {"event": "submitted",
         "detail": {"client_id": "leg-1", "role": "target",
                    "reservation_id": "r9", "qty": 0.5,
                    "instrument": "BTCUSDT"}},
    ]
    with (run / "engine_journal.jsonl").open("a", encoding="utf-8") as fh:
        for event in journal:
            fh.write(json.dumps(event) + "\n")
    con = sqlite3.connect(run / "store.db")
    con.execute("create table checkpoints (id integer primary key,"
                "run_id text,ts_utc text,kind text,payload text)")
    con.execute("insert into checkpoints values (1,'r',"
                "'2026-10-11T10:00:04+00:00','protection-unverified',"
                "'{\"leg\": \"leg-1\", \"state\": \"open\"}')")
    con.execute("insert into checkpoints values (2,'r',"
                "'2026-10-11T10:00:05+00:00','flatten',"
                "'{\"reason\": \"time-exit\", \"net\": 0.0}')")
    con.commit()
    con.close()
    panel = score_cell(run)
    watch = panel["watch"]
    assert watch["unresolved_reservations"] == ["r9"]
    assert watch["risk_state"] == "ok"
    assert watch["live_client_ids"] == [{
        "client_id": "leg-1", "role": "target",
        "reservation_id": "r9", "instrument": "BTCUSDT"}]
    assert watch["protection_checkpoints"]["kinds"] == {
        "flatten": 1, "protection-unverified": 1}
    assert watch["protection_checkpoints"]["legs_unverified"] == ["leg-1"]
    assert watch["orphan_exit_reservations"] == []
    assert panel["flat_valid"] is False


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
