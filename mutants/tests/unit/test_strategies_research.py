"""Research tests (Worker 1, Q-001): fixtures, registry, splits, trial log."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.research.experiments import (
    EXP_001,
    EXP_002,
    EXP_003,
    EXP_004,
    NET_S1_V1,
    S1_SCENARIOS,
    S2_SCENARIOS,
    S3_SCENARIOS,
    S4_SCENARIOS,
    TRAIN_SEEDS,
    TRAIN_SEEDS_S2,
    TRAIN_SEEDS_S3,
    TRAIN_SEEDS_S4,
    VALIDATION_SEEDS,
    VALIDATION_SEEDS_S2,
    VALIDATION_SEEDS_S3,
    VALIDATION_SEEDS_S4,
    TrialLog,
    TrialRecord,
    split_indices,
)
from cryptobot.research.synthetic import (
    GENERATOR_ID,
    SCENARIOS,
    SCENARIO_CHOPPY,
    SCENARIO_FLAT,
    SCENARIO_GAP,
    SCENARIO_LONG,
    SCENARIO_S2_LONG,
    SCENARIO_S2_SHORT,
    SCENARIO_S3_LONG,
    SCENARIO_S3_SHORT,
    SCENARIO_S4_LONG,
    SCENARIO_S4_SHORT,
    SCENARIO_SHORT,
    SCENARIO_WIDE_SPREAD,
    generate_fixture,
)
from cryptobot.strategies.contract import (
    ARM_IDS_S1,
    ARM_IDS_S2,
    ARM_IDS_S3,
    ARM_IDS_S4,
)


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
    assert tuple(EXP_001["arms"]) == ARM_IDS_S1
    assert len(EXP_001["arms"]) == 3
    assert tuple(EXP_001["train_seeds"]) == TRAIN_SEEDS
    assert tuple(EXP_001["validation_seeds"]) == VALIDATION_SEEDS
    assert set(TRAIN_SEEDS).isdisjoint(VALIDATION_SEEDS)
    assert "NONE" in EXP_001["promotion_rule"]
    assert "2*(fee+slippage)" in NET_S1_V1
    assert "conservative-simulation" in NET_S1_V1


def test_exp001_frozen_despite_later_additions():
    assert tuple(EXP_001["scenarios"]) == S1_SCENARIOS
    assert len(S1_SCENARIOS) == 6
    assert tuple(EXP_002["scenarios"]) == S2_SCENARIOS
    assert len(SCENARIOS) == 12  # generator grew; preregistrations did not


def test_exp002_preregistered_bounded_unpromoted():
    assert EXP_002["status"] == "preregistered"
    assert EXP_002["trials_executed"] == 0
    assert tuple(EXP_002["arms"]) == ARM_IDS_S2
    assert tuple(EXP_002["scenarios"]) == S2_SCENARIOS
    assert tuple(EXP_002["train_seeds"]) == TRAIN_SEEDS_S2 == (31, 32, 33)
    assert tuple(EXP_002["validation_seeds"]) == VALIDATION_SEEDS_S2 == (41, 42)
    assert set(TRAIN_SEEDS_S2).isdisjoint(VALIDATION_SEEDS_S2)
    assert set(TRAIN_SEEDS_S2 + VALIDATION_SEEDS_S2).isdisjoint(
        TRAIN_SEEDS + VALIDATION_SEEDS)
    assert "NONE" in EXP_002["promotion_rule"]


def test_s2_fixture_construction():
    fx = generate_fixture(seed=31, scenario=SCENARIO_S2_LONG)
    bars = fx.bars
    assert bars[0] is not None and bars[199] is not None
    assert bars[207] is not None and bars[212] is not None
    assert bars[199].close > bars[0].close  # trend up
    assert bars[207].close < bars[199].close  # pullback down
    assert bars[212].close > bars[207].close  # resumption up
    assert all(b.source == "synthetic" for b in bars if b is not None)
    mirror = generate_fixture(seed=31, scenario=SCENARIO_S2_SHORT).bars
    assert mirror[0] is not None and mirror[199] is not None
    assert mirror[199].close < mirror[0].close


def test_exp003_exp004_preregistered_bounded_unpromoted():
    assert EXP_003["status"] == "preregistered"
    assert EXP_003["trials_executed"] == 0
    assert tuple(EXP_003["arms"]) == ARM_IDS_S3
    assert tuple(EXP_003["scenarios"]) == S3_SCENARIOS
    assert tuple(EXP_003["train_seeds"]) == TRAIN_SEEDS_S3 == (51, 52, 53)
    assert tuple(EXP_003["validation_seeds"]) == VALIDATION_SEEDS_S3 == (61, 62)
    assert "NONE" in EXP_003["promotion_rule"]
    assert EXP_004["status"] == "preregistered"
    assert EXP_004["trials_executed"] == 0
    assert tuple(EXP_004["arms"]) == ARM_IDS_S4
    assert tuple(EXP_004["scenarios"]) == S4_SCENARIOS
    assert tuple(EXP_004["train_seeds"]) == TRAIN_SEEDS_S4 == (71, 72, 73)
    assert tuple(EXP_004["validation_seeds"]) == VALIDATION_SEEDS_S4 == (81, 82)
    assert "NONE" in EXP_004["promotion_rule"]
    assert set(TRAIN_SEEDS_S3 + VALIDATION_SEEDS_S3).isdisjoint(
        TRAIN_SEEDS_S4 + VALIDATION_SEEDS_S4)


def test_s3_s4_fixture_construction():
    s3 = generate_fixture(seed=51, scenario=SCENARIO_S3_LONG).bars
    assert s3[0] is not None and s3[159] is not None and s3[210] is not None
    assert s3[159].close > s3[0].close  # range edge formed
    assert abs(s3[210].close - s3[0].close) / s3[0].close < 4.0 / 1e4  # touch
    assert all(b.source == "synthetic" for b in s3 if b is not None)
    s3m = generate_fixture(seed=51, scenario=SCENARIO_S3_SHORT).bars
    assert s3m[0] is not None and s3m[159] is not None
    assert s3m[159].close < s3m[0].close
    s4 = generate_fixture(seed=71, scenario=SCENARIO_S4_SHORT).bars
    assert s4[196] is not None and s4[199] is not None
    assert s4[196].close > s4[190].close  # pierce above the level
    assert s4[199].close < s4[190].close  # reclaimed back inside
    s4m = generate_fixture(seed=71, scenario=SCENARIO_S4_LONG).bars
    assert s4m[196] is not None and s4m[190] is not None
    assert s4m[196].close < s4m[190].close


def test_persisted_fixtures_match_generator():
    import json
    from pathlib import Path

    from cryptobot.research.synthetic import Fixture

    root = Path(__file__).resolve().parent.parent / "fixtures"
    for name, scenario, seed in (
        ("synth_s3_long.json", SCENARIO_S3_LONG, 51),
        ("synth_s3_short.json", SCENARIO_S3_SHORT, 51),
        ("synth_s4_long.json", SCENARIO_S4_LONG, 71),
        ("synth_s4_short.json", SCENARIO_S4_SHORT, 71),
    ):
        frozen = Fixture.from_dict(
            json.loads((root / name).read_text(encoding="utf-8")))
        fresh = generate_fixture(seed=seed, scenario=scenario)
        assert frozen.to_dict() == fresh.to_dict()


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
