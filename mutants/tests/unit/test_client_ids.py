"""T1.6: client IDs unique across restarts, <=36 chars, legal charset.

Defect: live engine used run_tag + per-process seq + 16-bit random, so
restarts with the same tag (e.g. "prod") collide quickly.
"""
from __future__ import annotations

import re

import venue_fixtures as venues

LEGAL = re.compile(r"^[A-Za-z0-9._\-/]+$")


def test_ids_unique_across_restarts_and_legal(tmp_path):
    seen = set()
    for run in range(5):
        engine, _ = venues.make_engine(tmp_path / f"r{run}", [])
        for _ in range(200):
            cid = engine._new_client_id()  # noqa: SLF001
            assert len(cid) <= 36, cid
            assert LEGAL.match(cid), cid
            assert cid not in seen, cid
            seen.add(cid)
    assert len(seen) == 1000


def test_ids_share_run_prefix_within_run(tmp_path):
    engine, _ = venues.make_engine(tmp_path, [])
    a = engine._new_client_id()  # noqa: SLF001
    b = engine._new_client_id()  # noqa: SLF001
    assert a.rsplit("-", 1)[0] == b.rsplit("-", 1)[0]  # same run prefix
    assert a != b
