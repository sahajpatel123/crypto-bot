from __future__ import annotations

import datetime as dt

import pytest

from cryptobot.research import c_family


def _results() -> list[c_family.DayResult]:
    start = dt.date(2027, 1, 4)
    return [c_family.DayResult((start + dt.timedelta(days=k)).isoformat(),
                              5.0 if k % 3 else -1.0,
                              3.0 if k % 3 else -3.0,
                              6.0 if k % 3 else 0.0, 1.0)
            for k in range(30)]


def test_week_block_score_rounds_are_explicit_and_reproducible():
    rows = _results()
    assert c_family.score(rows, rounds=100) == c_family.score(rows, rounds=100)


def test_week_block_score_rejects_nonpositive_rounds():
    with pytest.raises(ValueError, match="rounds must be positive"):
        c_family.score(_results(), rounds=0)
