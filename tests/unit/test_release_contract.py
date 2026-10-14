"""Release contract v1 proofs (W1 trading core, Checkpoint A).

Session._apply_engine_event is the ONE idempotent booking handler:
persist-first fills keyed by execution_id, max-applied cumulative qty
per order, version-gated order truth, AccountSnapshot venue leg,
command intentions + resume reconcile, single-instance lock, versioned
reader + backup. No adapter file is touched here; doubles implement
the contract surface from app/engine.py.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from cryptobot.app.engine import (AccountPosition, AccountSnapshot,
                                  EngineEvent, EngineFill,
                                  EngineOrderStatus)
from cryptobot.app.session import Session
from cryptobot.app.store import RunStore, StoreLocked, UnsafeState


def _config(tmp_path, **over):
    from cryptobot.app.config import load_config
    text = open("configs/paper.toml").read()
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    for key, value in over.items():
        text = text.replace(f"{key} =", f"{key} = {value} #", 1)
    path = tmp_path / "test.toml"
    path.write_text(text)
    return load_config(path)


class _ContractEngine:
    """Double implementing the contract v1 adapter surface."""

    def __init__(self):
        self.states = {}
        self.versions = {}
        self.cancelled = []
        self.unknown = ()
        self.snapshot = None
        self.bound = None
        self.fail_cancel = set()

    def open_orders(self):
        return [s for s in self.states.values()
                if s.state in ("open", "partial")]

    def order_status(self, cid):
        return self.states.get(cid)

    def unknown_ids(self):
        return tuple(self.unknown)

    def account_snapshot(self):
        return self.snapshot

    def bind_sink(self, handler):
        self.bound = handler

    def resolve(self, cid):
        return cid

    def cancel(self, cid, reason):
        if cid in self.fail_cancel:
            raise ValueError("venue:cancel-rejected")
        self.cancelled.append(cid)

    def attach_protection(self, entry, stop, target):
        n = len(self.cancelled) + len(self.states) + 1
        return [f"stop-{n}", f"tgt-{n}"]

    def submit_immediate(self, cmd):
        self.states[f"imm-{len(self.states)}"] = EngineOrderStatus(
            f"imm-{len(self.states)}", cmd.instrument, "open",
            cmd.qty, 0.0, cmd.reservation_id, "target")
        return f"imm-{len(self.states) - 1}"

    def submit(self, cmd):
        cid = f"e-{len(self.states)}"
        self.states[cid] = EngineOrderStatus(
            cid, cmd.instrument, "open", cmd.qty, 0.0,
            cmd.reservation_id, "entry")
        return cid

    def poll(self):
        return []

    def account_margin(self):
        return None

    def recover(self, sink):
        pass

    def close(self):
        pass


def _session(tmp_path, engine, run_id="rel"):
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    session = Session(_config(tmp_path), store, tmp_path / "runs" / run_id,
                      run_id, engine=engine)
    store.create_run(run_id, "replay", "fp", str(session.workdir), None)
    session.policy.reconcile_day(120.0, 0.0)
    return session, store


def _reservation(session, rid="r-1", qty=1.0):
    from cryptobot.risk.state import Reservation
    now = session.now_utc()
    return Reservation(
        reservation_id=rid, intent_ref="t:1", instrument="BTCUSDT",
        side="LONG", notional=100.0 * qty, reserved_risk=1.0,
        created_utc=now.isoformat(),
        expires_utc=(now + timedelta(seconds=60)).isoformat(), qty=qty)


def _position(**kw):
    pos = {"reservation_id": "r-1", "instrument": "BTCUSDT", "side": "LONG",
           "entry_pre_id": "e", "entry_id": "e", "legs": [], "retired": [],
           "stop": 99.0, "target": 102.0,
           "time_exit": datetime.now(timezone.utc) + timedelta(hours=1),
           "legacy_exit": None, "protected": False, "protect_attempts": 0,
           "entry_cap": None, "close_ids": [], "emergency_latched": False,
           "exposure_noted": False}
    pos.update(kw)
    return pos


def _fill(session, cid="e", exec_id="x1", qty=1.0, fee=0.05):
    return EngineEvent("fill", EngineFill(
        execution_id=exec_id, client_order_id=cid, instrument="BTCUSDT",
        side="BUY", qty=qty, price=100.0, fee=fee,
        ts_utc=session.now_utc(), liquidity="taker"), session.now_utc())


def _events(store, run_id="rel", kind="fill"):
    return [json.loads(r[0]) for r in store._db.execute(
        "SELECT payload FROM execution_events WHERE run_id=? AND kind=?",
        (run_id, kind)).fetchall()]


# --- one handler: push + drain + redelivery book once -------------------

def test_bound_push_books_once_with_ledger_and_fees(tmp_path):
    engine = _ContractEngine()
    session, store = _session(tmp_path, engine)
    try:
        assert engine.bound is not None  # Session binds at construction.
        session._position = _position()
        session.policy._state.reservations["r-1"] = _reservation(session)
        session._known_reservations.add("r-1")
        engine.states["e"] = EngineOrderStatus(
            "e", "BTCUSDT", "filled", 1.0, 1.0, "r-1", "entry", version=2)
        engine.bound(_fill(session))  # push delivery, as adapters do.
        assert session.ledger.position_qty() == pytest.approx(1.0)
        assert session.policy.booked_net("r-1") == pytest.approx(1.0)
        assert session.ledger.paid_costs() == pytest.approx(0.05)
        assert session._order_cum["e"] == pytest.approx(1.0)
        assert len(_events(store)) == 1
        fills = (session.workdir / "fills.jsonl").read_text().splitlines()
        assert len(fills) == 1
        row = json.loads(fills[0])
        assert (row["execution_id"], row["client_order_id"]) == ("x1", "e")
    finally:
        store.close()


def test_duplicate_fill_is_noop_and_counted(tmp_path):
    engine = _ContractEngine()
    session, store = _session(tmp_path, engine)
    try:
        session._position = _position()
        session.policy._state.reservations["r-1"] = _reservation(session)
        session._known_reservations.add("r-1")
        engine.states["e"] = EngineOrderStatus(
            "e", "BTCUSDT", "filled", 1.0, 1.0, "r-1", "entry")
        session._apply_engine_event(_fill(session))
        session._apply_engine_event(_fill(session))  # stream + REST redelivery.
        assert session.ledger.position_qty() == pytest.approx(1.0)
        assert session.policy.booked_net("r-1") == pytest.approx(1.0)
        assert session._order_cum["e"] == pytest.approx(1.0)
        assert session._dup_events == 1
        assert len(_events(store)) == 1
        fills = (session.workdir / "fills.jsonl").read_text().splitlines()
        assert len(fills) == 1
    finally:
        store.close()


def test_partial_fills_accumulate_cumulative_never_rolls_back(tmp_path):
    engine = _ContractEngine()
    session, store = _session(tmp_path, engine)
    try:
        session._position = _position()
        session.policy._state.reservations["r-1"] = _reservation(session)
        session._known_reservations.add("r-1")
        engine.states["e"] = EngineOrderStatus(
            "e", "BTCUSDT", "partial", 1.0, 0.4, "r-1", "entry")
        session._apply_engine_event(_fill(session, exec_id="x1", qty=0.4))
        session._apply_engine_event(_fill(session, exec_id="x2", qty=0.6))
        session._apply_engine_event(_fill(session, exec_id="x1", qty=0.4))
        assert session._order_cum["e"] == pytest.approx(1.0)
        assert session.ledger.position_qty() == pytest.approx(1.0)
        assert session._dup_events == 1
    finally:
        store.close()


def test_stale_status_version_keeps_newer_view(tmp_path):
    engine = _ContractEngine()
    session, store = _session(tmp_path, engine)
    try:
        engine.states["e"] = EngineOrderStatus(
            "e", "BTCUSDT", "partial", 1.0, 0.7, "r-1", "entry", version=5)
        fresh = session._tracked_status("e")
        assert fresh.filled_qty == pytest.approx(0.7)
        # Out-of-order update: older version, rolled-back quantity.
        engine.states["e"] = EngineOrderStatus(
            "e", "BTCUSDT", "partial", 1.0, 0.2, "r-1", "entry", version=3)
        stale = session._tracked_status("e")
        assert stale.filled_qty == pytest.approx(0.7)
        assert session._stale_status == 1
        # Newer version applies.
        engine.states["e"] = EngineOrderStatus(
            "e", "BTCUSDT", "filled", 1.0, 1.0, "r-1", "entry", version=9)
        assert session._tracked_status("e").filled_qty == pytest.approx(1.0)
    finally:
        store.close()


def test_legacy_sink_delta_consumed_by_poll_event_with_client_id(tmp_path):
    engine = _ContractEngine()
    session, store = _session(tmp_path, engine)
    try:
        session._position = _position()
        session.policy._state.reservations["r-1"] = _reservation(session)
        session._known_reservations.add("r-1")
        engine.states["e"] = EngineOrderStatus(
            "e", "BTCUSDT", "filled", 1.0, 1.0, "r-1", "entry")
        # Pre-migration paper order: sink call first, poll event after.
        session._engine_handler.note_fill_delta(
            "r-1", "x1", "BTCUSDT", "BUY", 1.0, 100.0, 0.05,
            session.now_utc().isoformat())
        assert session.ledger.position_qty() == pytest.approx(0.0)
        session._apply_engine_event(_fill(session))
        session._drain_engine()  # flush: nothing left staged.
        assert session.ledger.position_qty() == pytest.approx(1.0)
        assert session._staged_deltas == {}
        row = json.loads(
            (session.workdir / "fills.jsonl").read_text().splitlines()[0])
        assert row["client_order_id"] == "e"  # real id, not adopted.
    finally:
        store.close()


def test_staged_delta_without_event_flushes_as_adopted(tmp_path):
    engine = _ContractEngine()
    session, store = _session(tmp_path, engine)
    try:
        session._position = _position()
        session.policy._state.reservations["r-1"] = _reservation(session)
        session._known_reservations.add("r-1")
        session._engine_handler.note_fill_delta(
            "r-1", "x9", "BTCUSDT", "BUY", 0.5, 100.0, 0.05,
            session.now_utc().isoformat())
        session._drain_engine()
        assert session.ledger.position_qty() == pytest.approx(0.5)
        row = json.loads(
            (session.workdir / "fills.jsonl").read_text().splitlines()[0])
        assert row["client_order_id"] == "adopted:r-1"
    finally:
        store.close()


# --- foreign exposure: never booked, always flagged ----------------------

def test_unknown_fill_never_books_and_blocks_entries(tmp_path):
    engine = _ContractEngine()
    session, store = _session(tmp_path, engine)
    try:
        session._position = _position()
        session.policy._state.reservations["r-1"] = _reservation(session)
        session._known_reservations.add("r-1")
        engine.states["e"] = EngineOrderStatus(
            "e", "BTCUSDT", "open", 1.0, 0.0, "r-1", "entry")
        outcome = session._apply_fill(
            client_order_id="foreign-1", execution_id="fx1",
            instrument="BTCUSDT", side="BUY", qty=2.0, price=100.0,
            fee=0.05, ts_utc=session.now_utc(), liquidity="taker")
        assert outcome == "unbooked"
        assert session.ledger.position_qty() == pytest.approx(0.0)
        assert session.policy.booked_net("r-1") == pytest.approx(0.0)
        assert session._booking_blocked == "unknown-fill:foreign-1"
        assert session._admission_hold() == "booking:unknown-fill:foreign-1"
        kinds = [r[0] for r in store._db.execute(
            "SELECT kind FROM checkpoints WHERE run_id='rel'").fetchall()]
        assert "fill-unbooked" in kinds
        # The event itself is still durable history.
        assert len(_events(store)) == 1
    finally:
        store.close()


def test_venue_position_with_empty_cache_is_not_flat(tmp_path):
    engine = _ContractEngine()
    session, store = _session(tmp_path, engine)
    try:
        session._position = _position()
        session.policy._state.reservations["r-1"] = _reservation(session)
        engine.states["e"] = EngineOrderStatus(
            "e", "BTCUSDT", "cancelled", 1.0, 0.0, "r-1", "entry")
        statuses = session._tracked_statuses_for(session._position)
        # Flat everywhere locally...
        assert session._release_agrees(
            session._position, statuses, statuses["e"]) is True
        # ...but the venue reports a position: not flat, no touch.
        engine.snapshot = AccountSnapshot(
            wallet_equity_usdt=120.0, available_margin_usdt=100.0,
            margin_balance_usdt=120.0,
            positions=(AccountPosition("BTCUSDT", 0.5,
                                       entry_price=100.0),),
            asof_utc=session.now_utc(), complete=True)
        assert session._release_agrees(
            session._position, statuses, statuses["e"]) is False
        assert session.ledger.position_qty() == pytest.approx(0.0)
        kinds = [r[0] for r in store._db.execute(
            "SELECT kind FROM checkpoints WHERE run_id='rel'").fetchall()]
        assert "flat-blocked" in kinds
    finally:
        store.close()


def test_incomplete_snapshot_is_never_flat(tmp_path):
    engine = _ContractEngine()
    session, store = _session(tmp_path, engine)
    try:
        session._position = _position()
        session.policy._state.reservations["r-1"] = _reservation(session)
        engine.states["e"] = EngineOrderStatus(
            "e", "BTCUSDT", "cancelled", 1.0, 0.0, "r-1", "entry")
        engine.snapshot = AccountSnapshot(
            wallet_equity_usdt=120.0, available_margin_usdt=100.0,
            positions=(), asof_utc=session.now_utc(), complete=False)
        statuses = session._tracked_statuses_for(session._position)
        assert session._release_agrees(
            session._position, statuses, statuses["e"]) is False
        # A complete empty snapshot agrees.
        engine.snapshot = AccountSnapshot(
            wallet_equity_usdt=120.0, available_margin_usdt=100.0,
            positions=(), asof_utc=session.now_utc(), complete=True)
        assert session._release_agrees(
            session._position, statuses, statuses["e"]) is True
    finally:
        store.close()


# --- command intentions + reconcile --------------------------------------

def test_terminal_event_resolves_submit_command(tmp_path):
    engine = _ContractEngine()
    session, store = _session(tmp_path, engine)
    try:
        session._position = _position()
        session.policy._state.reservations["r-1"] = _reservation(session)
        cmd = session._new_command("submit", {"role": "entry"})
        store.update_command(cmd, "submitted", engine_client_id="e")
        assert len(store.open_commands("rel")) == 1
        from cryptobot.app.engine import EngineCancel
        session._apply_engine_event(EngineEvent(
            "cancel", EngineCancel("e", "BTCUSDT", "ioc-remainder",
                                   session.now_utc()), session.now_utc()))
        assert store.open_commands("rel") == []
    finally:
        store.close()


def test_command_without_engine_id_goes_unknown_and_holds(tmp_path):
    engine = _ContractEngine()
    session, store = _session(tmp_path, engine)
    try:
        # Crash inside submit: intention persisted, no engine id back.
        session._new_command("submit", {"role": "entry"})
        session._reconcile_commands()
        pending = store.open_commands("rel")
        assert len(pending) == 1 and pending[0]["status"] == "unknown"
        assert session._admission_hold() == "reconcile:unknown-commands"
    finally:
        store.close()


def test_orphan_close_attributes_single_unresolved_reservation(tmp_path):
    engine = _ContractEngine()
    session, store = _session(tmp_path, engine)
    try:
        session.ledger.record_fill("BUY", 1.0, 100.0, 0.05,
                                   session.now_utc(), "f1", "BTCUSDT")
        session.policy._state.unresolved["r-9"] = {"since": "t"}
        session._known_reservations.add("r-9")
        session._position = None
        session._flatten("test-orphan")
        assert session._orphan_close_ids == ["imm-0"]
        assert engine.states["imm-0"].reservation_id == "r-9"
        cmds = store.open_commands("rel")
        assert len(cmds) == 1
        assert cmds[0]["payload"]["reservation_id"] == "r-9"
        assert cmds[0]["payload"]["role"] == "close"
    finally:
        store.close()


# --- resume: rebuild + replay --------------------------------------------

def test_resume_rebuilds_idempotency_and_heals_ledger(tmp_path):
    engine = _ContractEngine()
    session, store = _session(tmp_path, engine)
    try:
        session._position = _position()
        session.policy._state.reservations["r-1"] = _reservation(session)
        session._known_reservations.add("r-1")
        engine.states["e"] = EngineOrderStatus(
            "e", "BTCUSDT", "filled", 1.0, 1.0, "r-1", "entry")
        session._apply_engine_event(_fill(session))
        assert session.ledger.position_qty() == pytest.approx(1.0)
        session._new_command("submit", {"role": "entry"})
        # Crash persisted-but-unbooked row: same run, fresh objects.
        store2 = RunStore(tmp_path / "runs" / "cryptobot.db")
        session2 = Session(_config(tmp_path), store2,
                           tmp_path / "runs" / "rel", "rel",
                           engine=_ContractEngine())
        try:
            session2.policy.reconcile_day(120.0, 0.0)
            session2.policy._state.reservations["r-1"] = _reservation(
                session2)
            # No explicit seeding: the converted reservation is known
            # via booked history (regression: live/unresolved miss it).
            session2._rebuild_booking_state()
            assert "r-1" in session2._known_reservations
            assert session2._applied_exec == {"x1"}
            assert session2._order_cum["e"] == pytest.approx(1.0)
            assert session2._cmd_seq == 1  # continues past existing rows.
            # Ledger healed from the durable anchor (no double-book).
            assert session2.ledger.position_qty() == pytest.approx(1.0)
            assert session2.policy.booked_net("r-1") == pytest.approx(1.0)
            session2._rebuild_booking_state()  # replay is idempotent.
            assert session2.ledger.position_qty() == pytest.approx(1.0)
        finally:
            store2.close()
    finally:
        store.close()


def test_resume_replays_staged_row_as_adopted(tmp_path):
    engine = _ContractEngine()
    session, store = _session(tmp_path, engine)
    try:
        session._position = _position()
        session.policy._state.reservations["r-1"] = _reservation(session)
        session._known_reservations.add("r-1")
        # Crash between stage-persist and poll booking.
        session._engine_handler.note_fill_delta(
            "r-1", "x7", "BTCUSDT", "BUY", 0.25, 100.0, 0.05,
            session.now_utc().isoformat())
        assert session.ledger.position_qty() == pytest.approx(0.0)
        store2 = RunStore(tmp_path / "runs" / "cryptobot.db")
        session2 = Session(_config(tmp_path), store2,
                           tmp_path / "runs" / "rel", "rel",
                           engine=_ContractEngine())
        try:
            session2.policy.reconcile_day(120.0, 0.0)
            session2.policy._state.reservations["r-1"] = _reservation(
                session2)
            session2._known_reservations.add("r-1")
            session2._rebuild_booking_state()
            assert session2.ledger.position_qty() == pytest.approx(0.25)
            row = json.loads(
                (session2.workdir / "fills.jsonl").read_text(
                ).splitlines()[0])
            assert row["client_order_id"] == "adopted:r-1"
        finally:
            store2.close()
    finally:
        store.close()


# --- crash window: journaled-but-undrained fill adopts -------------------

def test_crash_before_first_drain_adopts_via_alias(tmp_path):
    from cryptobot.app.engine import EngineOrder
    from cryptobot.app.reference import ReferenceEngine
    log = tmp_path / "runs" / "cr" / "om.jsonl"
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    engine = ReferenceEngine(log_path=log, outcome_sink=None, taker_bps=5.0)
    session = Session(_config(tmp_path), store, tmp_path / "runs" / "cr",
                      "cr", engine=engine)
    try:
        store.create_run("cr", "replay", "fp", str(session.workdir), None)
        session.policy.reconcile_day(120.0, 0.0)
        session.policy._state.reservations["r-1"] = _reservation(session)
        session.policy.note_executable_qty("r-1", 0.05)
        session._known_reservations.add("r-1")
        cmd = session._new_command(
            "submit", {"role": "entry", "reservation_id": "r-1"})
        engine.note_mark("BTCUSDT", 100.0)
        pre = engine.submit(EngineOrder(
            instrument="BTCUSDT", side="BUY", qty=0.05, kind="MARKET",
            reservation_id="r-1", role="entry"))
        store.update_command(cmd, "submitted", engine_client_id=pre)
        # CRASH: fill journaled in the adapter, Session never drained.
        assert store._db.execute(
            "SELECT COUNT(*) FROM execution_events").fetchone()[0] == 0
    finally:
        store.close()
    store2 = RunStore(tmp_path / "runs" / "cryptobot.db")
    engine2 = ReferenceEngine(log_path=log, outcome_sink=None,
                              taker_bps=5.0)
    session2 = Session(_config(tmp_path), store2, tmp_path / "runs" / "cr",
                       "cr", engine=engine2)
    try:
        session2.policy.reconcile_day(120.0, 0.0)
        session2._position = _position(entry_pre_id=pre, entry_id=None,
                                       approved_qty=0.05,
                                       executable_qty=0.05)
        session2._rebuild_booking_state()
        assert "r-1" in session2._known_reservations  # command intention.
        engine2.recover(session2._engine_handler)
        assert engine2.resolve(pre) is not None  # durable alias.
        session2._drain_engine()
        assert session2.ledger.position_qty() == pytest.approx(0.05)
        assert session2.policy.booked_net("r-1") == pytest.approx(0.05)
        assert session2._booking_blocked is None
    finally:
        store2.close()


# --- W5 blocking fix: protected posture engages --------------------------

def test_protected_posture_honors_advisory_only(tmp_path, monkeypatch):
    """Fail-open regression: paper-protected.toml must enforce (W5-15).

    The old posture-string compare never matched, so every Session
    ran advisory. Stub the startup verify + background refresher
    (network/threads stay out of unit tests); assert the decision.
    """
    from cryptobot.events import freshness as freshen
    calls = []
    monkeypatch.setattr(
        freshen.FreshnessTracker, "refresh_once",
        lambda self, store, http_get, now: calls.append(True) or {})
    monkeypatch.setattr(
        freshen.FreshnessTracker, "start", lambda *a, **k: None)
    text = open("configs/paper-protected.toml").read()
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    path = tmp_path / "protected.toml"
    path.write_text(text)
    from cryptobot.app.config import load_config
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    try:
        session = Session(load_config(path), store,
                          tmp_path / "runs" / "p", "p",
                          engine=_ContractEngine())
        assert session.protection is not None
        assert session.protection.advisory_only is False
        assert calls == [True]  # one blocking verify at startup.
    finally:
        store.close()


def test_research_profile_stays_advisory(tmp_path, monkeypatch):
    from cryptobot.events import freshness as freshen
    calls = []
    monkeypatch.setattr(
        freshen.FreshnessTracker, "refresh_once",
        lambda self, store, http_get, now: calls.append(True) or {})
    monkeypatch.setattr(
        freshen.FreshnessTracker, "start", lambda *a, **k: None)
    engine = _ContractEngine()
    session, store = _session(tmp_path, engine)
    try:
        if session.protection is not None:
            assert session.protection.advisory_only is True
        assert calls == []  # research: no blocking verify.
    finally:
        store.close()


# --- store: lock, versioned reader, backup, cursors ----------------------

def test_lock_reentrant_same_process_and_refuses_foreign(tmp_path):
    import fcntl
    path = tmp_path / "s.db"
    store = RunStore(path)
    try:
        store.acquire_lock()
        store.acquire_lock()  # re-entrant: refcounts, never blocks.
        store.release_lock()
        store.release_lock()
        # A foreign-held flock refuses with StoreLocked.
        fd = open(str(path.with_name("s.db.lock")), "w")
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with pytest.raises(StoreLocked):
                store.acquire_lock()
        finally:
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
            fd.close()
        store.acquire_lock()  # free again: succeeds.
    finally:
        store.close()


def test_versioned_reader_migrates_legacy_and_refuses_future(tmp_path):
    import sqlite3
    legacy = tmp_path / "legacy.db"
    raw = sqlite3.connect(str(legacy))
    raw.executescript(
        "CREATE TABLE runs (run_id TEXT PRIMARY KEY, mode TEXT,"
        " config_hash TEXT, state TEXT, pid INTEGER, started_utc TEXT,"
        " updated_utc TEXT, heartbeat_utc TEXT, workdir TEXT);")
    raw.commit()
    raw.close()
    store = RunStore(legacy)
    try:
        assert store.command_count("r") == 0  # v2 tables exist.
        assert store.durability_mode()["power_loss_safe"] is False
    finally:
        store.close()
    backups = list(tmp_path.glob("legacy.db.bak-*"))
    assert len(backups) == 1  # pre-migration backup taken.
    future = tmp_path / "future.db"
    raw = sqlite3.connect(str(future))
    raw.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY)")
    raw.execute("PRAGMA user_version=99")
    raw.commit()
    raw.close()
    with pytest.raises(UnsafeState):
        RunStore(future)


def test_backup_refuses_to_clobber_and_cursors_paginate(tmp_path):
    store = RunStore(tmp_path / "s.db")
    try:
        store.create_run("r", "replay", "h", str(tmp_path), None)
        dest = tmp_path / "b.db"
        out = store.backup(dest)
        assert out.exists()
        with pytest.raises(UnsafeState):
            store.backup(dest)
        store.record_event("r", "e1", "fill", {"q": 1})
        store.record_event("r", "e2", "fill", {"q": 2})
        first = store.read_events("r", after_id=0, limit=1)
        assert len(first) == 1 and first[0]["execution_id"] == "e1"
        rest = store.read_events("r", after_id=first[0]["cursor"])
        assert [r["execution_id"] for r in rest] == ["e2"]
        assert store.applied_exec_ids("r") == {"e1", "e2"}
        # Commands: dup id rejected, terminal never regresses.
        store.record_command("r", "c1", "submit", {})
        with pytest.raises(ValueError):
            store.record_command("r", "c1", "submit", {})
        store.update_command("c1", "submitted", engine_client_id="e")
        store.update_command("c1", "resolved")
        with pytest.raises(ValueError):
            store.update_command("c1", "submitted")
        with pytest.raises(KeyError):
            store.update_command("nope", "resolved")
        assert store.command_count("r") == 1
    finally:
        store.close()
