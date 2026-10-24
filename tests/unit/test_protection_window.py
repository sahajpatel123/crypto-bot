"""T1.4: shadow stop + protection-time budget (fault paths)."""
from __future__ import annotations

from pathlib import Path

from cryptobot.app.config import load_config
from cryptobot.app.session import Session
from cryptobot.app.store import RunStore


class _StubEngine:
    model_label = "t14-stub"
    assumptions = ("stub: t14",)

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
                   "t14-run", engine=_StubEngine())


def test_shadow_stop_long_and_short(tmp_path):
    session = _session(tmp_path)
    session._position = {"stop": 90.0, "legs": ["s1"]}  # noqa: SLF001
    session.ledger._qty = 0.1  # noqa: SLF001 — long
    assert session.shadow_stop_breached(89.0) is True
    assert session.shadow_stop_breached(95.0) is False
    session.ledger._qty = -0.1  # noqa: SLF001 — short
    assert session.shadow_stop_breached(91.0) is True
    assert session.shadow_stop_breached(85.0) is False


def test_protection_budget_flattens_and_alerts(tmp_path):
    session = _session(tmp_path)
    session.protection_budget_s = 30.0
    calls = []
    session._flatten = lambda reason: calls.append(reason)  # noqa: SLF001
    from datetime import timedelta
    old = (session.now_utc() - timedelta(hours=1)).isoformat()
    pos = {"stop": 90.0, "target": 110.0, "legs": [],
           "unprotected_since_utc": old}
    out = session.check_protection_budget(pos)
    assert out is True
    assert calls and "protection-gap" in calls[0]
    assert session.alerts[-1]["kind"] == "protection-gap"


def test_protection_budget_within_window_noop(tmp_path):
    session = _session(tmp_path)
    session.protection_budget_s = 30000.0
    pos = {"stop": 90.0, "target": 110.0, "legs": [],
           "unprotected_since_utc": session.now_utc().isoformat()}
    assert session.check_protection_budget(pos) is False
