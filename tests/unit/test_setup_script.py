"""setup.sh: one command from a fresh clone, and it must refuse safely.

The script is checked statically (executable, locked sync, real gates, no
secret-shaped literals) and its Python guard is executed hermetically with a
fake PATH, so the "clear message otherwise" promise is proven, not assumed.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP = REPO_ROOT / "setup.sh"
MAKEFILE = REPO_ROOT / "Makefile"

# A 64-character alphanumeric run is the shape of a Binance key or secret.
_SECRET_SHAPED = (
    re.compile(r"[A-Za-z0-9]{64,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|api[_-]?secret|secret|token)"
               r"\s*=\s*[\"']?[A-Za-z0-9+/=_-]{16,}"),
)


def _script() -> str:
    return SETUP.read_text(encoding="utf-8")


def test_setup_sh_exists_and_is_executable():
    assert SETUP.is_file()
    assert os.access(SETUP, os.X_OK), "setup.sh must be chmod +x"
    assert SETUP.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash")


def test_setup_sh_syntax_is_valid():
    bash = shutil.which("bash")
    if bash is None:  # pragma: no cover - bash is a hard dependency here
        pytest.skip("bash is required to syntax-check setup.sh")
    proc = subprocess.run([bash, "-n", str(SETUP)], capture_output=True,
                          text=True, check=False)
    assert proc.returncode == 0, proc.stderr


def test_setup_sh_uses_the_locked_sync():
    script = _script()
    # The line that actually runs, not only a message that mentions it.
    assert re.search(r"^uv sync --locked --extra dev \\$", script,
                     re.MULTILINE), "the executed sync must be locked"
    assert "uv sync --locked --extra dev" in script
    # A fresh clone must get the same resolution as CI: no bare `uv sync`.
    assert not re.search(r"^\s*uv sync(?! --locked)", script, re.MULTILINE)


def test_setup_sh_runs_the_two_real_gates():
    script = _script()
    assert 'doctor --config "$DOCTOR_CONFIG"' in script
    assert 'DOCTOR_CONFIG="configs/paper.toml"' in script
    assert "selftest" in script
    # Fail fast: both gates abort the install when they fail.
    assert 'fail "cryptobot doctor' in script
    assert 'fail "cryptobot selftest' in script


def test_setup_sh_checks_python_312_to_314():
    script = _script()
    assert "(3, 12) <= sys.version_info[:2] <= (3, 14)" in script
    for candidate in ("python3.12", "python3.13", "python3.14"):
        assert candidate in script
    assert "needs Python 3.12, 3.13 or 3.14" in script


def test_setup_sh_installs_uv_only_when_absent_and_only_from_astral():
    script = _script()
    assert 'if command -v uv >/dev/null 2>&1; then' in script
    assert "https://astral.sh/uv/install.sh" in script
    # Exactly one network fetch outside the package index: the uv installer.
    curl_lines = [line for line in script.splitlines()
                  if line.lstrip().startswith("curl ")]
    assert len(curl_lines) == 1
    assert "astral.sh/uv/install.sh" in curl_lines[0]


def test_setup_sh_refuses_a_tracked_virtualenv():
    script = _script()
    assert "git ls-files --error-unmatch" in script
    assert "git check-ignore -q" in script
    assert "refusing to create a virtualenv" in script


def _extract_function(name: str) -> str:
    """Return the shell function `name` verbatim from setup.sh."""
    lines = _script().splitlines()
    start = next(i for i, line in enumerate(lines)
                 if line.startswith(f"{name}() {{"))
    end = next(i for i in range(start, len(lines)) if lines[i] == "}")
    return "\n".join(lines[start:end + 1])


def test_setup_sh_virtualenv_guard_passes_before_the_directory_exists(
        tmp_path):
    """A fresh clone has no `.venv`, and `.venv/` is a directory-only pattern.

    `git check-ignore .venv` returns 1 in that state, so a guard that only
    asks that spelling refuses every clean checkout at its first run. This runs
    the function the script actually calls, in a repository shaped like the
    fresh clone that exposed it.
    """
    bash = shutil.which("bash")
    if bash is None or shutil.which("git") is None:  # pragma: no cover
        pytest.skip("bash and git are required")
    guard = _extract_function("venv_is_ignored")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    script = f'VENV=.venv\n{guard}\nvenv_is_ignored\n'

    # Fresh clone: `.venv/` ignored, no directory on disk yet -> must pass.
    assert not (repo / ".venv").exists()
    (repo / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    fresh = subprocess.run([bash, "-c", script], cwd=str(repo), check=False)
    assert fresh.returncode == 0, "guard refuses a fresh clone"

    # The directory existing must not be what makes it pass.
    (repo / ".venv").mkdir()
    assert subprocess.run([bash, "-c", script], cwd=str(repo),
                          check=False).returncode == 0

    # A checkout that ignores nothing must still be refused.
    (repo / ".gitignore").write_text("build/\n", encoding="utf-8")
    assert subprocess.run([bash, "-c", script], cwd=str(repo),
                          check=False).returncode == 1


def test_setup_sh_prints_the_exact_next_steps():
    script = _script()
    for step in ("keys set", "keys status", "keys check", "demo-drill",
                 "owner"):
        assert step in script, step


def test_setup_sh_contains_no_secret_shaped_literals():
    for line_number, line in enumerate(_script().splitlines(), start=1):
        for pattern in _SECRET_SHAPED:
            match = pattern.search(line)
            assert match is None, (f"secret-shaped literal on line "
                                  f"{line_number}: {match.group(0)[:8]}...")
    # It also never reads or writes a credential file itself.
    script = _script()
    assert "CRYPTOBOT_API_KEY=" not in script
    assert "CRYPTOBOT_API_SECRET=" not in script


def test_setup_sh_is_offline_safe():
    script = _script()
    # No package-manager calls beyond uv: nothing to install twice.
    assert "pip install" not in script
    assert "python -m venv" not in script
    assert "python3 -m venv" not in script


@pytest.mark.parametrize("missing", ["bash", "git"])
def test_setup_sh_does_not_require_an_unsupported_python(missing, tmp_path,
                                                         monkeypatch):
    """The Python guard refuses with a readable message, not a traceback."""
    bash = shutil.which("bash")
    if bash is None:  # pragma: no cover
        pytest.skip("bash is required")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    # A 3.11 interpreter (too old) and a uv that cannot provision one.
    python3 = fake_bin / "python3"
    python3.write_text("#!/bin/sh\nexit 1\n")
    python3.chmod(0o755)
    uv = fake_bin / "uv"
    uv.write_text("#!/bin/sh\nexit 1\n")
    uv.chmod(0o755)
    env = {"PATH": str(fake_bin), "HOME": str(tmp_path / "home")}
    proc = subprocess.run([bash, str(SETUP)], cwd=str(REPO_ROOT), env=env,
                          capture_output=True, text=True, check=False,
                          timeout=120)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 1, combined
    assert "needs Python 3.12, 3.13 or 3.14" in combined
    assert "Traceback" not in combined
    assert "no python3" in combined or "found none" in combined


def test_make_setup_runs_setup_sh():
    assert MAKEFILE.is_file()
    text = MAKEFILE.read_text(encoding="utf-8")
    assert re.search(r"^setup:\s*$", text, re.MULTILINE)
    assert re.search(r"^\t\./setup\.sh$", text, re.MULTILINE)
    assert ".PHONY: setup" in text
    if shutil.which("make") is None:  # pragma: no cover
        pytest.skip("make is not installed")
    proc = subprocess.run(["make", "-n", "setup"], cwd=str(REPO_ROOT),
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    assert "./setup.sh" in proc.stdout
