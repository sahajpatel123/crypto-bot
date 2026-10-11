"""R-010 ledger partitioning, R-011 accounting day / timezone."""
from __future__ import annotations

from datetime import datetime

import pytest

from conftest import load_fixture
from cryptobot.accounting import Ledger, accounting_date

DAYS = load_fixture("risk_days.json")


def test_ist_midnight_boundaries():
    for case in DAYS["boundaries"]:
        assert accounting_date(datetime.fromisoformat(case["utc"])).isoformat() == case["accounting_date"]


def test_flows_partitioned_from_pnl():
    ledger = Ledger(pilot_equity=10000.0)
    assert ledger.marked_equity(67005.0) == 10000.0
    ledger.record_flow(500.0, "deposit", datetime.fromisoformat("2026-10-11T00:00:01+00:00"))
    assert ledger.marked_equity(67005.0) == 10500.0
    assert ledger.net_realised() == 0.0
    ledger.record_flow(-200.0, "transfer-out", datetime.fromisoformat("2026-10-11T06:00:00+00:00"))
    assert ledger.marked_equity(67005.0) == 10300.0
    assert ledger.net_realised() == 0.0
    assert ledger.paid_costs() == 0.0


def test_flows_since_day_start():
    ledger = Ledger(pilot_equity=10000.0)
    for flow in DAYS["flows"]:
        ledger.record_flow(flow["amount"], flow["kind"], datetime.fromisoformat(flow["utc"]))
    since = datetime.fromisoformat(DAYS["day_start_utc"])
    assert ledger.flows_since(since) == DAYS["expected_net_flows_since_day_start"]
    assert ledger.flow_adjusted(10300.0, since) == 10000.0


def test_fill_pnl_and_costs():
    ledger = Ledger(pilot_equity=10000.0)
    ts = datetime.fromisoformat("2026-10-11T12:00:00+00:00")
    ledger.record_fill("BUY", 0.1, 67000.0, fee=3.35, ts=ts)
    ledger.record_fill("SELL", 0.1, 67100.0, fee=3.355, ts=ts)
    assert ledger.net_realised() == pytest.approx(0.1 * 100.0 - 3.35 - 3.355)
    assert ledger.paid_costs() == pytest.approx(3.35 + 3.355)
    assert ledger.marked_equity(67100.0) == pytest.approx(10000.0 + ledger.net_realised())


def test_marked_vs_net_liquidation_distinct():
    ledger = Ledger(pilot_equity=10000.0)
    ts = datetime.fromisoformat("2026-10-11T12:00:00+00:00")
    ledger.record_fill("BUY", 0.1, 67000.0, fee=3.35, ts=ts)
    marked = ledger.marked_equity(67100.0)
    netliq = ledger.net_liquidation(67100.0, close_cost_bps=15.0)
    assert netliq < marked
    assert marked - netliq == pytest.approx(0.1 * 67100.0 * 15.0 / 10000)
