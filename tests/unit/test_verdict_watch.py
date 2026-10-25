"""Verdict watch: records transitions, never synthesises a verdict."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cryptobot.ops import verdict_watch
from cryptobot.ops.verdict_watch import (
    DECIDED,
    ERROR,
    EXIT_CANNOT_RUN,
    EXIT_CHANGED,
    EXIT_OK,
    WAITING,
    StudyResult,
    run_watch,
)


def _study(name: str, status: str, verdict: str | None = None,
           reason: str = "still accruing") -> object:
    return lambda: StudyResult(name, status, verdict, reason,
                               {"code": "a" * 64}, {"detail": 1})


def _records(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.json"))


def test_first_run_records_and_exits_zero(tmp_path: Path) -> None:
    out = tmp_path / "verdicts"
    doc, code, written = run_watch(
        out_dir=out, repo_root=tmp_path,
        studies=[_study("B4b", WAITING)],
        names=["B4b"])
    assert code == EXIT_OK
    assert written is not None and written.is_file()
    assert doc["format"] == "cryptobot-verdict-watch/1"
    assert doc["gate"] == "NO-GO"
    assert doc["changed"] == [] and doc["previous"] is None
    stored = json.loads(written.read_text(encoding="utf-8"))
    row = stored["studies"]["B4b"]
    assert row["status"] == WAITING
    assert row["verdict"] is None
    assert row["reason"] == "still accruing"
    assert row["code_sha256"] == {"code": "a" * 64}
    assert stored["commit"]


def test_a_decided_verdict_is_a_transition_and_exits_ten(
        tmp_path: Path) -> None:
    out = tmp_path / "verdicts"
    first, code, written = run_watch(
        out_dir=out, repo_root=tmp_path,
        studies=[_study("B4b", WAITING)], names=["B4b"])
    assert code == EXIT_OK and written is not None

    second, code, later = run_watch(
        out_dir=out, repo_root=tmp_path,
        studies=[_study("B4b", DECIDED, "KILL")], names=["B4b"])
    assert code == EXIT_CHANGED
    assert second["changed"] == ["B4b"]
    assert second["previous"] == str(written)
    assert later is not None and later != written
    row = json.loads(later.read_text(encoding="utf-8"))["studies"]["B4b"]
    assert row["status"] == DECIDED
    # The verdict is the tool's own string, copied verbatim.
    assert row["verdict"] == "KILL"


def test_an_unchanged_rerun_writes_no_second_record(tmp_path: Path) -> None:
    out = tmp_path / "verdicts"
    _, code, written = run_watch(
        out_dir=out, repo_root=tmp_path,
        studies=[_study("D1", WAITING)], names=["D1"])
    assert code == EXIT_OK and written is not None
    before = written.read_bytes()
    doc, code, again = run_watch(
        out_dir=out, repo_root=tmp_path,
        studies=[_study("D1", WAITING)], names=["D1"])
    assert code == EXIT_OK
    assert again is None
    assert doc["changed"] == []
    assert _records(out) == [written]
    assert written.read_bytes() == before


def test_a_missing_tool_output_exits_three(tmp_path: Path) -> None:
    out = tmp_path / "verdicts"

    def broken() -> StudyResult:
        raise RuntimeError("tool printed nothing recognisable")

    doc, code, written = run_watch(
        out_dir=out, repo_root=tmp_path, studies=[broken], names=["B4b"])
    assert code == EXIT_CANNOT_RUN
    assert doc["studies"]["B4b"]["status"] == ERROR
    assert doc["studies"]["B4b"]["verdict"] is None
    assert "tool printed nothing recognisable" in \
        doc["studies"]["B4b"]["reason"]
    assert written is not None and written.is_file()


def test_an_error_is_never_read_as_a_verdict_transition(
        tmp_path: Path) -> None:
    out = tmp_path / "verdicts"
    run_watch(out_dir=out, repo_root=tmp_path,
              studies=[_study("B4b", WAITING)], names=["B4b"])

    def broken() -> StudyResult:
        raise OSError("no recorder root")

    doc, code, written = run_watch(
        out_dir=out, repo_root=tmp_path, studies=[broken], names=["B4b"])
    assert code == EXIT_CANNOT_RUN
    assert doc["changed"] == []  # ERROR is not a deliverable verdict
    assert written is not None
    # ... and recovering to WAITING is not a transition either.
    doc, code, _ = run_watch(out_dir=out, repo_root=tmp_path,
                             studies=[_study("B4b", WAITING)],
                             names=["B4b"])
    assert code == EXIT_OK
    assert doc["changed"] == []


def test_two_studies_are_reported_independently(tmp_path: Path) -> None:
    out = tmp_path / "verdicts"
    doc, code, _ = run_watch(
        out_dir=out, repo_root=tmp_path,
        studies=[lambda: StudyResult("B4b", WAITING, None, "waiting"),
                 lambda: StudyResult("D1", DECIDED, "KILL", "cell killed")],
        names=["B4b", "D1"])
    assert code == EXIT_OK
    assert doc["studies"]["B4b"]["status"] == WAITING
    assert doc["studies"]["D1"]["status"] == DECIDED
    assert doc["studies"]["D1"]["verdict"] == "KILL"


def test_unrecognised_b4b_output_is_refused(tmp_path: Path,
                                            monkeypatch) -> None:
    class FakeModule:
        @staticmethod
        def forward_command(_root: Path) -> dict:
            return {"state": "MAYBE"}

    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "forward_b4b.py").write_text("# stub\n")
    monkeypatch.setattr(verdict_watch, "_load_b4b",
                        lambda _repo: FakeModule())
    with pytest.raises(ValueError, match="unrecognised state"):
        verdict_watch.b4b_study(root=tmp_path, repo_root=tmp_path)


def test_default_studies_on_an_empty_tree_cannot_run(tmp_path: Path) -> None:
    out = tmp_path / "verdicts"
    doc, code, written = run_watch(out_dir=out, repo_root=tmp_path)
    assert code == EXIT_CANNOT_RUN
    assert set(doc["studies"]) == {"B4b", "D1"}
    assert all(row["status"] == ERROR for row in doc["studies"].values())
    assert all(row["verdict"] is None for row in doc["studies"].values())
    assert written is not None
