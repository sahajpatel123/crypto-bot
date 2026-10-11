"""Strategy contract tests (Worker 1, Q-001): shared types + S1 conventions."""
import dataclasses
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.coordination import (
    DataQuality,
    ForecastCost,
    Intent,
    Side,
)
from cryptobot.strategies import contract as C


def test_no_duplicate_intent_type():
    """The strategy contract reuses the manager-owned Intent (shared type)."""
    assert C.Intent is Intent
    assert C.DecisionRecord.__module__ == "cryptobot.coordination.decision_record"
    assert C.ForecastCost is ForecastCost


def test_arm_ids_and_versions():
    assert C.ARM_IDS_S1 == ("S1", "S1-V", "S1-F")
    assert C.ARM_IDS_S2 == ("S2", "S2-V", "S2-F")
    assert C.ARM_IDS == C.ARM_IDS_S1 + C.ARM_IDS_S2
    assert C.STRATEGY_VERSION == "0.1.0"
    assert C.CONTRACT_VERSION == "v0.1.1"


def test_s1_cost_preset_nonzero_labelled():
    cost = C.S1_FORECAST_COST
    assert cost.fee_bps > 0 and cost.spread_bps > 0
    assert cost.slippage_bps > 0 and cost.funding_bps > 0
    assert cost.label == "conservative-simulation"
    with pytest.raises(dataclasses.FrozenInstanceError):
        cost.fee_bps = 0.0  # type: ignore[misc]


def test_s2_cost_preset_matches_s1_values():
    assert C.S2_FORECAST_COST == C.S1_FORECAST_COST
    assert C.S2_FORECAST_COST.label == "conservative-simulation"


def test_evidence_ref_format():
    ts = datetime(2026, 1, 2, 0, 2, 34, tzinfo=timezone.utc)
    ref = C.build_evidence_ref("S1", "0.1.0", "BTCUSDT", Side.LONG, ts)
    assert ref == "S1:0.1.0:BTCUSDT:LONG:2026-01-02T00:02:34+00:00"
    assert C.build_evidence_ref("S1", "0.1.0", "BTCUSDT", Side.LONG, ts) == ref


def _intent_kwargs(**kw):
    now = datetime.now(timezone.utc)
    base = dict(
        strategy="S1", instrument="BTCUSDT", side=Side.LONG,
        evidence_ts_utc=now, entry_low=100.0, entry_high=101.0,
        entry_expiry_utc=now + timedelta(seconds=15),
        invalidation_price=99.0, exit_rule="S1_EXIT_V1:take_r=1.5,stop_r=1.0",
        holding_limit_s=120, evidence_ref="r", data_quality=DataQuality.CLEAN,
        data_quality_reason="no-gaps-N=120",
    )
    base.update(kw)
    return base


def test_build_intent_ok_and_defaults():
    intent = C.build_intent(**_intent_kwargs())
    assert intent.version == "0.1.0"
    assert intent.forecast_cost is C.S1_FORECAST_COST
    s2 = C.build_intent(**_intent_kwargs(strategy="S2-V",
                                         forecast_cost=C.S2_FORECAST_COST))
    assert s2.strategy == "S2-V"


def test_build_intent_rejects_convention_violations():
    with pytest.raises(ValueError):
        C.build_intent(**_intent_kwargs(strategy="S9"))
    with pytest.raises(ValueError):
        C.build_intent(**_intent_kwargs(version="9.9.9"))
    bad_cost = ForecastCost(1, 1, 1, 1, label="optimistic-live")
    with pytest.raises(ValueError):
        C.build_intent(**_intent_kwargs(forecast_cost=bad_cost))


def test_build_intent_enforces_structural_invariants():
    with pytest.raises(ValueError):
        C.build_intent(**_intent_kwargs(entry_low=102.0, entry_high=101.0))
    with pytest.raises(ValueError):
        C.build_intent(**_intent_kwargs(invalidation_price=100.5))  # LONG: must be < low
    with pytest.raises(ValueError):
        C.build_intent(**_intent_kwargs(
            side=Side.SHORT, entry_low=100.0, entry_high=101.0,
            invalidation_price=100.5))  # SHORT: must be > high
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError):
        C.build_intent(**_intent_kwargs(entry_expiry_utc=now - timedelta(seconds=1)))
    with pytest.raises(ValueError):
        C.build_intent(**_intent_kwargs(holding_limit_s=0))
