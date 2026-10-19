"""V-004 F-CEO-01: partial-close basis, funding, durable IDs, replay."""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from cryptobot.accounting import Ledger

T0 = datetime.fromisoformat("2026-10-11T12:00:00+00:00")


def test_partial_long_preserves_basis_ceo_numbers():
    ledger = Ledger(1000.0)
    ledger.record_fill("BUY", 10, 10, 0, T0)
    ledger.record_fill("SELL", 4, 11, 0, T0)
    assert ledger.entry_basis() == 10.0
    assert ledger.position_qty() == 6.0
    ledger.record_fill("SELL", 6, 12, 0, T0)
    assert ledger.net_realised() == 16.0
    assert ledger.marked_equity(12) - 1000 == 16.0
    assert ledger.entry_basis() is None


def test_partial_short_preserves_basis():
    ledger = Ledger(1000.0)
    ledger.record_fill("SELL", 10, 12, 0, T0)
    ledger.record_fill("BUY", 4, 11, 0, T0)
    assert ledger.entry_basis() == 12.0
    assert ledger.position_qty() == -6.0
    ledger.record_fill("BUY", 6, 10, 0, T0)
    assert ledger.net_realised() == 16.0
    assert ledger.entry_basis() is None


def test_reversal_long_to_short_with_fees():
    ledger = Ledger(1000.0)
    ledger.record_fill("BUY", 10, 10, 1, T0)
    assert ledger.record_fill("SELL", 14, 12, 1, T0) is True
    assert ledger.position_qty() == -4.0
    assert ledger.entry_basis() == 12.0
    assert ledger.net_realised() == 10 * 2 - 2
    assert ledger.paid_costs() == 2.0


def test_reversal_short_to_long():
    ledger = Ledger(1000.0)
    ledger.record_fill("SELL", 5, 20, 0, T0)
    ledger.record_fill("BUY", 8, 18, 0, T0)
    assert ledger.position_qty() == 3.0
    assert ledger.entry_basis() == 18.0
    assert ledger.net_realised() == 5 * 2


def test_funding_is_signed_trading_cash_flow():
    ledger = Ledger(1000.0)
    assert ledger.record_funding(-2.5, T0, event_id="f1") is True
    assert ledger.record_funding(1.0, T0, event_id="f2") is True
    assert ledger.record_funding(-2.5, T0, event_id="f1") is False
    assert ledger.net_realised() == -1.5
    assert ledger.funding_net() == -1.5
    assert ledger.paid_costs() == 0.0
    assert ledger.marked_equity(10) == 998.5


def test_flows_never_trading_pnl_with_fills_and_fees():
    ledger = Ledger(1000.0)
    ledger.record_flow(500.0, "deposit", T0, event_id="d1")
    ledger.record_fill("BUY", 1, 100, 2, T0, exec_id="e1")
    ledger.record_fill("SELL", 1, 110, 2, T0, exec_id="e2")
    ledger.record_flow(-100.0, "transfer-out", T0, event_id="w1")
    assert ledger.net_realised() == 10 - 4
    assert ledger.marked_equity(110) == 1000 + 500 - 100 + 10 - 4
    assert ledger.record_flow(500.0, "deposit", T0, event_id="d1") is False
    assert ledger.total_flows() == 400.0


def test_duplicate_fill_never_double_charges():
    ledger = Ledger(1000.0)
    assert ledger.record_fill("BUY", 10, 10, 1, T0, exec_id="e1") is True
    assert ledger.record_fill("BUY", 10, 10, 1, T0, exec_id="e1") is False
    assert ledger.paid_costs() == 1.0
    assert ledger.position_qty() == 10.0


def test_save_load_replay_exact_and_idempotent(tmp_path):
    ledger = Ledger(1000.0)
    ledger.record_fill("BUY", 10, 10, 1, T0, exec_id="e1")
    ledger.record_flow(50.0, "deposit", T0, event_id="d1")
    ledger.record_fill("SELL", 4, 11, 1, T0, exec_id="e2")
    ledger.record_funding(-0.5, T0, event_id="f1")
    path = tmp_path / "ledger.json"
    ledger.save(path)
    restored = Ledger.load(path)
    assert restored.to_dict() == ledger.to_dict()
    assert restored.net_realised() == ledger.net_realised()
    assert restored.entry_basis() == 10.0
    assert restored.record_fill("SELL", 4, 11, 1, T0, exec_id="e2") is False
    assert restored.net_realised() == ledger.net_realised()


def test_corrupt_snapshot_refuses_load(tmp_path):
    ledger = Ledger(1000.0)
    ledger.record_fill("BUY", 1, 100, 0, T0, exec_id="e1")
    path = tmp_path / "ledger.json"
    ledger.save(path)
    raw = json.loads(path.read_text())
    raw["snapshot"]["cash"] += 1.0
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="reconcile"):
        Ledger.load(path)


def test_nonfinite_inputs_rejected():
    ledger = Ledger(1000.0)
    with pytest.raises(ValueError):
        ledger.record_fill("BUY", float("nan"), 10, 0, T0)
    with pytest.raises(ValueError):
        ledger.record_fill("BUY", 1, float("inf"), 0, T0)
    with pytest.raises(ValueError):
        ledger.record_flow(float("nan"), "deposit", T0)
    with pytest.raises(ValueError):
        Ledger(float("nan"))
