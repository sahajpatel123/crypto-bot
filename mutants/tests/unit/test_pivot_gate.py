"""pivot_gate unit tests (manager-owned, self-contained).

Covers: all-zero economics -> NONE/DATA BLOCKED (reproduces X1 shape),
qualifying synthetic -> QUALIFIED winner, missing adverse cell ->
REJECTED with reason, zero-intent mechanism labelled UNTESTED.
No src/ imports: loads tools/pivot_gate.py by path.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "pivot_gate", REPO / "tools" / "pivot_gate.py")
assert SPEC and SPEC.loader
pivot_gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pivot_gate)

MANIFEST = {"families": [], "configs": []}


def _doc(cells):
    return {"cells": cells}


def _cell(cfg, split, net=0.0, closed=0, fills=0, intents=0):
    return {"config_id": cfg, "split": split, "ledger_net": net,
            "closed_positions": closed, "n_fills": fills,
            "intents_admitted": intents}


def test_all_zero_is_none_data_blocked():
    realistic = _doc([_cell("P1-R1", "dev"), _cell("P1-R1", "validation")])
    adverse = _doc([_cell("P1-R1", "dev"), _cell("P1-R1", "validation")])
    res = pivot_gate.evaluate(
        pivot_gate._cells_by_config(realistic, "r"),
        pivot_gate._cells_by_config(adverse, "a"), MANIFEST, {})
    assert res["winner"] is None
    assert res["verdict"].startswith("NONE")
    cfg = res["configs"]["P1-R1"]
    assert cfg["status"] == "DATA BLOCKED"
    assert cfg["mechanism"].startswith("UNTESTED")
    assert any("UNKNOWN" in r for r in cfg["reasons"])


def test_qualifying_synthetic_picks_winner():
    realistic = _doc([
        _cell("P1-R1", "dev", 5.0, 120, 240, 300),
        _cell("P1-R1", "validation", 7.0, 150, 300, 320),
        _cell("P2-R1", "dev", 4.0, 110, 220, 250),
        _cell("P2-R1", "validation", 3.0, 120, 240, 260),
    ])
    adverse = _doc([
        _cell("P1-R1", "dev", 2.0, 120, 240, 300),
        _cell("P1-R1", "validation", 1.5, 150, 300, 320),
        _cell("P2-R1", "dev", 1.0, 110, 220, 250),
        _cell("P2-R1", "validation", 0.5, 120, 240, 260),
    ])
    cov = {"P1-R1|validation": {"days": 12.0},
           "P2-R1|validation": {"days": 11.0}}
    res = pivot_gate.evaluate(
        pivot_gate._cells_by_config(realistic, "r"),
        pivot_gate._cells_by_config(adverse, "a"), MANIFEST, cov)
    assert res["winner"] == "P1-R1"
    assert res["verdict"].startswith("QUALIFIED")
    assert res["configs"]["P1-R1"]["mechanism"] == "SCORED"


def test_missing_adverse_cell_rejected_with_reason():
    realistic = _doc([_cell("P3-R1", "dev", 5.0, 120, 240, 300),
                      _cell("P3-R1", "validation", 6.0, 130, 260, 280)])
    adverse = _doc([_cell("P3-R1", "dev", 2.0, 120, 240, 300)])
    cov = {"P3-R1|validation": {"days": 12.0}}
    res = pivot_gate.evaluate(
        pivot_gate._cells_by_config(realistic, "r"),
        pivot_gate._cells_by_config(adverse, "a"), MANIFEST, cov)
    cfg = res["configs"]["P3-R1"]
    assert cfg["status"] == "REJECTED"
    assert any("adverse" in r for r in cfg["reasons"])
    assert res["winner"] is None


def test_zero_fill_mechanism_labelled_blocked():
    realistic = _doc([_cell("P1-R1", "dev", 0.0, 0, 0, 391),
                      _cell("P1-R1", "validation", 0.0, 0, 0, 6199)])
    adverse = _doc([_cell("P1-R1", "dev", 0.0, 0, 0, 391),
                    _cell("P1-R1", "validation", 0.0, 0, 0, 6199)])
    res = pivot_gate.evaluate(
        pivot_gate._cells_by_config(realistic, "r"),
        pivot_gate._cells_by_config(adverse, "a"), MANIFEST, {})
    cfg = res["configs"]["P1-R1"]
    assert cfg["mechanism"].startswith("BLOCKED")
    assert any("zero fills" in r for r in cfg["reasons"])


PIVOT_MANIFEST = {
    "families": [
        {"family": "P1", "role": "candidate", "min_target_bps": 15.0},
        {"family": "P2", "role": "candidate", "min_target_bps": 40.0},
        {"family": "CASH", "role": "control"},
    ],
    "configs": [],
}


def _strong(cfg):
    realistic = _doc([_cell(cfg, "dev", 99.0, 200, 400, 400),
                      _cell(cfg, "validation", 99.0, 200, 400, 400)])
    adverse = _doc([_cell(cfg, "dev", 50.0, 200, 400, 400),
                    _cell(cfg, "validation", 50.0, 200, 400, 400)])
    return (pivot_gate._cells_by_config(realistic, "r"),
            pivot_gate._cells_by_config(adverse, "a"))


def test_cash_control_never_advances():
    realistic, adverse = _strong("X1-R1-CASH")
    res = pivot_gate.evaluate(realistic, adverse, PIVOT_MANIFEST,
                              {"X1-R1-CASH|validation": {"days": 12.0}})
    assert res["winner"] is None
    assert not res["verdict"].startswith("QUALIFIED")
    cfg = res["configs"]["X1-R1-CASH"]
    assert cfg["status"] == "REJECTED"
    assert any("never advances" in r for r in cfg["reasons"])


def test_unenrolled_config_cannot_qualify():
    realistic, adverse = _strong("X1-R1")
    res = pivot_gate.evaluate(realistic, adverse, PIVOT_MANIFEST,
                              {"X1-R1|validation": {"days": 12.0}})
    assert res["winner"] is None
    cfg = res["configs"]["X1-R1"]
    assert cfg["status"] == "REJECTED"
    assert any("not enrolled" in r for r in cfg["reasons"])


def test_enrolled_candidate_still_qualifies():
    realistic, adverse = _strong("P1-R1")
    res = pivot_gate.evaluate(realistic, adverse, PIVOT_MANIFEST,
                              {"P1-R1|validation": {"days": 12.0}})
    assert res["winner"] == "P1-R1"
    assert res["configs"]["P1-R1"]["status"] == "QUALIFIED"


def test_x1_shape_reproduces_none(tmp_path):
    # Mirrors outputs/x1/economics_*.json: 0 intents/0 fills/0 net.
    cells = []
    for cfg in ("X1-R1", "X1-R1-T"):
        for split in ("dev", "validation"):
            cells.append(_cell(cfg, split))
    realistic = _doc(cells)
    r_path = tmp_path / "r.json"
    a_path = tmp_path / "a.json"
    r_path.write_text(json.dumps(realistic), encoding="utf-8")
    a_path.write_text(json.dumps(realistic), encoding="utf-8")
    res = pivot_gate.evaluate(
        pivot_gate._cells_by_config(
            json.loads(r_path.read_text()), str(r_path)),
        pivot_gate._cells_by_config(
            json.loads(a_path.read_text()), str(a_path)),
        MANIFEST, {})
    assert res["verdict"].startswith("NONE")
    assert res["winner"] is None
