"""Z5: each final state, synthetic refusal, and launchd unload."""
from datetime import UTC, datetime, timedelta

from cryptobot.research.adjudicate import project_decision, run_adjudication

NOW = datetime(2026, 10, 19, tzinfo=UTC)
T0 = NOW - timedelta(days=91)


def _rows(*states, provenance="OBSERVED"):
    return [{"hypothesis": f"H{i}", "state": s, "provenance": provenance}
            for i, s in enumerate(states, start=1)]


def test_archive_negative_unloads_every_launchd_job(tmp_path):
    plist = tmp_path / "agents"
    plist.mkdir()
    (plist / "com.cryptobot.recorder.plist").write_text("a")
    (plist / "com.cryptobot.refresh.plist").write_text("b")
    (plist / "other.plist").write_text("no")
    calls = []
    out = run_adjudication(
        rows=_rows("KILLED", "NOT_ESTABLISHED", "FAIL", "IMPRACTICAL"),
        now=NOW, t0=T0, gate_is_go=False,
        chain_path=tmp_path / "chain.json", plist_dir=plist,
        verdict_path=tmp_path / "FINAL_VERDICT.md",
        runner=lambda cmd: calls.append(cmd), notify=True)
    assert out["decision"] == "ARCHIVE_NEGATIVE"
    booted = [c for c in calls if c[:2] == ["launchctl", "bootout"]]
    assert len(booted) == 2
    assert (tmp_path / "FINAL_VERDICT.md").exists()
    again = run_adjudication(
        rows=_rows("KILLED", "NOT_ESTABLISHED", "FAIL", "IMPRACTICAL"),
        now=NOW, t0=T0, gate_is_go=False,
        chain_path=tmp_path / "chain.json", plist_dir=plist,
        verdict_path=tmp_path / "FINAL_VERDICT.md",
        runner=lambda cmd: calls.append(cmd))
    assert again["idempotent"] is True
    assert len([c for c in calls if c[:2] == ["launchctl", "bootout"]]) == 2


def test_paper_only_and_ready_for_human(tmp_path):
    paper = project_decision(
        _rows("KILLED", "PASS"), now=NOW, t0=T0, gate_is_go=False)
    assert paper[0] == "PAPER_ONLY"
    ready = project_decision(
        _rows("KILLED", "PASS"), now=NOW, t0=T0, gate_is_go=True)
    assert ready[0] == "READY_FOR_HUMAN_DECISION"


def test_synthetic_cannot_produce_a_real_final_state(tmp_path):
    calls = []
    out = run_adjudication(
        rows=_rows("KILLED", "FAIL", provenance="SYNTHETIC"),
        now=NOW, t0=T0, gate_is_go=True,
        chain_path=tmp_path / "chain.json", plist_dir=tmp_path,
        verdict_path=tmp_path / "FINAL_VERDICT.md",
        runner=lambda cmd: calls.append(cmd))
    assert out["decision"] == "REFUSED_SYNTHETIC"
    assert out["decision"] not in {
        "ARCHIVE_NEGATIVE", "PAPER_ONLY", "READY_FOR_HUMAN_DECISION"}
    assert calls == []
    assert not (tmp_path / "FINAL_VERDICT.md").exists()


def test_await_data_is_force_closed_at_the_deadline():
    decision, closed = project_decision(
        _rows("AWAIT_DATA", "KILLED"), now=NOW, t0=T0, gate_is_go=False)
    assert decision == "ARCHIVE_NEGATIVE"
    assert closed[0]["state"] == "NOT_ESTABLISHED"
    assert closed[0]["forced"] is True


def test_family_c_pass_enters_forward_paper(tmp_path):
    from cryptobot.research.autopilot import Autopilot
    root = tmp_path / "c"
    prereg = tmp_path / "C1.md"
    prereg.write_text("# C1\n")
    bot = Autopilot(root, family="C")
    bot.register("C1", prereg=str(prereg), config_sha256="abc",
                 commit="c", family_size=1)
    assert bot.run_once()["hypotheses"]["C1"]["state"] == "AWAIT_FORWARD"
    fwd = root / "forward"
    fwd.mkdir()
    (fwd / "C1.json").write_text(
        '{"decision":"PASS","n_days":90,"provenance":"OBSERVED",'
        '"beats_zero":true,"beats_benchmark_apr":false}')
    assert bot.run_once()["hypotheses"]["C1"]["state"] == "PASS"
    (fwd / "C1.json").write_text(
        '{"decision":"PASS","n_days":90,"provenance":"OBSERVED",'
        '"paper_started_utc":"2026-10-19T00:00:00+00:00"}')
    # PASS reads forward/<H>.json for the paper clock. The artifact
    # path is root/forward, and _artifact("forward") is that file.
    # paper_started_utc is read from a separate forward artifact only
    # after PASS, so write it under the same file before the next run.
    state = bot.read_state("C1")
    assert state["state"] == "PASS"
    paper = root / "forward" / "C1.json"
    paper.write_text(
        '{"paper_started_utc":"2026-10-19T00:00:00+00:00",'
        '"provenance":"OBSERVED"}')
    assert bot.run_once()["hypotheses"]["C1"]["state"] == "FORWARD_PAPER"
