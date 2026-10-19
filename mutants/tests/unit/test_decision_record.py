"""Decision-record tests (manager-owned)."""
import dataclasses

import pytest

from cryptobot.coordination.decision_record import DecisionRecord, FeatureEvidence
from cryptobot.coordination.intent import DataQuality, Side


def _record(**kw):
    base = dict(record_id="r1", side=Side.LONG, regime="compression",
                features=(FeatureEvidence("range", "120s", "<0.5*vol", "0.3*vol"),),
                trigger="close>upper", rejects_evaluated=("chase=pass",),
                data_quality=DataQuality.CLEAN)
    base.update(kw)
    return DecisionRecord(**base)


def test_record_valid():
    assert _record().record_id == "r1"


def test_record_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        _record().regime = "other"  # type: ignore[misc]


def test_record_requires_evidence():
    with pytest.raises(ValueError):
        _record(features=())
    with pytest.raises(ValueError):
        _record(regime="")
    with pytest.raises(ValueError):
        _record(trigger="")
