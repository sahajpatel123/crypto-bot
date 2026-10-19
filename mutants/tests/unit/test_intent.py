"""Intent schema unit tests (manager-owned bootstrap)."""
from datetime import datetime, timedelta, timezone

import pytest

from cryptobot.coordination import DataQuality, ForecastCost, Intent, Side


def _intent(**kw):
    now = datetime.now(timezone.utc)
    base = dict(strategy="S1", version="0.1.0", instrument="BTCUSDT", side=Side.LONG,
                evidence_ts_utc=now, entry_low=100.0, entry_high=101.0,
                entry_expiry_utc=now + timedelta(seconds=60), invalidation_price=99.0,
                exit_rule="inv", holding_limit_s=60, forecast_cost=ForecastCost(1, 1, 1, 0),
                evidence_ref="r", data_quality=DataQuality.CLEAN)
    base.update(kw)
    return Intent(**base)


def test_intent_valid():
    assert _intent().holding_limit_s == 60


def test_intent_rejects_bad_bounds():
    with pytest.raises(ValueError):
        _intent(entry_low=102.0, entry_high=101.0)


def test_intent_rejects_wrong_side_invalidation():
    with pytest.raises(ValueError):
        _intent(invalidation_price=102.0)
