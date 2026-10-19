"""ROUND-01 freeze + discarded-trial tests (Worker 4, 30MIN)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cryptobot.research.experiments import (  # noqa: E402
    REGISTRY_VERSION,
    ROUND_01,
    TrialLog,
    TrialRecord,
)


def test_round_01_frozen_shape():
    assert REGISTRY_VERSION == "0.4.0"
    assert ROUND_01["round_id"] == "ROUND-01"
    assert ROUND_01["status"] == "preregistered"
    assert ROUND_01["trials_executed"] == 0
    configs = ROUND_01["configs"]
    assert len(configs) == 11
    assert len(configs) <= 12
    ids = [c["config_id"] for c in configs]
    assert len(set(ids)) == 11
    roles = {c["role"] for c in configs}
    assert {"baseline", "variant", "portfolio", "benchmark"} <= roles
    fams = {c["family"] for c in configs if c["role"] == "baseline"}
    assert fams == {"S1", "S2", "S3", "S4"}
    assert ROUND_01["splits"]["purge_s"] == 300
    assert "holdout" in ROUND_01["splits"]
    assert "stopping_rule" in ROUND_01 and ROUND_01["stopping_rule"]
    excluded = {(e.get("family"), e.get("arm")) for e in ROUND_01["excluded"]}
    assert ("S5", None) in excluded


def test_round_01_json_matches_code():
    repo = Path(__file__).resolve().parents[2]
    filed = json.loads((repo / "trials" / "round-01.json").read_text())
    assert filed == ROUND_01


def test_discarded_trials_stay_recorded():
    log = TrialLog()
    log.log_trial(TrialRecord(
        trial_id="R01-S1-dev", exp_id="ROUND-01", arm="R01-S1", seed=7,
        split="development", status="discarded",
        reason="dataset lacks quotes for the window", utc="t"))
    log.log_trial(TrialRecord(
        trial_id="R01-S2-dev", exp_id="ROUND-01", arm="R01-S2", seed=7,
        split="development", status="failed", reason="engine crash",
        utc="t"))
    assert [t.trial_id for t in log.discarded()] == ["R01-S1-dev"]
    assert [t.trial_id for t in log.failed()] == ["R01-S2-dev"]
    with pytest.raises(ValueError, match="duplicate"):
        log.log_trial(TrialRecord(
            trial_id="R01-S1-dev", exp_id="ROUND-01", arm="R01-S1",
            seed=7, split="development", status="ok", reason="",
            utc="t"))
