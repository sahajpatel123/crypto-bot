"""Funnel analyzer tests (Worker 4, 30MIN). Buckets + unique IDs."""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.research.funnel import (analyze_banked, analyze_run,  # noqa: E402
                                       analyze_symbol_time, map_reason)


def test_reason_mapping_covers_plan_buckets():
    assert map_reason("strategy", "gap:fail|gap:fail") == "unavailable_data"
    assert map_reason("strategy", "book:never-synced|book:never-synced") == \
        "missing_depth"
    assert map_reason("strategy", "sequence:fail|trend:fail") == \
        "missing_sequence"
    assert map_reason("strategy", "breakout:fail|momentum:fail") == "no_setup"
    assert map_reason("strategy", "regime:na(S3)|regime:na(S3)") == "no_setup"
    assert map_reason("selection", "reward-below-cost") == "below_cost"
    assert map_reason("selection", "position-busy") == "exposure_cooldown"
    assert map_reason("selection", "cooldown") == "exposure_cooldown"
    assert map_reason("risk", "skip:min-notional") == "below_minimum"
    assert map_reason("execution", "queued-past-window") == "stale_expired"
    assert map_reason("execution", "ioc-remainder-cancel") == "ioc_cancelled"
    assert map_reason("execution", "band:nonmarketable") == "nonmarketable"
    assert map_reason("selection", "expired") == "stale_expired"
    assert map_reason("gate", "stale-quote") == "stale_input"
    assert map_reason("gate", "quote-age-unknown") == "stale_input"
    assert map_reason("reconcile", "restart-pending") == "startup"
    assert map_reason("reconcile", "unknown-outcomes") == "other_hold"
    assert map_reason("event", "pre-window:X") == "other_hold"
    assert map_reason("anomaly", "halt-entries:latency") == "other_hold"
    assert map_reason("strategy", "strategy:no-fire:gap-2") == \
        "unavailable_data"
    assert map_reason("strategy", "no-fire:gap-2") == "unavailable_data"
    assert map_reason("strategy", "no-fire:insufficient-history") == \
        "unavailable_data"
    assert map_reason("strategy", "no-fire:confirm-gate") == "no_setup"
    assert map_reason("strategy", "no-fire:position-gate") == "no_setup"
    assert map_reason("strategy", "no-fire:vwap-gate") == "no_setup"
    assert map_reason("strategy", "something:new") == ""


