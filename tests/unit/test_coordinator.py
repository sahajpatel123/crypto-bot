"""Coordinator selection tests (manager-owned, CONTRACTS v0.1.0 rules)."""
from datetime import UTC, datetime, timedelta

from cryptobot.coordination import (
    Coordinator,
    DataQuality,
    ForecastCost,
    Intent,
    Side,
)


def _intent(side=Side.LONG, **kw):
    now = datetime.now(UTC)
    base = dict(strategy="S1", version="0.1.0", instrument="BTCUSDT", side=side,
                evidence_ts_utc=now, entry_low=100.0, entry_high=101.0,
                entry_expiry_utc=now + timedelta(seconds=60),
                invalidation_price=99.0 if side == Side.LONG else 102.0,
                exit_rule="inv", holding_limit_s=60,
                forecast_cost=ForecastCost(1, 1, 1, 0),
                evidence_ref="r", data_quality=DataQuality.CLEAN)
    base.update(kw)
    return Intent(**base)


def test_dedup_same_direction_single_owner():
    coord = Coordinator()
    first, dup = _intent(), _intent()
    decision = coord.select([first, dup])
    assert decision.accepted is first
    assert dup in decision.rejected


def test_opposing_signals_stand_aside():
    coord = Coordinator()
    decision = coord.select([_intent(Side.LONG), _intent(Side.SHORT)])
    assert decision.accepted is None
    assert "stand-aside" in decision.reason


def test_stale_and_halt_rejected():
    coord = Coordinator()
    now = datetime.now(UTC)
    stale = _intent(evidence_ts_utc=now - timedelta(seconds=120),
                      entry_expiry_utc=now - timedelta(seconds=1))
    halted = _intent(data_quality=DataQuality.HALT)
    decision = coord.select([stale, halted], now)
    assert decision.accepted is None
