"""The macOS installer must install agents whose commands still exist.

`cryptobot verdict-watch --once` and `cryptobot pnl daily` only run daily if
``deploy/macos/install.sh`` installs agents for them, and an agent whose command
was renamed -- or whose flag was dropped -- fails silently at 04:00 instead of
in CI. This module parses the installer (no line numbers, no hand-kept command
list) and parses every installed CLI command through the real argparse tree.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from cryptobot.cli import build_parser

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SH = REPO_ROOT / "deploy" / "macos" / "install.sh"

#: The daily operator jobs v1.1.1 promises; the recorder is deliberately not here.
DAILY_AGENTS = ("com.cryptobot.verdict-watch", "com.cryptobot.pnl")

_AGENT_BLOCK = re.compile(
    r'install_one\s+(?P<label>[\w.-]+)\s+"\$\(cat\s*<<EOF\n(?P<body>.*?)\nEOF\n\)"',
    re.DOTALL)
_PROGRAM_ARGS = re.compile(
    r"<key>ProgramArguments</key>\s*<array>(?P<items>.*?)</array>", re.DOTALL)
_STRING = re.compile(r"<string>(?P<value>.*?)</string>", re.DOTALL)
_HOUR = re.compile(r"<key>Hour</key>\s*<integer>\d+</integer>")
_MINUTE = re.compile(r"<key>Minute</key>\s*<integer>\d+</integer>")


def _agents() -> dict[str, str]:
    """label -> plist body, for every agent the installer writes."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    agents = {m.group("label"): m.group("body") for m in _AGENT_BLOCK.finditer(text)}
    assert agents, f"no install_one blocks parsed from {INSTALL_SH}"
    return agents


def _program_arguments(body: str) -> list[str]:
    array = _PROGRAM_ARGS.search(body)
    assert array, "agent has no ProgramArguments array"
    return [value.strip() for value in _STRING.findall(array.group("items"))]


def _cli_argv(body: str) -> list[str]:
    """The arguments after ``-m cryptobot.cli`` (wrappers such as nice are skipped)."""
    argv = _program_arguments(body)
    assert "cryptobot.cli" in argv, f"not a cryptobot.cli agent: {argv}"
    return argv[argv.index("cryptobot.cli") + 1:]


def _script_path(argv: list[str]) -> str | None:
    """The repository-relative script an agent runs directly, if it runs one."""
    for argument in argv:
        if not argument.endswith(".py"):
            continue
        return argument.split("$ROOT/", 1)[1] if "$ROOT/" in argument else argument
    return None


def test_installer_parses_and_still_owns_the_recorder():
    """A parse that silently matched nothing would make every test below vacuous."""
    agents = _agents()
    assert "com.cryptobot.recorder" in agents
    assert "<key>KeepAlive</key><true/>" in agents["com.cryptobot.recorder"]
    for label in DAILY_AGENTS:
        assert label in agents, f"{label} is not installed by deploy/macos/install.sh"


@pytest.mark.parametrize("label", DAILY_AGENTS)
def test_daily_agent_is_a_plain_calendar_job_outside_the_recorder(label):
    body = _agents()[label]
    assert f"<key>Label</key><string>{label}</string>" in body
    assert _HOUR.search(body) and _MINUTE.search(body), "want StartCalendarInterval H:M"
    assert "<key>StartCalendarInterval</key>" in body
    # No supervision, no polling loop, and nothing that could disturb the recorder.
    assert "<key>KeepAlive</key>" not in body
    assert "<key>StartInterval</key>" not in body
    assert "recorder" not in " ".join(_program_arguments(body))
    assert label != "com.cryptobot.recorder"


@pytest.mark.parametrize("label", DAILY_AGENTS)
def test_daily_agent_command_exists_in_the_cli_parser(label):
    argv = _cli_argv(_agents()[label])
    assert argv, f"{label} installs an empty command"
    args = build_parser().parse_args(argv)  # SystemExit => subcommand or flag is gone
    assert callable(args.func)
    if label == "com.cryptobot.verdict-watch":
        assert "--once" in argv  # the cron-friendly form; the command refuses otherwise
    if label == "com.cryptobot.pnl":
        assert argv[:2] == ["pnl", "daily"]


def test_every_installed_command_exists():
    """Every agent: a live cryptobot.cli command, or a script that is really in the repo."""
    for label, body in _agents().items():
        argv = _program_arguments(body)
        if "cryptobot.cli" in argv:
            args = build_parser().parse_args(_cli_argv(body))
            assert callable(args.func), label
            continue
        script = _script_path(argv)
        assert script, f"{label} installs neither a CLI command nor a script: {argv}"
        assert (REPO_ROOT / script).is_file(), f"{label} points at missing {script}"
