"""F0.5 triage batch 4: supervision + shutdown + orphans (B#3,B#4,A#6,A#3,A#2,B#19).

B#3 (HIGH): shadow stop wired into _supervise (venue-independent
backstop when no live stop leg exists and mark breaches).
B#4 (HIGH): idle supervision evaluates health (detection runs without
market traffic, throttled).
A#6 (HIGH): missing marks fail closed (no more SHORT-shows-healthy).
A#3 (HIGH): shutdown drains between attempts, retains legs until the
close confirms, and safe-modes (loudly) when unconfirmed.
A#2 (CRITICAL): orphaned ledger exposure (no shell) is flattened by
supervision.
B#19 (MEDIUM): shell-less recovery releases risk state on flat.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from cryptobot.app.config import load_config
from cryptobot.app.session import Session
from cryptobot.app.store import RunStore

NOW = datetime(2026, 10, 17, 12, 0, 0, tzinfo=UTC)


class _Eng:
    model_label = "b4"
    assumptions = ()

    def __init__(self):
        self.submits = []
        self.cancels = []
        self.statuses: dict = {}
        self._seq = 0

    def poll(self):
        return []

    def open_orders(self):
        return []

    def order_status(self, cid):
        return self.statuses.get(cid)

    def resolve(self, cid):
        return cid if cid in self.statuses else None

    def cancel(self, cid, reason):
        self.cancels.append(cid)

    def submit_immediate(self, cmd):
        self._seq += 1
        cid = f"close-{self._seq}"
        self.submits.append(cmd)
        self.statuses[cid] = SimpleNamespace(state="open", filled_qty=0.0,
                                             qty=cmd.qty, role="target")
        return cid

    def account_snapshot(self):
        return SimpleNamespace(positions=())


def _session(tmp_path: Path, engine) -> Session:
    text = Path("configs/paper.toml").read_text()
    text = text.replace('mode = "replay"', 'mode = "paper"', 1)
    text = text.replace('kind = "reference"', 'kind = "nautilus"', 1)
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    cfg_path = tmp_path / "paper.toml"
    cfg_path.write_text(text)
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    session = Session(load_config(cfg_path), store, tmp_path / "run",
                      "b4-run", engine=engine)
    session.clock.set_ms(int(NOW.timestamp() * 1000))
    session.policy.reconcile_day(10000.0, 0.0)
    session.store.create_run("b4-run", "paper", "fp",
                             str(session.workdir), None)
    return session


def _long_pos(session, engine, qty=0.5, price=60000.0, stop=59000.0,
              fee=1.0):
    # Policy day matches the ledger paper seed (120) so stop math is
    # meaningful; size qty to keep breach losses below latch levels.
    session.policy.reconcile_day(120.0, 0.0)
    session.ledger.record_fill("BUY", qty, price, fee, NOW, "e1",
                               symbol="BTCUSDT")
    engine.statuses["entry-1"] = SimpleNamespace(state="filled",
                                                 filled_qty=qty, qty=qty,
                                                 role="entry")
    session._position = {  # noqa: SLF001
        "instrument": "BTCUSDT", "reservation_id": "r-1",
        "side": "LONG", "entry_id": "entry-1", "entry_pre_id": "entry-1",
        "legs": [], "retired": [], "close_ids": [],
        "cancel_requested": set(), "seen_ids": {"entry-1"},
        "protected": False, "protect_attempts": 0, "attach_filled": qty,
        "stop": stop, "target": 61000.0,
        "time_exit": datetime(2030, 1, 1, tzinfo=UTC)}
    from cryptobot.app.session import _SymbolFeed
    feed = _SymbolFeed("BTCUSDT", 0)
    feed.mark = price
    feed.mark_ts = NOW
    session._feeds["BTCUSDT"] = feed


def test_shadow_stop_flattens_when_no_live_stop(tmp_path):
    engine = _Eng()
    session = _session(tmp_path, engine)
    # Shadow-only zone: breach (59920 <= 59950) with -0.09 loss (no
    # policy latch: operating needs -0.60), proving SHADOW fired.
    _long_pos(session, engine, qty=0.001, stop=59950.0, fee=0.01)
    session._feeds["BTCUSDT"].mark = 59920.0
    session._feeds["BTCUSDT"].mark_ts = NOW
    session.control_tick()
    assert len(engine.submits) == 1, "shadow stop did not flatten"
    assert engine.submits[0].side == "SELL"
    rows = session.store._db.execute(  # noqa: SLF001
        "SELECT kind FROM checkpoints WHERE run_id='b4-run'").fetchall()
    assert ("shadow-stop",) in rows, rows


def test_shadow_quiet_when_venue_stop_live(tmp_path):
    engine = _Eng()
    session = _session(tmp_path, engine)
    _long_pos(session, engine, qty=0.001, stop=59950.0, fee=0.01)
    engine.statuses["stop-1"] = SimpleNamespace(state="open",
                                                filled_qty=0.0, qty=0.001,
                                                role="stop")
    session._position["legs"] = ["stop-1"]  # noqa: SLF001
    session._feeds["BTCUSDT"].mark = 59920.0
    session._feeds["BTCUSDT"].mark_ts = NOW
    session.control_tick()
    assert engine.submits == [], "venue owns the exit; shadow stays out"


def test_idle_supervision_latches_breached_stop(tmp_path):
    engine = _Eng()
    session = _session(tmp_path, engine)
    # Ledger scale is the paper seed (120): realize -0.6% (below the
    # 0.5% operating stop, above the 1% emergency stop) with no events.
    # A feed mark is present (flat: equity unaffected) so the mark-age
    # gate passes and stops evaluate.
    session.policy.reconcile_day(120.0, 0.0)
    session.ledger.record_fill("BUY", 0.001, 60000.0, 0.0, NOW, "e1",
                               symbol="BTCUSDT")
    session.ledger.record_fill("SELL", 0.001, 59280.0, 0.0, NOW, "e2",
                               symbol="BTCUSDT")
    assert session.ledger.net_realised() == -0.72
    from cryptobot.app.session import _SymbolFeed
    feed = _SymbolFeed("BTCUSDT", 0)
    feed.mark = 60000.0
    feed.mark_ts = NOW
    session._feeds["BTCUSDT"] = feed
    session.control_tick()  # idle: no market traffic at all
    today = session.policy._state.current_day  # noqa: SLF001
    assert today in session.policy._state.operating_stop_days, (  # noqa: SLF001
        "idle tick never evaluated the breached stop")


def test_missing_mark_blocks_entries_short(tmp_path):
    engine = _Eng()
    session = _session(tmp_path, engine)
    # SHORT 0.5 @60k, then ALL marks vanish (feed + engine).
    session.ledger.record_fill("SELL", 0.5, 60000.0, 1.0, NOW, "e1",
                               symbol="BTCUSDT")
    session._feeds.clear()
    engine.valuation_mark = lambda symbol: None
    session._saw_exchange_marks = False  # noqa: SLF001
    session._health_tick()  # noqa: SLF001
    assert any("mark-missing" in r
               for r in session._health_halt_reasons), (  # noqa: SLF001
        "SHORT with no marks must not report healthy")


def test_shutdown_retains_legs_until_close_confirms(tmp_path):
    from cryptobot.adapters.binance_live import UnknownOutcomeError

    engine = _Eng()
    session = _session(tmp_path, engine)
    _long_pos(session, engine)
    engine.statuses["stop-1"] = SimpleNamespace(state="open",
                                                filled_qty=0.0, qty=0.5,
                                                role="stop")
    session._position["legs"] = ["stop-1"]  # noqa: SLF001

    def _boom(cmd):
        raise UnknownOutcomeError("close-x", "submit 504")

    engine.submit_immediate = _boom
    out = session.shutdown_flatten(attempts=2)
    assert out["confirmed_flat"] is False
    assert engine.cancels == [], (
        f"legs cancelled before close confirmed: {engine.cancels}")


def test_shutdown_unconfirmed_enters_safe_mode(tmp_path):
    from cryptobot.adapters.binance_live import UnknownOutcomeError

    engine = _Eng()
    session = _session(tmp_path, engine)
    _long_pos(session, engine)
    engine.submit_immediate = lambda cmd: (_ for _ in ()).throw(
        UnknownOutcomeError("close-x", "submit 504"))
    session._stop_flag = "graceful"  # noqa: SLF001
    out = session.control_tick()
    assert out == "operator-stop:graceful"
    assert session.safe_mode_reason is not None, (
        "unconfirmed shutdown must safe-mode loudly")


def test_orphan_exposure_flattened_by_supervision(tmp_path):
    engine = _Eng()
    session = _session(tmp_path, engine)
    session.policy.reconcile_day(120.0, 0.0)
    session.ledger.record_fill("BUY", 0.001, 60000.0, 0.01, NOW, "e1",
                               symbol="BTCUSDT")
    assert session._position is None  # noqa: SLF001 — orphaned, no shell
    from cryptobot.app.session import _SymbolFeed
    feed = _SymbolFeed("BTCUSDT", 0)
    feed.mark = 60000.0
    feed.mark_ts = NOW
    session._feeds["BTCUSDT"] = feed
    session.control_tick()
    assert len(engine.submits) == 1, "orphan exposure unsupervised"
    assert engine.submits[0].side == "SELL"


def test_retry_pending_flatten_releases_risk_on_flat(tmp_path):
    engine = _Eng()
    session = _session(tmp_path, engine)
    assert session._position is None  # noqa: SLF001
    session.policy._state.open_position = True  # noqa: SLF001
    session._flatten_pending = True  # noqa: SLF001
    session._retry_pending_flatten("triage")  # noqa: SLF001
    assert session.policy._state.open_position is False  # noqa: SLF001
    assert session.policy.live_reservations() == ()
