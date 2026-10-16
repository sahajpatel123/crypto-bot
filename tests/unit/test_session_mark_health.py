"""A stale mark halts entries. A later fresh snapshot lifts only that halt.

The paper engine stores one bool and refuses an entry with
PermissionError while it is set. Releasing the mark reason must clear
that refusal when no other halt remains, and must keep the refusal
when another halt remains.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cryptobot.app.config import load_config
from cryptobot.app.engine import EngineOrder
from cryptobot.app.session import Session
from cryptobot.app.store import RunStore
from cryptobot.risk.types import HealthStatus


class _BoolEngine:
    def __init__(self) -> None:
        self.halted = False

    def set_exit_only(self, halted: bool, reason: str = "") -> None:
        self.halted = halted

    def open_orders(self):
        return []


def _session(tmp_path: Path, engine, run_id: str = "mark"):
    text = Path("configs/sc-dev.toml").read_text(encoding="utf-8")
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    path = tmp_path / "sc.toml"
    path.write_text(text, encoding="utf-8")
    cfg = load_config(path)
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    session = Session(cfg, store, tmp_path / "runs" / run_id, run_id,
                      engine=engine)
    session.policy.reconcile_day(120.0, 0.0)
    session.store.create_run(run_id, cfg.mode, "fp", str(session.workdir),
                              None)
    return session


def test_supervision_does_not_clear_a_stale_mark(tmp_path):
    engine = _BoolEngine()
    session = _session(tmp_path, engine)
    session._apply_account_health(
        HealthStatus(False, ("health:stale-mark",), ()))
    assert session.control_tick() is None
    assert "health:stale-mark" in session._exit_only_reasons
    assert engine.halted is True


def test_paper_entry_refused_while_stale_and_accepted_when_fresh(tmp_path):
    pytest.importorskip("nautilus_trader")
    from cryptobot.adapters import NautilusPaperEngine

    engine = NautilusPaperEngine(taker_bps=5.0, submit_delay_ms=0)
    engine.add_instrument("BTCUSDT", price_precision=2, size_precision=3,
                          tick_size=0.01, step_size=0.001)
    session = _session(tmp_path, engine, run_id="mark-paper")
    session._apply_account_health(
        HealthStatus(False, ("health:stale-mark",), ()))
    with pytest.raises(PermissionError, match="exit-only"):
        engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    session._apply_account_health(HealthStatus(True, (), ()))
    assert engine._exit_only is False
    cid = engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
    assert isinstance(cid, str) and cid


def test_another_halt_keeps_the_paper_entry_refused(tmp_path):
    pytest.importorskip("nautilus_trader")
    from cryptobot.adapters import NautilusPaperEngine

    engine = NautilusPaperEngine(taker_bps=5.0, submit_delay_ms=0)
    engine.add_instrument("BTCUSDT", price_precision=2, size_precision=3,
                          tick_size=0.01, step_size=0.001)
    session = _session(tmp_path, engine, run_id="mark-hold")
    session._halt_entries("funding-mismatch")
    session._apply_account_health(
        HealthStatus(False, ("health:stale-mark",), ()))
    session._apply_account_health(HealthStatus(True, (), ()))
    assert "health:stale-mark" not in session._exit_only_reasons
    assert "funding-mismatch" in session._exit_only_reasons
    assert engine._exit_only is True
    with pytest.raises(PermissionError, match="exit-only"):
        engine.submit(EngineOrder("BTCUSDT", "BUY", 0.001, "MARKET"))
