"""Import lint: no module outside the vault may touch CONFIRM loading.

Only these locations may reference vault CONFIRM loading::

    src/cryptobot/vault/*            the sealed vault itself (owner: F3.5 agent)
    src/cryptobot/research/verdict.py  the sole CONFIRM consumer (owner wires
                                       the one-shot token call; allowlisted
                                       ahead of that wiring)
    tests/**                         tests, including this file

Scope: ``*.py`` modules only. The property being guarded is executable
access ("no other module can read CONFIRM data"); prose docs such as
``data/vault/README.md`` are non-executable by construction and out of
scope. ``.venv``/caches are excluded as third-party/ephemeral.

Matching is whole-word (``\\bload_chunk\\b``, ``\\bCONFIRM\\b``) so that
unrelated identifiers do not trip the gate. Two pre-existing near-misses
were examined on 2026-10-18 and are benign substring matches, left
untouched per the no-edit rule:

* ``src/cryptobot/market_data/latency.py`` — ``STOP_CONFIRM`` latency stage
  (stop-order acknowledgement timing; no vault relation).
* ``src/cryptobot/app/session.py`` — the English word "CONFIRMED" in a
  comment about terminal order states.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

LOAD_CHUNK_RE = re.compile(r"\bload_chunk\b")
CONFIRM_RE = re.compile(r"\bCONFIRM\b")

# Regex self-check samples: must NOT match (benign substrings).
BENIGN_SAMPLES = ["STOP_CONFIRM", "CONFIRMED", "confirmation", "load_chunks"]

ALLOWED_PREFIXES = (
    "src/cryptobot/vault/",
    "tests/",
)
ALLOWED_FILES = {
    "src/cryptobot/research/verdict.py",
}

SKIP_DIR_PARTS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "node_modules",
    ".hypothesis",
}


def _is_allowed(rel_posix: str) -> bool:
    if rel_posix in ALLOWED_FILES:
        return True
    return rel_posix.startswith(ALLOWED_PREFIXES)


def _iter_repo_py_files() -> list[Path]:
    found = []
    for path in REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT)
        if any(part in SKIP_DIR_PARTS for part in rel.parts):
            continue
        found.append(path)
    return sorted(found)


def test_word_boundary_rescues_benign_substrings() -> None:
    for sample in BENIGN_SAMPLES:
        assert not LOAD_CHUNK_RE.search(sample), sample
        assert not CONFIRM_RE.search(sample), sample
    assert LOAD_CHUNK_RE.search("load_chunk(root, cid)")
    assert CONFIRM_RE.search('cls == "CONFIRM"')


def test_no_unauthorized_confirm_loading_references() -> None:
    offenders: dict[str, list[str]] = {}
    scanned = 0
    for path in _iter_repo_py_files():
        scanned += 1
        rel = path.relative_to(REPO_ROOT).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        hits = []
        if LOAD_CHUNK_RE.search(text):
            hits.append("load_chunk")
        if CONFIRM_RE.search(text):
            hits.append("CONFIRM")
        if hits and not _is_allowed(rel):
            offenders[rel] = hits
    assert scanned > 0, "lint scanned zero files; repo root resolution broken?"
    assert not offenders, (
        "unauthorized vault CONFIRM-loading references "
        f"(allowlist: {sorted(ALLOWED_FILES | set(ALLOWED_PREFIXES))}): {offenders}"
    )


def test_allowlist_covers_known_vault_surface() -> None:
    # Guard against silent allowlist drift: these files must exist and be allowed.
    assert (REPO_ROOT / "src/cryptobot/vault/loader.py").is_file()
    assert (REPO_ROOT / "src/cryptobot/research/verdict.py").is_file()
    assert _is_allowed("src/cryptobot/vault/loader.py")
    assert _is_allowed("src/cryptobot/research/verdict.py")
    assert _is_allowed("tests/unit/test_vault_access.py")
    assert not _is_allowed("src/cryptobot/research/runner.py")
