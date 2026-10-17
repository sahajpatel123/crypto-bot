"""T1.5: SIGTERM/SIGINT flatten by default; --leave-protected opt-out."""
from __future__ import annotations

from pathlib import Path

import pytest

from cryptobot.app.config import load_config
from cryptobot.app.session import Session
from cryptobot.app.store import RunStore


class _StubEngine:
    model_label = "t15-stub"
    assumptions = ("stub: t15",)

    def poll(self):
        return []

    def open_orders(self):
        return []


def _session(tmp_path: Path) -> Session:
    text = Path("configs/paper.toml").read_text()
    text = text.replace('mode = "replay"', 'mode = "paper"', 1)
    text = text.replace('kind = "reference"', 'kind = "nautilus"', 1)
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    cfg_path = tmp_path / "paper.toml"
    cfg_path.write_text(text)
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    return Session(load_config(cfg_path), store, tmp_path / "run",
                   "t15-run", engine=_StubEngine())


def test_shutdown_flattens_by_default(tmp_path):
    session = _session(tmp_path)
    calls = []
    session._flatten = lambda reason: calls.append(reason)  # noqa: SLF001
    out = session.shutdown_flatten()
    assert calls and "shutdown" in calls[0]
    assert out["confirmed_flat"] is True


def test_leave_protected_requires_confirmed_protection(tmp_path):
    session = _session(tmp_path)
    session.leave_protected = True
    # Flat with no position: nothing to protect — leaving is a no-op OK.
    out = session.shutdown_flatten()
    assert out["left_protected"] is False
    # Open position without legs: refuse to leave unprotected.
    session._position = {"symbol": "BTCUSDT", "legs": []}  # noqa: SLF001
    with pytest.raises(ValueError, match="protection"):
        session.shutdown_flatten()
