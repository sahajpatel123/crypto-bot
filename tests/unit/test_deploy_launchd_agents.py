"""deploy/macos/install.sh must schedule the verdict watcher and the daily P&L.

v1.1.0 shipped ``cryptobot verdict-watch --once`` and ``cryptobot pnl daily`` but nothing
called them, so "delivers its verdict automatically" held only if the owner wrote cron by
hand. These tests keep both agents in the installer, keep their commands real (they parse in
the CLI parser the same installation ships) and keep them inert: a calendar trigger, no
KeepAlive, and no hand on the recorder.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cryptobot.cli import build_parser

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL = REPO_ROOT / "deploy" / "macos" / "install.sh"

# label -> argv after ``-m cryptobot.cli`` (the command the agent must actually run)
AGENTS = {
    "com.cryptobot.verdict-watch": ["verdict-watch", "--once"],
    "com.cryptobot.pnl": ["pnl", "daily"],
}
IDS = list(AGENTS)


def _script() -> str:
    assert INSTALL.is_file(), f"missing {INSTALL}"
    return INSTALL.read_text(encoding="utf-8")


def _agent_block(text: str, label: str) -> str:
    """The here-document body of ``install_one <label> "$(cat <<EOF``."""
    marker = f'install_one {label} "$(cat <<EOF'
    start = text.find(marker)
    assert start != -1, f"install.sh does not install {label}"
    end = text.find("\nEOF\n", start)
    assert end != -1, f"unterminated here-document for {label}"
    return text[start:end]


@pytest.mark.parametrize("label", IDS)
def test_installer_schedules_the_agent(label):
    block = _agent_block(_script(), label)
    assert f"<key>Label</key><string>{label}</string>" in block
    tokens = ["<string>-m</string>", "<string>cryptobot.cli</string>"]
    tokens += [f"<string>{part}</string>" for part in AGENTS[label]]
    for token in tokens:
        assert token in block, f"{label} does not run {token}"


@pytest.mark.parametrize("label", IDS)
def test_agent_is_a_plain_daily_calendar_agent(label):
    block = _agent_block(_script(), label)
    assert "<key>StartCalendarInterval</key>" in block, f"{label} needs a daily trigger"
    assert "<key>Hour</key>" in block and "<key>Minute</key>" in block
    assert "<key>KeepAlive</key>" not in block, f"{label} must not restart itself"
    assert "<key>RunAtLoad</key>" not in block, f"{label} must not run at install time"
    assert "<key>StartInterval</key>" not in block
    assert "recorder" not in block, f"{label} must not touch the recorder"
    assert "caffeinate" not in block, f"{label} is a short job, not a long-lived one"


@pytest.mark.parametrize("label", IDS)
def test_the_scheduled_command_exists_in_the_cli_parser(label):
    args = build_parser().parse_args(AGENTS[label])
    assert callable(getattr(args, "func", None)), f"{AGENTS[label]} has no command function"


def test_the_verdict_agent_passes_once():
    """``verdict-watch`` refuses without ``--once`` (it is the cron idiom), so it must be
    in the installed argv, not left to the installer's environment."""
    args = build_parser().parse_args(AGENTS["com.cryptobot.verdict-watch"])
    assert args.once is True


def test_the_agents_do_not_replace_the_existing_ones():
    text = _script()
    for label in ("com.cryptobot.recorder", "com.cryptobot.refresh",
                  "com.cryptobot.autopilot", "com.cryptobot.adjudicate",
                  "com.cryptobot.watchdog"):
        assert f"install_one {label} " in text, f"{label} disappeared from install.sh"
