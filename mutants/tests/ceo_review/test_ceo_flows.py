"""F-CEO-06: external flows are not trading results (target/halt wiring)."""
from helpers import T0, audit_intent, make_clock

from cryptobot.risk import SliceRisk


def test_deposit_does_not_trigger_daily_target(tmp_path):
    cell, clock = make_clock()
    gate = SliceRisk(state_path=tmp_path / "risk.json",
                     day_start_equity=1000, now_utc=clock)
    gate.ledger.record_flow(30, "deposit", cell[0])
    assert gate.ledger.net_realised() == 0
    decision = gate.evaluate(audit_intent(cell[0]), 100)
    assert decision.ok  # no trading profit -> no target pause


def test_withdrawal_does_not_trip_halt_or_target(tmp_path):
    cell, clock = make_clock()
    gate = SliceRisk(state_path=tmp_path / "risk.json",
                     day_start_equity=1000, now_utc=clock)
    gate.ledger.record_flow(-30, "withdrawal", cell[0])
    assert gate.ledger.net_realised() == 0
    decision = gate.evaluate(audit_intent(cell[0]), 100)
    assert decision.ok  # capital movement, not a trading loss


def test_flows_never_become_realised_pnl(tmp_path):
    cell, clock = make_clock()
    gate = SliceRisk(state_path=tmp_path / "risk.json",
                     day_start_equity=1000, now_utc=clock)
    gate.ledger.record_flow(30, "deposit", cell[0])
    gate.ledger.record_flow(-30, "withdrawal", cell[0])
    assert gate.ledger.net_realised() == 0
