"""v0.2.0 addendum: fill-delta propagation (F-CEO-02/03 seam).

Risk implements `note_fill_delta(...)` (idempotent by exec_id, validated
before booking); first nonzero delta marks exposure. Black-box behavior
expectations for the fix-after runs; pre-fix runs fail on the missing API.
"""
import pytest
from helpers import make_clock

from cryptobot.risk import SliceRisk


def _slice(tmp_path):
    cell, clock = make_clock()
    gate = SliceRisk(state_path=tmp_path / "risk.json",
                     day_start_equity=1000, now_utc=clock)
    return cell, clock, gate


def _delta(gate, exec_id, qty=2.0, price=100.0, fee=1.0, side="BUY",
           ts="2026-10-11T12:00:00+00:00"):
    gate.policy.note_fill_delta("r-000001", exec_id, "BTCUSDT", side,
                                qty, price, fee, ts)


def test_sink_exposes_fill_delta(tmp_path):
    _, _, gate = _slice(tmp_path)
    assert hasattr(gate.policy, "note_fill_delta"), \
        "sink must expose note_fill_delta (v0.2.0 addendum)"


def test_duplicate_delta_booked_once(tmp_path):
    _, _, gate = _slice(tmp_path)
    assert hasattr(gate.policy, "note_fill_delta"), \
        "sink must expose note_fill_delta (v0.2.0 addendum)"
    _delta(gate, "exec-1")
    _delta(gate, "exec-1")  # at-least-once redelivery
    assert gate.ledger.position_qty() == 2.0
    assert gate.ledger.paid_costs() == 1.0  # never double-charged


def test_delta_validation_rejects_before_booking(tmp_path):
    _, _, gate = _slice(tmp_path)
    assert hasattr(gate.policy, "note_fill_delta"), \
        "sink must expose note_fill_delta (v0.2.0 addendum)"
    with pytest.raises(ValueError):
        _delta(gate, "exec-bad", qty=float("nan"))
    assert gate.ledger.position_qty() == 0.0
    assert gate.ledger.paid_costs() == 0.0
