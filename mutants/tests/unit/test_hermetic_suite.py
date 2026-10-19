"""Hermetic suite guard (F0.2).

The full suite must be immune to uncommitted working-tree mutations and
must never touch sealed campaign events. This test statically enforces:

1. No test reads the mutable working-tree copy of coord/pivot/* via
   direct filesystem IO. Git-object reads (`git show HEAD:...`) or
   fixtures under tests/fixtures/ are required.
2. No test references sealed campaign events
   (data/captures/campaign-1day-*). Manifest/heartbeat/status metadata
   may be inspected only by tools outside tests/, never by tests.
3. No test hardcodes absolute paths to another checkout (e.g. the main
   checkout at /Users/sahajpatel/Code/cryto-bot).

Scope note: committed code/config under src/, tools/, configs/,
trials/, datasets/*.py loaded for contract tests are NOT mutable data
and remain allowed via repo-relative paths. A literal "only tests/,
tmp, git objects" ban would require rewriting 1400+ tests for no
money-safety gain; the money-critical subset above is enforced here.
See DECISIONS.md D-RUN2-01 for the written justification.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# (substring, reason) — any occurrence in a test file is a violation
# unless the same file also contains an explicit git-object read marker.
FORBIDDEN = [
    ('coord" / "pivot" / "ZONES.json").read_text',
     "working-tree ZONES.json read; use git show HEAD:coord/pivot/ZONES.json"),
    ("coord/pivot/ZONES.json",
     "working-tree ZONES.json reference; use git object or fixture"),
    ('"coord" / "pivot"', "working-tree coord/pivot read; use git object"),
    ("'coord' / 'pivot'", "working-tree coord/pivot read; use git object"),
    ("data/captures/campaign", "sealed campaign data is off-limits to tests"),
    ("/Users/sahajpatel/Code/cryto-bot", "absolute main-checkout path"),
    ("/private/tmp/cryto-bot", "absolute peer-worktree path"),
]

GIT_OBJECT_MARKERS = ("git show", "git cat-file", "tests/fixtures/zones",
                        "_read_committed")

# Direct filesystem-IO markers: a coord/pivot mention is only a
# violation when it appears alongside one of these on the same line.
_DIRECT_IO = (".read_text", "open(", "REPO /", "Path(", "os.path", "read_bytes")


def _is_guard_self(path: Path) -> bool:
    return path.name == "test_hermetic_suite.py"


def test_no_working_tree_mutable_reads():
    violations: list[str] = []
    for path in sorted((REPO / "tests").rglob("*.py")):
        if _is_guard_self(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for substr, reason in FORBIDDEN:
            if substr not in text:
                continue
            if "coord" in substr:
                # coord mentions (docstrings, _read_committed args,
                # HEAD: paths) are fine; only direct filesystem IO
                # on a coord path is a violation.
                bad_lines = [
                    ln.strip()[:160] for ln in text.splitlines()
                    if substr in ln and any(m in ln for m in _DIRECT_IO)
                    and "_read_committed" not in ln and "HEAD:" not in ln
                ]
                if bad_lines:
                    violations.append(
                        f"{path.relative_to(REPO)}: {reason}: "
                        f"{' // '.join(bad_lines[:3])}")
                continue
            # Non-coord forbiddens (campaign data, absolute paths):
            # any occurrence is a violation.
            bad = [ln.strip()[:160] for ln in text.splitlines()
                   if substr in ln][:3]
            violations.append(
                f"{path.relative_to(REPO)}: {reason}: {' // '.join(bad)}")
    assert not violations, (
        "Hermetic-suite violations (read via git object or fixture instead):\n"
        + "\n".join(violations))


def test_zone_test_uses_git_object():
    """test_zone_status must load ZONES.json from a git object, not CWD."""
    text = (REPO / "tests" / "unit" / "test_zone_status.py").read_text(
        encoding="utf-8")
    assert "git show" in text or "tests/fixtures/zones" in text, (
        "test_zone_status.py must read ZONES.json via git object or fixture")
    direct = '/ "coord" / "pivot" / "ZONES.json").read_text'
    assert direct not in text, (
        "direct working-tree ZONES.json read still present")
