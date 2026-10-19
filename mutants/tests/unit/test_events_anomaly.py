"""Anomaly policy tests (Worker 4, EV-001). Trip/hysteresis/cooldown."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.events.anomaly import (
    AnomalyBaseline,
    AnomalyConfig,
    AnomalyReading,
    AnomalyState,
    evaluate,
)

T0 = datetime(2026, 10, 12, 13, 10, tzinfo=timezone.utc)
BASE = AnomalyBaseline()


def _run(readings, config=None):
    config = config or AnomalyConfig()
    state = AnomalyState()
    out = []
    for step, reading in enumerate(readings):
        out.append(evaluate(config, reading, BASE, state,
                            T0 + timedelta(seconds=step)))
    return out, state


def test_quiet_reading_allows():
    decisions, _ = _run([AnomalyReading()])
    assert decisions[0].action == "allow"
    assert decisions[0].reason == "anomaly:clear"


def test_each_signal_trips_its_action():
    cases = [
        (AnomalyReading(spread_bps=30.0), "reject-entries", "spread"),
        (AnomalyReading(book_depth_ratio=0.1), "reject-entries",
         "book-thin"),
        (AnomalyReading(abs_return_bps=80.0), "cancel-entries",
         "shock-return"),
        (AnomalyReading(latency_ms=5000.0), "halt-entries", "latency"),
        (AnomalyReading(exchange_error_count=5), "halt-entries",
         "exchange-errors"),
    ]
    for reading, action, name in cases:
        decisions, _ = _run([reading])
        assert decisions[0].action == action, name
        assert name in decisions[0].reason


def test_worst_action_wins():
    reading = AnomalyReading(spread_bps=30.0, latency_ms=5000.0)
    decisions, _ = _run([reading])
    assert decisions[0].action == "halt-entries"
    assert decisions[0].triggered == ("latency", "spread")


def test_none_readings_never_trip_or_clear():
    config = AnomalyConfig(clear_streak=1, cooldown_s=0)
    state = AnomalyState()
    first = evaluate(config, AnomalyReading(spread_bps=30.0), BASE,
                     state, T0)
    assert first.action == "reject-entries"
    # Missing spread neither re-trips nor clears the open trip.
    second = evaluate(config, AnomalyReading(), BASE, state,
                      T0 + timedelta(seconds=1))
    assert second.action == "reject-entries"
    assert second.triggered == ("spread",)


def test_hysteresis_needs_clear_streak():
    config = AnomalyConfig(clear_streak=3, cooldown_s=0)
    state = AnomalyState()
    now = T0
    evaluate(config, AnomalyReading(spread_bps=30.0), BASE, state, now)
    clean = AnomalyReading(spread_bps=5.0)
    for step in range(1, 3):
        now = T0 + timedelta(seconds=step)
        decision = evaluate(config, clean, BASE, state, now)
        assert decision.action == "reject-entries", step
    decision = evaluate(config, clean, BASE, state,
                        T0 + timedelta(seconds=3))
    assert decision.action == "allow"
    assert decision.triggered == ()


def test_cooldown_holds_reject_after_clear():
    config = AnomalyConfig(clear_streak=1, cooldown_s=300)
    state = AnomalyState()
    evaluate(config, AnomalyReading(latency_ms=5000.0), BASE, state, T0)
    cleared = evaluate(config, AnomalyReading(latency_ms=100.0), BASE,
                       state, T0 + timedelta(seconds=1))
    assert cleared.action == "reject-entries"
    assert cleared.reason == "anomaly:cooldown"
    later = evaluate(config, AnomalyReading(latency_ms=100.0), BASE,
                     state, T0 + timedelta(seconds=302))
    assert later.action == "allow"


def test_new_breach_resets_streak():
    config = AnomalyConfig(clear_streak=2, cooldown_s=0)
    state = AnomalyState()
    evaluate(config, AnomalyReading(spread_bps=30.0), BASE, state, T0)
    evaluate(config, AnomalyReading(spread_bps=5.0), BASE, state,
             T0 + timedelta(seconds=1))
    evaluate(config, AnomalyReading(spread_bps=40.0), BASE, state,
             T0 + timedelta(seconds=2))
    decision = evaluate(config, AnomalyReading(spread_bps=5.0), BASE,
                        state, T0 + timedelta(seconds=3))
    assert decision.action == "reject-entries"
    assert state.ok_streak == 1


def test_config_validation():
    with pytest.raises(ValueError):
        AnomalyConfig(spread_widen_bps=-1.0)
    with pytest.raises(ValueError):
        AnomalyConfig(recovery_fraction=1.0)
    with pytest.raises(ValueError):
        AnomalyConfig(book_thin_ratio=1.5)
    with pytest.raises(ValueError):
        AnomalyReading(exchange_error_count=-1)