def _mini_run(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    rows = [
        # same opportunity twice (repetition), then two more seconds
        {"ts_utc": "2026-08-27T00:00:01.200000+00:00", "stage": "strategy",
         "reason": "breakout:fail|breakout:fail", "strategy": "S1",
         "instrument": "XRPUSDT", "side": "unknown"},
        {"ts_utc": "2026-08-27T00:00:01.900000+00:00", "stage": "strategy",
         "reason": "breakout:fail|breakout:fail", "strategy": "S1",
         "instrument": "XRPUSDT", "side": "unknown"},
        {"ts_utc": "2026-08-27T00:00:02.200000+00:00", "stage": "strategy",
         "reason": "gap:fail|gap:fail", "strategy": "S1",
         "instrument": "XRPUSDT", "side": "unknown"},
        {"ts_utc": "2026-08-27T00:00:03.200000+00:00", "stage": "selection",
         "reason": "reward-below-cost", "strategy": "S1",
         "instrument": "XRPUSDT", "side": "LONG"},
    ]
    (run / "rejections.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    con = sqlite3.connect(run / "store.db")
    con.execute("create table intents (id integer primary key, run_id text,"
                "intent_id text,strategy text,instrument text,side text,"
                "decision text,reason text,ts_utc text)")
    con.execute("insert into intents values (1,'r','I1','S1','XRPUSDT',"
                "'LONG','selected','selection:admitted',"
                "'2026-08-27T00:00:03.500000+00:00')")
    con.commit()
    con.close()
    journal = [
        {"ts_utc": "2026-08-27T00:00:03.600000+00:00", "event": "submitted",
         "detail": {"client_id": "pe-1", "role": "entry", "kind": "LIMIT",
                    "reservation_id": "r-1"}},
        {"ts_utc": "2026-08-27T00:00:03.700000+00:00", "event": "fill",
         "detail": {"client_id": "pe-1", "exec_id": "T-1"}},
        {"ts_utc": "2026-08-27T00:00:04.000000+00:00", "event": "submitted",
         "detail": {"client_id": "pe-2", "role": "entry", "kind": "LIMIT",
                    "reservation_id": "r-2"}},
        {"ts_utc": "2026-08-27T00:00:04.100000+00:00", "event": "terminal",
         "detail": {"client_id": "pe-2", "kind": "cancel",
                    "reason": "venue-canceled"}},
    ]
    (run / "engine_journal.jsonl").write_text(
        "\n".join(json.dumps(e) for e in journal) + "\n", encoding="utf-8")
    return run


def test_run_funnel_dedups_and_counts_ids(tmp_path):
    report = analyze_run(_mini_run(tmp_path))
    assert report["rejection_rows"] == 4
    assert report["unique_opportunities"] == 3
    assert report["rows_per_opportunity"] == 1.33
    assert report["unique_intents"] == 1
    assert report["selected_intents"] == 1
    assert report["entry_client_ids"] == 2
    assert report["entries_filled"] == 1
    assert report["entries_cancelled_unfilled"] == 1
    assert report["fill_exec_ids"] == 1
    assert report["eligible_seconds"] == {"S1": 2}
    assert report["healthy_no_trade_seconds"] == {"S1": 1}
    assert report["buckets"]["no_setup"] == 2
    assert report["buckets"]["unavailable_data"] == 1
    assert report["buckets"]["below_cost"] == 1
    assert report["buckets"]["ioc_cancelled"] == 1
    # v2: startup, original verdict, stage chain, close linkage.
    assert report["startup_seconds"] == {"S1": 0}
    path = report["intent_stage_paths"]["I1"]
    assert path["strategy_verdict"] == "admitted"
    assert path["terminal_bucket"] == "admitted"
    assert report["intent_terminal_gates"] == {"admitted": 1}
    assert report["closed_reservations"] == 0
    assert report["stages"]["setup_unique_intents"] == 1
    assert report["stages"]["submitted_entries"] == 2
    assert report["stages"]["filled_entries"] == 1


def test_blocked_intent_keeps_original_verdict(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "rejections.jsonl").write_text(
        json.dumps({"ts_utc": "2026-08-27T00:00:01+00:00",
                    "stage": "risk", "reason": "skip:min-notional",
                    "strategy": "S1", "instrument": "XRPUSDT",
                    "side": "LONG"}) + "\n", encoding="utf-8")
    con = sqlite3.connect(run / "store.db")
    con.execute("create table intents (id integer primary key, run_id text,"
                "intent_id text,strategy text,instrument text,side text,"
                "decision text,reason text,ts_utc text)")
    con.execute("insert into intents values (1,'r','I9','S1','XRPUSDT',"
                "'LONG','selected','selection:admitted',"
                "'2026-08-27T00:00:01+00:00')")
    con.execute("insert into intents values (2,'r','I9','S1','XRPUSDT',"
                "'LONG','rejected','risk:skip:min-notional',"
                "'2026-08-27T00:00:02+00:00')")
    con.commit()
    con.close()
    (run / "engine_journal.jsonl").write_text("", encoding="utf-8")
    report = analyze_run(run)
    path = report["intent_stage_paths"]["I9"]
    assert path["strategy_verdict"] == "admitted"
    assert path["terminal_bucket"] == "below_minimum"
    assert path["rows"] == 2
    assert report["stages"]["setup_unique_intents"] == 1
    assert report["stages"]["cost_pass_unique_intents"] == 1


def test_two_symbols_same_second_counts_two_symbol_seconds(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    rows = [{"ts_utc": "2026-10-11T10:00:01+00:00", "stage": "strategy",
             "reason": "breakout:fail|breakout:fail", "strategy": "S1",
             "instrument": symbol, "side": "unknown"}
            for symbol in ("BTCUSDT", "ETHUSDT")]
    (run / "rejections.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    con = sqlite3.connect(run / "store.db")
    con.execute("create table intents (id integer primary key, run_id text,"
                "intent_id text,strategy text,instrument text,side text,"
                "decision text,reason text,ts_utc text)")
    con.commit()
    con.close()
    (run / "engine_journal.jsonl").write_text("", encoding="utf-8")
    report = analyze_run(run)
    assert report["unique_opportunities"] == 2
    assert report["eligible_seconds"] == {"S1": 2}
    assert report["stages"]["strategy_eligible_seconds"] == {"S1": 2}
    assert report["eligible_symbol_seconds"] == {"S1|BTCUSDT": 1,
                                                 "S1|ETHUSDT": 1}
    assert report["usable_symbol_seconds_total"] == 2
    assert report["stages"]["usable_data_seconds"] == 1
    assert report["rejection_rows"] == 2


def test_unattributed_rows_keyed_separately(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    rows = [
        {"ts_utc": "2026-10-11T10:00:01+00:00", "stage": "strategy",
         "reason": "breakout:fail|breakout:fail", "strategy": "S1",
         "instrument": "BTCUSDT", "side": "unknown"},
        {"ts_utc": "2026-10-11T10:00:01+00:00", "stage": "strategy",
         "reason": "breakout:fail|breakout:fail", "strategy": "S1",
         "side": "unknown"},
    ]
    (run / "rejections.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    con = sqlite3.connect(run / "store.db")
    con.execute("create table intents (id integer primary key, run_id text,"
                "intent_id text,strategy text,instrument text,side text,"
                "decision text,reason text,ts_utc text)")
    con.commit()
    con.close()
    (run / "engine_journal.jsonl").write_text("", encoding="utf-8")
    report = analyze_run(run)
    assert report["unique_opportunities"] == 2
    assert report["eligible_symbol_seconds"] == {"S1|BTCUSDT": 1,
                                                 "S1|?": 1}


def test_partial_reservation_is_qty_aware(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "rejections.jsonl").write_text("", encoding="utf-8")
    con = sqlite3.connect(run / "store.db")
    con.execute("create table intents (id integer primary key, run_id text,"
                "intent_id text,strategy text,instrument text,side text,"
                "decision text,reason text,ts_utc text)")
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
                    "exec_id": "T-2", "qty": 0.005}},
    ]
    (run / "engine_journal.jsonl").write_text(
        "\n".join(json.dumps(e) for e in journal) + "\n", encoding="utf-8")
    report = analyze_run(run)
    assert report["closed_reservations"] == 0
    assert report["partial_reservations"] == 1
    assert report["open_reservations"] == 0
    assert report["partial_reservation_ids"] == ["r1"]
    assert report["stages"]["closed_reservations"] == 0
    assert report["entries_filled"] == 1


def test_symbol_time_counts_per_symbol_seconds(tmp_path):
    capture = tmp_path / "events.jsonl"
    base_ms = 1_757_000_000_000
    lines = [
        {"channel": "aggTrade", "symbol": "BTCUSDT",
         "exchange_ts_ms": base_ms},
        {"channel": "aggTrade", "symbol": "BTCUSDT",
         "exchange_ts_ms": base_ms + 500},
        {"channel": "bookTicker", "symbol": "ETHUSDT",
         "exchange_ts_ms": base_ms + 1500},
        {"channel": "noise", "symbol": "BTCUSDT",
         "exchange_ts_ms": base_ms + 2500},
    ]
    capture.write_text("\n".join(json.dumps(e) for e in lines) + "\n",
                       encoding="utf-8")
    report = analyze_symbol_time(capture)
    assert report["events_scanned"] == 3
    assert report["usable_symbol_seconds"] == {"BTCUSDT": 1, "ETHUSDT": 1}
    assert report["usable_symbol_seconds_total"] == 2


def test_banked_mapping_labels_rows(tmp_path):
    cell = {"armset": "COMBINED", "split": "validation",
            "days": ["2026-09-27"], "events_seen": 100,
            "reject_counts": {"strategy:gap:fail|gap:fail": 50,
                              "selection:cooldown": 5,
                              "strategy:brand:new": 2},
            "intents_admitted": 1,
            "replay_stream": {"first_ms": 1, "last_ms": 2}}
    journal = tmp_path / "j.jsonl"
    journal.write_text(
        json.dumps({"event": "submitted",
                    "detail": {"client_id": "p", "role": "entry",
                               "reservation_id": "r"}}) + "\n"
        + json.dumps({"event": "fill",
                      "detail": {"client_id": "p", "exec_id": "T",
                                 "reservation_id": "r"}}) + "\n",
        encoding="utf-8")
    report = analyze_banked(cell, journal)
    assert report["row_buckets"] == {"unavailable_data": 50,
                                     "exposure_cooldown": 5}
    assert report["unmapped_reasons"] == {"strategy:brand:new": 2}
    assert report["unique_reservations"] == 1
    assert report["entries_filled"] == 1
    assert "REPEATED ROWS" in report["note"]
