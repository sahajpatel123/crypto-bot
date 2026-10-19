import pytest

from cryptobot.research.autopilot import Autopilot
from cryptobot.research.power import confirm_eta, trades_needed

DEV_GOOD = {"expectancy_bps": 5.0, "ci_lb_bps": 1.0, "folds_positive": 1.0,
            "sd_bps": 40.0, "trades_per_day": 50.0, "config_hash": "abc"}
DEV_BAD = {"expectancy_bps": -1.0, "ci_lb_bps": -3.0, "folds_positive": 0.0}


def test_power_math():
    assert trades_needed(0, 40) == float("inf")
    assert confirm_eta(5, 40, 50)["verdict"] == "FEASIBLE"
    assert confirm_eta(0.1, 40, 1)["verdict"] == "IMPRACTICAL"


def test_kill_path_and_chain(tmp_path):
    a = Autopilot(tmp_path)
    assert a.run_once("H9") == "DEV_EVAL"
    assert a.run_once("H9", dev=DEV_BAD) == "KILLED"
    assert a.verify_chain("H9") is True
    assert a.run_once("H9") == "KILLED"  # idempotent terminal


def test_full_path_to_gate_ready(tmp_path):
    a = Autopilot(tmp_path)
    a.run_once("H1")
    a.run_once("H1", dev=DEV_GOOD)
    assert a.state["hypotheses"]["H1"]["state"] == "AWAIT_CONFIRM_DATA"
    a.run_once("H1", confirm_verdict={"verdict": "PASS"})
    a.run_once("H1", confirm_verdict={"verdict": "PASS"})
    assert a.state["hypotheses"]["H1"]["state"] == "PASS"
    a.run_once("H1")
    a.run_once("H1", paper_days=15)
    assert a.run_once("H1", paper_expectancy_bps=4.0,
                      confirm_verdict={"verdict": "PASS"}) == "GATE_READY"


def test_synthetic_never_gate_ready(tmp_path):
    a = Autopilot(tmp_path)
    a.run_once("HS", dev=None)
    syn = {**DEV_GOOD, "provenance": "SYNTHETIC"}
    a.run_once("HS", dev=syn)
    a.run_once("HS", confirm_verdict={"verdict": "PASS"})
    a.run_once("HS", confirm_verdict={"verdict": "PASS"})
    a.run_once("HS")
    a.run_once("HS", paper_days=20)
    a.run_once("HS", paper_expectancy_bps=4.0)
    assert a.state["hypotheses"]["HS"]["state"] == "PAPER_COMPARE"
    assert a.state["hypotheses"]["HS"]["gate_blocked"] == \
        "synthetic provenance"


def test_illegal_transition_rejected(tmp_path):
    a = Autopilot(tmp_path)
    a.register("HX")
    with pytest.raises(ValueError):
        a._transition("HX", "GATE_READY", "cheat")
