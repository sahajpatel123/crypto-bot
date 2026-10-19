"""Recorded-fixture contract tests (F2.3, auto-activate on ingest).

Skips (not fails) when tests/fixtures/recorded/ is empty; validates
every installed fixture once `cryptobot fixtures ingest` lands them.
"""
from __future__ import annotations

import pytest

from cryptobot.testing.fixtures import (
    check_recorded_case, recorded_contract_cases)


def test_recorded_contracts():
    cases = recorded_contract_cases()
    if not cases:
        pytest.skip("no recorded fixtures (run: cryptobot fixtures ingest)")
    assert len(cases) == 6, [c["name"] for c in cases]
    for case in cases:
        check_recorded_case(case)
