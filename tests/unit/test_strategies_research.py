"""Research tests (Worker 1, Q-001): fixtures, registry, splits, trial log."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.research.experiments import (
    EXP_001,
    NET_S1_V1,
    TRAIN_SEEDS,
    VALIDATION_SEEDS,
    TrialLog,
    TrialRecord,
    split_indices,
)
from cryptobot.research.synthetic import (
    GENERATOR_ID,
    SCENARIO_CHOPPY,
    SCENARIO_FLAT,
    SCENARIO_GAP,
    SCENARIO_LONG,
    SCENARIO_SHORT,
    SCENARIO_WIDE_SPREAD,
    generate_fixture,
)
from cryptobot.strategies.contract import ARM_IDS


def test_fixture_deterministic_and_labelled():
    a = generate_fixture(seed=11, scenario=SCENARIO_LONG)
    b = generate_fixture(seed=11, scenario=SCENARIO_LONG)
    assert a.to_dict() == b.to_dict()
    assert a.label == "synthetic" and a.generator == GENERATOR_ID
    assert all(bar.source == "synthetic" for bar in a.bars if bar is not None)


def test_scenario_constructions():
    long = generate_fixture(seed=11, scenario=SCENARIO_LONG).bars
    assert long[154] is not None and long[0] is not None
    assert long[154].close > long[0].close
    short = generate_fixture(seed=11, scenario=SCENARIO_SHORT).bars
    assert short[154] is not None and short[0] is not None
    assert short[154].close < short[0].close
    flat = generate_fixture(seed=11, scenario=SCENARIO_FLAT).bars
    closes = {b.close for b in flat if b is not None}
    assert len(closes) == 1
    gap = generate_fixture(seed=11, scenario=SCENARIO_GAP).bars
    assert all(b is None for b in gap[160:163])
    assert all(b is None for b in gap[200:207])
    assert gap[159] is not None and gap[163] is not None
    wide = generate_fixture(seed=11, scenario=SCENARIO_WIDE_SPREAD).bars
    assert all(b is not None and b.spread_bps == 10.0 for b in wide[150:160])
    choppy = generate_fixture(seed=11, scenario=SCENARIO_CHOPPY).bars
    assert all(b is not None for b in choppy)


def test_fixture_json_round_trip_and_guards():
    f = generate_fixture(seed=21, scenario=SCENARIO_FLAT)
    from cryptobot.research.synthetic import Fixture

    assert Fixture.from_dict(json.loads(json.dumps(f.to_dict()))) == f
    with pytest.raises(ValueError):
        generate_fixture(seed=1, scenario="nope")
    with pytest.raises(ValueError):
        generate_fixture(seed=1, scenario=SCENARIO_FLAT, n_bars=50)


def test_split_indices_70_5_25_with_embargo():
    s = split_indices(240)
    assert (s.train_end, s.val_start) == (168, 180)
    assert len(range(0, s.train_end)) == 168
    assert len(range(s.train_end, s.val_start)) == 12  # embargo excluded
    assert len(range(s.val_start, 240)) == 60
    with pytest.raises(ValueError):
        split_indices(10)


def test_exp001_preregistered_bounded_unpromoted():
    assert EXP_001["status"] == "preregistered"
    assert EXP_001["trials_executed"] == 0
    assert tuple(EXP_001["arms"]) == ARM_IDS
    assert len(EXP_001["arms"]) == 3
    assert tuple(EXP_001["train_seeds"]) == TRAIN_SEEDS
    assert tuple(EXP_001["validation_seeds"]) == VALIDATION_SEEDS
    assert set(TRAIN_SEEDS).isdisjoint(VALIDATION_SEEDS)
    assert "NONE" in EXP_001["promotion_rule"]
    assert "2*(fee+slippage)" in NET_S1_V1
    assert "conservative-simulation" in NET_S1_V1


def test_trial_log_keeps_failed_trials():
    log = TrialLog()
    assert log.failed() == []
    log.log_trial(TrialRecord("t1", "EXP-001", "S1", 11, "train", "ok",
                              "done", TrialRecord.utcnow(), (("n", "6"),)))
    log.log_trial(TrialRecord("t2", "EXP-001", "S1-V", 11, "train", "failed",
                              "replay-gap", TrialRecord.utcnow()))
    assert [t.trial_id for t in log.failed()] == ["t2"]
    assert len(json.loads(log.to_json())) == 2
    with pytest.raises(ValueError):
        log.log_trial(TrialRecord("t1", "EXP-001", "S1", 11, "train", "ok",
                                  "dup", TrialRecord.utcnow()))
