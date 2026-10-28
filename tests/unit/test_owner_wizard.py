"""Owner wizard: 11 human steps incl recorder-start + disk (Iris G3)."""
from __future__ import annotations

import argparse
import json

from cryptobot.cli_extra import cmd_owner


def _run(tmp_path, step=None):
    return cmd_owner(argparse.Namespace(
        state=str(tmp_path / "owner.json"), step=step))


def test_wizard_lists_eleven_steps_in_owner_actions_order(tmp_path, capsys):
    assert _run(tmp_path) == 0
    out = capsys.readouterr().out
    assert "owner: 0 passed, 11 failed" in out
    order = ["host-check", "recorder-start", "demo-keys", "readiness",
             "demo-drill", "latency-probe", "fixtures", "calibrate",
             "disk", "legal", "tax"]
    positions = [out.index(f"[TODO] {name}:") for name in order]
    assert positions == sorted(positions)


def test_each_step_flips_and_counts(tmp_path, capsys):
    for name in ("recorder-start", "disk"):
        assert _run(tmp_path, step=name) == 0
    out = capsys.readouterr().out
    assert "owner: 2 passed, 9 failed" in out
    assert "[PASS] recorder-start:" in out
    assert "[PASS] disk:" in out
    state = json.loads((tmp_path / "owner.json").read_text())
    assert state["done"] == ["disk", "recorder-start"]


def test_blocked_owner_tracks_human_steps(tmp_path, capsys):
    _run(tmp_path)
    out = capsys.readouterr().out
    assert "blocked-owner: demo-drill, legal, tax" not in out
    assert "blocked-owner:" in out
    assert "recorder-start" in out.split("blocked-owner:")[1]


def test_invalid_step_refused_and_corrupt_state_recovers(tmp_path, capsys):
    assert _run(tmp_path, step="bogus") == 2
    assert "REFUSED unknown step" in capsys.readouterr().out
    (tmp_path / "owner.json").write_text("{corrupt")
    assert _run(tmp_path) == 0  # recovers, exit 0
