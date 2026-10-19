"""V-003 slice wiring: real S1 intent -> SliceRisk -> (ok, reason, notional).

Also covers RiskOutcomeSink conformance and duplicate-callback tolerance
(the E-003 residual re-fire window is risk's to tolerate).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from conftest import NOW, build_intent, load_fixture, make_clock
from cryptobot.coordination import RiskOutcomeSink, Side
from cryptobot.research.synthetic import SCENARIO_LONG, generate_fixture
from cryptobot.risk import SliceRisk
from cryptobot.strategies.contract import ARM_BASE
from cryptobot.strategies.s1 import Bar, evaluate_side

INTENTS = load_fixture("risk_intents.json")


def _s1_long(now=NOW):
    fix = generate_fixture(seed=11, scenario=SCENARIO_LONG)
    fire_t = next(
        t for t in range(120, len(fix.bars))
        if evaluate_side(list(fix.bars), t, Side.LONG, ARM_BASE, "BTCUSDT").intent is not None
    )
    shift = (now - timedelta(seconds=5)) - fix.bars[fire_t].ts_utc
    shifted = [
        Bar(ts_utc=b.ts_utc + shift, open=b.open, high=b.high, low=b.low,
            close=b.close, volume=b.volume, trades=b.trades,
            buy_frac=b.buy_frac, spread_bps=b.spread_bps, source=b.source)
        if b is not None else None
        for b in fix.bars[:fire_t + 1]
    ]
    dec = evaluate_side(shifted, fire_t, Side.LONG, ARM_BASE, "BTCUSDT")
    assert dec.intent is not None
    return dec.intent


def _wiring(tmp_path):
    return SliceRisk(state_path=tmp_path / "slice_state.json",
                     day_start_equity=100.0, now_utc=make_clock())


def test_wiring_approves_real_s1_intent(tmp_path):
    wiring = _wiring(tmp_path)
    intent = _s1_long()
    mid = (intent.entry_low + intent.entry_high) / 2
    out = wiring.evaluate(intent, mid)
    assert out.ok is True
    assert out.reservation_id == "r-000001"
    assert out.reason.startswith("risk-policy:approved:reservation=r-000001:budget=")
    assert "risk-stub" not in out.reason
    assert out.notional_usdt > 0.0
    assert out.qty == pytest.approx(out.notional_usdt / intent.entry_high)


def test_wiring_rejects_stale_with_policy_reason(tmp_path):
    wiring = _wiring(tmp_path)
    out = wiring.evaluate(build_intent(INTENTS["expired"]), 67005.0)
    assert out.ok is False
    assert out.reason == "risk-policy:rejected:stale:expired"
    assert out.notional_usdt == 0.0 and out.reservation_id is None


def test_wiring_fill_lifecycle_blocks_second_entry(tmp_path):
    wiring = _wiring(tmp_path)
    intent = _s1_long()
    mid = (intent.entry_low + intent.entry_high) / 2
    first = wiring.evaluate(intent, mid)
    assert first.ok
    wiring.note_slice_fill(first.reservation_id, "BUY", first.qty, mid)
    assert wiring.ledger.has_position()
    second = wiring.evaluate(intent, mid)
    assert second.ok is False
    assert second.reason == "risk-policy:rejected:exposure:one-position"
    wiring.ledger.record_fill("SELL", first.qty, mid, 0.0, NOW)
    wiring.note_slice_flat()
    assert wiring.evaluate(intent, mid).ok is True


def test_policy_conforms_to_risk_outcome_sink(tmp_path):
    assert isinstance(_wiring(tmp_path).policy, RiskOutcomeSink)


def test_duplicate_callbacks_tolerated(tmp_path):
    wiring = _wiring(tmp_path)
    intent = _s1_long()
    mid = (intent.entry_low + intent.entry_high) / 2
    first = wiring.evaluate(intent, mid)
    assert first.ok
    # E-003 residual window: a re-fired fill/flat must not corrupt state.
    wiring.policy.note_fill(first.reservation_id)
    wiring.policy.note_fill(first.reservation_id)
    assert wiring.evaluate(intent, mid).ok is False
    wiring.policy.note_flat()
    wiring.policy.note_flat()
    assert wiring.evaluate(intent, mid).ok is True
    assert wiring.policy.release("r-000002") is True
    assert wiring.policy.release("r-000002") is False
    assert wiring.policy.release("r-never-issued") is False
