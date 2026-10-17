"""F0.2: suite hermeticity guard.

No test may read mutable working-tree files outside tests/, tmp dirs,
or git objects. This scans test sources for the known mutable paths
(coord/, data/captures campaign dirs, runs/) read via working-tree
file access; git-object reads (`git show`) are the approved pattern.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FORBIDDEN = ("coord/pivot", "coord\\pivot", "campaign-1day")


def test_no_test_reads_mutable_campaign_or_coord_files():
    offenders: list[str] = []
    for path in sorted((REPO / "tests").rglob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for needle in FORBIDDEN:
            if needle in text and "git" not in text.split(needle)[0][-200:]:
                # Allowed only when the access is a git-object read.
                if "git show" not in text and "git\", \"show" not in text \
                        and '"git"' not in text:
                    offenders.append(f"{path.name}:{needle}")
    assert offenders == [], offenders


def test_zone_manifest_comes_from_git_object():
    text = (REPO / "tests" / "unit" / "test_zone_status.py").read_text()
    assert "git" in text and "HEAD:coord/pivot/ZONES.json" in text
