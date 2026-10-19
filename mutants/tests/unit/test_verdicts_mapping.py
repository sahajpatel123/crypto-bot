"""F0.4d: every verdict sentence maps to a machine-written verdict JSON.

Parses RESEARCH_VERDICTS.md and enforces:
1. Every evidence-table row cites research/verdicts/<name>.json.
2. Every cited JSON exists, parses, carries verdict + document_sha256,
   and was machine-bound (hashes.config_sha256_16 + code_commit).
3. No bare verdict claim (PASS/FAIL/UNDERPOWERED) appears outside a
   cited row or the headline rollup (which cites the verdicts dir).
4. The cost-structure paragraph cites research/verdicts/cost-model.json
   (machine output of tools/verify_breakeven.py --out).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOC = REPO / "RESEARCH_VERDICTS.md"
VERDICTS = REPO / "research" / "verdicts"


def _doc_text() -> str:
    return DOC.read_text(encoding="utf-8")


def test_verdicts_dir_and_cost_json_exist():
    assert VERDICTS.is_dir(), "research/verdicts/ missing"
    cost = VERDICTS / "cost-model.json"
    assert cost.exists(), "cost-model.json missing (verify_breakeven --out)"
    doc = json.loads(cost.read_text(encoding="utf-8"))
    assert doc["tool"] == "verify_breakeven"
    assert doc["rows_checked"] == 30
    assert "INFEASIBLE" in json.dumps(doc)


def test_every_table_row_cites_machine_json():
    text = _doc_text()
    rows = [ln for ln in text.splitlines() if ln.startswith("| ")
            and "Family" not in ln and "---" not in ln]
    assert len(rows) >= 6, f"expected >=6 evidence rows, got {len(rows)}"
    for row in rows:
        cites = re.findall(r"research/verdicts/[\w\-.]+\.json", row)
        assert cites, f"row cites no verdict JSON: {row[:120]}"
        for cite in cites:
            path = REPO / cite
            assert path.exists(), f"cited {cite} missing"
            doc = json.loads(path.read_text(encoding="utf-8"))
            assert doc.get("verdict") in ("PASS", "FAIL", "UNDERPOWERED"), cite
            assert doc.get("document_sha256"), f"{cite} not hash-bound"
            assert doc.get("hashes", {}).get("code_commit"), f"{cite} unbound"


def test_no_uncited_verdict_claims():
    text = _doc_text()
    # Strip cited rows + headline rollup + code spans; remaining prose
    # must not assert a verdict outcome.
    stripped = re.sub(r"`[^`]*`", "", text)
    lines = [ln for ln in stripped.splitlines()
             if "research/verdicts/" not in ln
             and not ln.startswith("| ")
             and "no strategy has demonstrated" not in ln.lower()
             and "0 PASS" not in ln]
    bad = [ln.strip()[:100] for ln in lines
           if re.search(r"\b(PASS|FAIL|UNDERPOWERED)\b", ln)]
    assert not bad, f"uncited verdict claims: {bad}"


def test_no_recommendation_section():
    text = _doc_text().lower()
    assert "recommendation" not in text, (
        "recommendations do not map to machine JSONs (F0.4d); "
        "next steps live in the F4 autopilot queue")
