"""Evidence-gate exit-status tests (manager-owned; F-CEO-05).

The gate must exit nonzero when a required check fails, while keeping
diagnostics. Optional checks never fail the gate.
"""
import contextlib
import importlib.util
import io
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"


def _load_gate():
    spec = importlib.util.spec_from_file_location(
        "generate_evidence_gate", TOOLS / "generate_evidence.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def gate(monkeypatch):
    module = _load_gate()
    monkeypatch.setattr(sys, "argv", ["generate_evidence.py"])
    return module


def _run_main(gate):
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        code = gate.main()
    return code, captured.getvalue()


def test_required_failure_fails_gate_with_diagnostics(gate, monkeypatch):
    monkeypatch.setattr(gate, "run", lambda cmd, cwd: (1, "INJECTED CHECK FAILURE"))
    code, out = _run_main(gate)
    assert code != 0
    assert "INJECTED CHECK FAILURE" in out


def test_required_pytest_failure_fails_gate(gate, monkeypatch):
    def fake_run(cmd, cwd):
        if "pytest" in cmd:
            return (1, "1 failed, 166 passed")
        return (0, "ok")
    monkeypatch.setattr(gate, "run", fake_run)
    code, out = _run_main(gate)
    assert code != 0
    assert "1 failed, 166 passed" in out


def test_all_required_pass_exits_zero(gate, monkeypatch):
    monkeypatch.setattr(gate, "run", lambda cmd, cwd: (0, "ok-line"))
    code, _ = _run_main(gate)
    assert code == 0
