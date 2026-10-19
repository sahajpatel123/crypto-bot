"""READY acceptance: CORR independent probes as regression assertions.

Manager-owned. Encodes the CORRECT behavior from
Crypto_Bot_CORR_Independent_Probes.py observations; red on the base tag,
must pass on the integrated fix revision. Lifecycle legs run the real
restart tape with observers (black-box: no W1-internal API assumed).
Scoring legs use the stable score_cell/analyze_run APIs.

No network (probe denies it), synthetic only, seconds-scale.
"""
import runpy
import socket
import tempfile
from pathlib import Path

import pytest

_ORIG_CONNECT = socket.socket.connect
_ORIG_CREATE = socket.create_connection
_PROBE = runpy.run_path("Crypto_Bot_CORR_Independent_Probes.py")
# The probe patches sockets at import. Put them back so the rest of the
# suite can use loopback, and deny only while this file's tests run.
_DENY = _PROBE["deny_network"]
socket.socket.connect = _ORIG_CONNECT
socket.create_connection = _ORIG_CREATE


@pytest.fixture(autouse=True)
def _deny_network_only_for_these_tests():
    socket.socket.connect = _DENY
    socket.create_connection = _DENY
    yield
    socket.socket.connect = _ORIG_CONNECT
    socket.create_connection = _ORIG_CREATE


def _session_case(remove_later_crossings):
    with tempfile.TemporaryDirectory(prefix="ready-acc-") as d:
        return _PROBE["session_case"](
            Path(d), remove_later_crossings=remove_later_crossings)


# -- Finding: Session protection/settlement lifecycle -------------------------
def test_lifecycle_original_tape_settles_cleanly():
    obs = _session_case(remove_later_crossings=False)
    assert obs["status"] == "COMPLETE", obs["status"]
    assert obs["returncode"] == 0
    # Every fill converts its reservation; nothing filled expires orphaned.
    assert obs["expiry_transitions"] == [], obs["expiry_transitions"]
    # No live child is ever dropped from tracking.
    assert obs["forgotten_live_legs"] == [], obs["forgotten_live_legs"][:2]
    # A correct lifecycle never takes the emergency path.
    assert obs["protection_counts"].get("protection-emergency", 0) == 0, \
        obs["protection_counts"]
    assert obs["protection_counts"].get("protection-unverified", 0) == 0, \
        obs["protection_counts"]


def test_lifecycle_quiet_tape_completes_in_bracket():
    # Same entry, later prices held inside the bracket: settlement must
    # not depend on a helpful future price move.
    obs = _session_case(remove_later_crossings=True)
    assert obs["status"] == "COMPLETE", obs["status"]
    assert obs["returncode"] == 0
    assert obs["expiry_transitions"] == [], obs["expiry_transitions"]
    assert obs["forgotten_live_legs"] == [], obs["forgotten_live_legs"][:2]
    assert obs["protection_counts"].get("protection-emergency", 0) == 0, \
        obs["protection_counts"]


# -- Finding: scoring correctness ---------------------------------------------
def _scoring_cases():
    with tempfile.TemporaryDirectory(prefix="ready-acc-") as d:
        return _PROBE["scoring_cases"](Path(d))


def test_scoring_partial_close_not_a_closed_trade():
    res = _scoring_cases()["partial_close"]
    assert res["reported_closed_trades"] == 0, res
    assert res["reported_expectancy_n"] == 0, res


def test_scoring_funding_and_ist_day():
    res = _scoring_cases()["funded_ist_day"]
    assert res["reported_booked_net"] == 0.74, res
    assert res["reported_daily_net"] == {"2026-10-12": 0.74}, res
    assert res["reported_trade_net"] == 0.74, res


def test_scoring_symbol_seconds_not_clock_seconds():
    res = _scoring_cases()["two_symbols_same_second"]
    total = sum(res["reported_strategy_eligible_seconds"].values())
    assert total == 2, res
