"""F0.5 triage batch 1: unknown-close handling (A#1, B#7, B#8).

A#1 (CRITICAL): a close reporting state "unknown" (live UNKNOWN /
CANCEL_UNKNOWN, paper restart-lost) must count as in flight; the old
code only treated None/open/partial as live and submitted a SECOND
full-size close -> reversal.
B#7 (HIGH): enter_safe_mode must not report flatten_ok=True while
closes remain unknown/unconfirmed.
B#8 (HIGH): _is_flat_confirmed must not treat venue-unreachable
(account_snapshot None) as confirmed flat.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from cryptobot.app.config import load_config
from cryptobot.app.session import Session
from cryptobot.app.store import RunStore

NOW = datetime(2026, 10, 17, 12, 0, 0, tzinfo=UTC)


class _ScriptedEngine:
    model_label = "triage-stub"
    assumptions = ("stub: triage",)

    def __init__(self):
        self.submits: list = []
        self.statuses: dict[str, SimpleNamespace] = {}
        self.snapshot = SimpleNamespace(positions=())
        self._seq = 0

    def poll(self):
        return []

    def open_orders(self):
        return []

    def submit_immediate(self, cmd):
        self._seq += 1
        cid = f"close-{self._seq}"
        self.submits.append(cmd)
        self.statuses[cid] = SimpleNamespace(state="open", filled_qty=0.0)
        return cid

    def order_status(self, cid):
        return self.statuses.get(cid)

    def cancel(self, cid, reason):
        return None

    def account_snapshot(self):
        return self.snapshot


def _session(tmp_path: Path) -> Session:
    text = Path("configs/paper.toml").read_text()
    text = text.replace('mode = "replay"', 'mode = "paper"', 1)
    text = text.replace('kind = "reference"', 'kind = "nautilus"', 1)
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    cfg_path = tmp_path / "paper.toml"
    cfg_path.write_text(text)
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    engine = _ScriptedEngine()
    session = Session(load_config(cfg_path), store, tmp_path / "run",
                      "triage-run", engine=engine)
    return session


def _long_position(session: Session, engine: _ScriptedEngine, qty=0.5):
    session.ledger.record_fill("BUY", qty, 60000.0, 1.0, NOW, "e1",
                               symbol="BTCUSDT")
    engine.statuses["entry-1"] = SimpleNamespace(state="filled",
                                                 filled_qty=qty)
    session._position = {  # noqa: SLF001
        "instrument": "BTCUSDT", "reservation_id": "r-000001",
        "entry_id": "entry-1", "entry_pre_id": "entry-1",
        "legs": [], "retired": [], "close_ids": [],
        "cancel_requested": set(), "seen_ids": set(),
        "protected": False,
        "time_exit": datetime(2030, 1, 1, tzinfo=UTC)}


def test_unknown_close_blocks_second_submit(tmp_path):
    session = _session(tmp_path)
    engine = session.engine
    _long_position(session, engine)
    # First flatten submits close-1; venue goes UNKNOWN (may have filled).
    session._flatten("triage")  # noqa: SLF001
    assert len(engine.submits) == 1
    cid1 = session._position["close_ids"][0]  # noqa: SLF001
    engine.statuses[cid1] = SimpleNamespace(state="unknown", filled_qty=0.0)
    # Second flatten must NOT submit close-2 (A#1 reversal).
    session._flatten("triage")  # noqa: SLF001
    assert len(engine.submits) == 1, (
        f"duplicate close submitted over unknown {cid1}")


def test_safe_mode_reports_unknown_not_ok(tmp_path):
    session = _session(tmp_path)
    engine = session.engine
    _long_position(session, engine)
    session._flatten("triage")  # noqa: SLF001
    cid1 = session._position["close_ids"][0]  # noqa: SLF001
    engine.statuses[cid1] = SimpleNamespace(state="unknown", filled_qty=0.0)
    out = session.enter_safe_mode("triage-unknown", attempts=2)
    assert out["flatten_ok"] is False, out
    assert "unknown" in str(out).lower(), out


def test_flat_unconfirmed_when_venue_unreachable(tmp_path):
    session = _session(tmp_path)
    engine = session.engine
    assert session.ledger.has_position() is False
    engine.snapshot = None  # venue unreachable: unknown, not flat
    assert session._is_flat_confirmed() is False  # noqa: SLF001
    engine.snapshot = SimpleNamespace(positions=())
    assert session._is_flat_confirmed() is True  # noqa: SLF001
    engine.snapshot = SimpleNamespace(
        positions=(SimpleNamespace(symbol="BTCUSDT", qty=0.5),))
    assert session._is_flat_confirmed() is False  # noqa: SLF001
