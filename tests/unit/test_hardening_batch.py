"""P2-P6 batch: breaker, alerts, ladder, costs, maker queue, verdict,
gate/arm refusal, data verify, watchdog."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from cryptobot import cli
from cryptobot.app.producer import DropBreaker
from cryptobot.execution.fill_realism import maker_fill
from cryptobot.monitoring.alerts import MemorySink, RateLimitedSink
from cryptobot.research.cost_model_v2 import breakeven_table
from cryptobot.research.verdict import evaluate_trades
from cryptobot.risk.ladder import canary_size, demotion_reasons


def test_drop_breaker_hysteresis():
    b = DropBreaker(trip_rate=0.02, resume_rate=0.005, min_sample=100)
    assert b.observe(100, 5) is True   # 5% > 2% trip
    # 5/1000 = 0.5% is NOT below resume_rate (strict <): stays tripped
    assert b.observe(900, 0) is True
    b2 = DropBreaker(trip_rate=0.02, resume_rate=0.005, min_sample=100)
    b2.observe(100, 5)
    assert b2.observe(1000, 0) is False  # 5/1100 < 0.5% resumes


def test_alerts_rate_limited_fake_sink():
    mem = MemorySink()
    times = iter([0.0, 10.0, 100.0])
    sink = RateLimitedSink(mem, min_interval_s=60.0,
                           now=lambda: next(times))
    assert sink.send("protection-gap", {}) is True
    assert sink.send("protection-gap", {}) is False  # suppressed
    assert sink.send("protection-gap", {}) is True
    assert sink.suppressed == 1 and len(mem.sent) == 2


def test_ladder_demotion_and_canary():
    assert demotion_reasons(slippage_ratio=1.6) == ("slippage>1.5x-assumed",)
    assert demotion_reasons(expectancy_ci_upper_bps=-1.0,
                            expectancy_n=40) == ("expectancy-ci-upper<0",)
    assert canary_size(trade_index=0, canary_trades=10, min_qty=0.001,
                       planned_qty=0.01) == 0.001
    assert canary_size(trade_index=10, canary_trades=10, min_qty=0.001,
                       planned_qty=0.01) == 0.01


def test_cost_table_taker_needs_high_win_rate():
    rows = breakeven_table()
    row = next(r for r in rows if r["stop_bps"] == 25.0
               and r["entry"] == "taker" and r["stress"] == 1.0)
    assert row["round_trip_bps"] >= 13.0
    assert row["required_win_rate"] > 0.6


def test_maker_queue_no_credit_for_touches():
    # Touch at limit with queue ahead: no fill. Trade-through: fills.
    assert maker_fill(side="BUY", limit_price=100.0, qty=1.0,
                      queue_ahead_qty=2.0,
                      trades=[(100.0, 1.0)]) == 0.0
    assert maker_fill(side="BUY", limit_price=100.0, qty=1.0,
                      queue_ahead_qty=2.0,
                      trades=[(100.0, 3.0)]) == 1.0
    assert maker_fill(side="BUY", limit_price=100.0, qty=1.0,
                      queue_ahead_qty=2.0,
                      trades=[(99.0, 0.4)]) == pytest.approx(0.4)


def test_verdict_underpowered_and_fail():
    out = evaluate_trades([5.0] * 10, adverse_bps=[5.0] * 10,
                          days=["d1"] * 10, max_dd_bps=0.0,
                          dd_budget_bps=500.0)
    assert out["verdict"] == "UNDERPOWERED"
    out = evaluate_trades([-5.0] * 400, adverse_bps=[-8.0] * 400,
                          days=[f"d{k % 20}" for k in range(400)],
                          max_dd_bps=100.0, dd_budget_bps=500.0)
    assert out["verdict"] == "FAIL"


def test_gate_no_go_and_arm_refuses(tmp_path, capsys, monkeypatch):
    rc = cli.cmd_gate(argparse.Namespace(
        verdict_json=None, drill_json=None, latency_json=None,
        out=str(tmp_path / "gate.json")))
    assert rc == 2
    assert json.loads((tmp_path / "gate.json").read_text())["gate"] == "NO-GO"
    monkeypatch.delenv("CRYPTOBOT_ARM_ACK", raising=False)
    rc = cli.cmd_arm(argparse.Namespace(
        capital_usdt=100.0, max_daily_loss=5.0,
        gate_json=str(tmp_path / "gate.json"),
        out=str(tmp_path / "armed.json")))
    assert rc == 2 and not (tmp_path / "armed.json").exists()


def test_data_verify(tmp_path, capsys):
    cap = tmp_path / "cap"
    cap.mkdir()
    (cap / "events.jsonl").write_text('{"a": 1}\n{"a": 2}\n')
    assert cli.cmd_data(argparse.Namespace(
        data_cmd="verify", capture=str(cap))) == 0
    assert cli.cmd_data(argparse.Namespace(
        data_cmd="verify", capture=str(tmp_path / "nope"))) == 2


def test_watchdog_stale_exposed(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "watchdog", Path("tools/watchdog.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    hb = tmp_path / "hb.json"
    hb.write_text(json.dumps({"ts_utc": "2000-01-01T00:00:00+00:00",
                              "has_exposure": True, "run_id": "x"}))
    status = mod.heartbeat_status(hb, max_age_s=90.0)
    assert status["stale"] is True and status["has_exposure"] is True


def test_soak_burst_bounded_queue():
    import time as _t

    from cryptobot.app.producer import BoundedProducer, TIMEOUT

    def gen():
        for i in range(5000):
            yield {"channel": "aggTrade", "seq": i}

    prod = BoundedProducer(gen(), maxsize=100)
    deadline = _t.time() + 10
    seen = 0
    while not prod.finished and _t.time() < deadline:
        if prod.poll(0.05) is not TIMEOUT:
            seen += 1
    _t.sleep(0.3)
    assert prod.qsize <= 100
    assert prod.dropped > 0
    assert sum(prod.dropped_by_type.values()) == prod.dropped
    prod.close()
