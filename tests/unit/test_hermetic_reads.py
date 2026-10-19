"""F0.2: the suite may not depend on mutable working-tree data.

Background: the prior full run failed only because
``test_zone_status.test_real_zones_manifest_shape`` read the live,
uncommitted ``coord/pivot/ZONES.json``. Systematic tests are allowed to
read committed repository files (git objects), fixtures under
``tests/``, and tmp dirs. They must never read a repo file that is
modified or untracked in the current checkout.

This test resolves literal ``REPO / "a" / "b"`` expressions and direct
string paths in every test module and fails when the target is currently
dirty. It is deliberately static (no import side effects) and runs in
under a second.
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TESTS = Path(__file__).resolve().parents[1]


def _dirty_paths() -> set[str]:
    """Repo-relative paths modified or untracked right now."""
    out = subprocess.run(
        ["git", "-C", str(REPO), "status", "--porcelain", "-z"],
        check=True, capture_output=True, text=True).stdout
    paths: set[str] = set()
    entries = out.split("\0")
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if not entry:
            continue
        status, raw = entry[:2], entry[3:]
        if status.startswith("R") and i < len(entries):
            i += 1  # skip rename source; raw is the destination
        paths.add(raw)
    return paths


def _literal_repo_path(node: ast.AST) -> str | None:
    """Resolve ``REPO / "coord" / "pivot" / "ZONES.json"``-like chains."""
    if isinstance(node, ast.Name) and node.id in {"REPO", "ROOT", "TESTS"}:
        return ""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _literal_repo_path(node.left)
        right = _literal_repo_path(node.right)
        if left is not None and right is not None:
            return f"{left}/{right}".strip("/")
    if isinstance(node, ast.Call) and node.args:
        func = node.func
        if isinstance(func, ast.Name) and func.id == "Path":
            return _literal_repo_path(node.args[0])
    return None


def _test_reads() -> list[tuple[str, str]]:
    reads: list[tuple[str, str]] = []
    for path in sorted(TESTS.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                target = None
                if isinstance(node.func, ast.Name) and node.func.id == "open" \
                        and node.args:
                    target = _literal_repo_path(node.args[0])
                elif isinstance(node.func, ast.Attribute) \
                        and node.func.attr in {"read_text", "read_bytes"}:
                    target = _literal_repo_path(node.func.value)
                if target and not target.startswith(
                        ("tests/", "/", "src/", "tools/")):
                    reads.append((str(path.relative_to(REPO)), target))
    return reads


def test_no_test_reads_a_mutable_repo_file():
    dirty = _dirty_paths()
    offenders = [(src, target) for src, target in _test_reads()
                 if target in dirty]
    assert not offenders, (
        "tests read mutable uncommitted repo files (use a fixture or a "
        f"git object): {offenders}")


def test_zone_status_uses_a_git_object():
    source = (TESTS / "unit" / "test_zone_status.py").read_text(
        encoding="utf-8")
    assert 'f"HEAD:{relative}"' in source
    assert '"coord" / "pivot" / "ZONES.json").read_text' not in source
