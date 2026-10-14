"""READY-§5 lifecycle proof matrix: state transitions, not just P&L.

Deterministic unit + real-engine tests for the six §5 invariants:
snap-before-approval, first-fill transition exactly once, confirmed-net
protection with pending-fill coverage, child tracking to terminal,
idempotent flatten, and fail-closed malformed ingest (W5 note).
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from cryptobot.accounting.ledger import Ledger
from cryptobot.app.engine import EngineEvent, EngineFill, EngineOrderStatus
from cryptobot.app.session import Session
from cryptobot.app.store import RunStore
from cryptobot.risk.policy import RiskPolicy
from cryptobot.risk.types import RiskConfig


def _config(tmp_path, **over):
    from cryptobot.app.config import load_config
    text = open("configs/paper.toml").read()
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    for key, value in over.items():
        text = text.replace(f"{key} =", f"{key} = {value} #", 1)
    path = tmp_path / "test.toml"
    path.write_text(text)
    return load_config(path)


def _session(tmp_path, engine):
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    session = Session(_config(tmp_path), store, tmp_path / "runs" / "ready",
                      "ready", engine=engine)
    store.create_run("ready", "replay", "fp", str(session.workdir), None)
    session.policy.reconcile_day(120.0, 0.0)
    return session, store


def _scripted_status(cid, state, qty=1.0, filled=0.0, rid=""):
    return EngineOrderStatus(client_order_id=cid, instrument="BTCUSDT",
                             state=state, qty=qty, filled_qty=filled,
                             reservation_id=rid)


class _ScriptEngine:
    """Minimal engine double with scripted order states."""

    def __init__(self):
        self.states = {}
        self.cancelled = []
        self.attached = []
        self.submitted_immediate = []
        self.fail_cancel_once = set()

    def open_orders(self):
        # Legacy snapshot retained for direct helper-level assertions
        # (some proofs script terminal states into open_orders()).
        # Migrated Session paths read order_status() instead.
        return [s for s in self.states.values()]

    def order_status(self, cid):
        # Contract v1 order truth (release migration): scripted
        # states incl. terminals; None only when never seen.
        # Version 0: the Session treats v0 reads as always current.
        return self.states.get(cid)

    def unknown_ids(self):
        return tuple(getattr(self, "unknown", ()))

    def bind_sink(self, handler):
        self.bound = handler

    def account_snapshot(self):
        return None

    def resolve(self, cid):
        return cid

    def cancel(self, cid, reason):
        if cid in self.fail_cancel_once:
            self.fail_cancel_once.discard(cid)
            raise ValueError("venue:cancel-rejected")
        self.cancelled.append(cid)

    def attach_protection(self, entry, stop, target):
        self.attached.append((entry, stop, target))
        script = getattr(self, "attach_script", None)
        if script:
            return script.pop(0)
        n = len(self.attached)
        return [f"stop-{n}", f"tgt-{n}"]

    def submit_immediate(self, cmd):
        self.submitted_immediate.append(cmd)
        return f"imm-{len(self.submitted_immediate)}"

    def set_exit_only(self, halted, reason=""):
        pass

    def poll(self):
        return []

    def account_margin(self):
        return {"available": 1e9, "locked": 0.0}


def _position(**kw):
    pos = {"reservation_id": "r-1", "instrument": "BTCUSDT", "side": "LONG",
           "entry_pre_id": "e", "entry_id": "e", "legs": [], "retired": [],
           "stop": 99.0, "target": 102.0,
           "time_exit": datetime.now(timezone.utc) + timedelta(hours=1),
           "legacy_exit": None, "protected": False, "protect_attempts": 0,
           "entry_cap": None, "close_ids": [], "emergency_latched": False}
    pos.update(kw)
    return pos


def _checkpoints(store):
    return [r[0] for r in store._db.execute(
        "SELECT kind FROM checkpoints WHERE run_id='ready'").fetchall()]


# --- inv 2: first-fill transition exactly once ---------------------------

def test_exposure_noted_exactly_once_on_duplicate_fills(tmp_path):
    engine = _ScriptEngine()
    session, store = _session(tmp_path, engine)
    try:
        session._position = _position()
        session.policy._state.reservations["r-1"] = _reservation(session)
        # Sink books first (as in production order flow), then events land.
        session.ledger.record_fill("BUY", 1.0, 100.0, 0.05,
                                   session.now_utc(), "x1")
        session.policy.note_fill_delta(
            "r-1", "x1", "BTCUSDT", "BUY", 1.0, 100.0, 0.05,
            session.now_utc().isoformat())
        engine.states = {"e": _scripted_status("e", "filled", 1.0, 1.0,
                                               "r-1")}
        fill = EngineFill(execution_id="x1", client_order_id="e",
                          instrument="BTCUSDT", side="BUY", qty=1.0,
                          price=100.0, fee=0.05, ts_utc=session.now_utc(),
                          liquidity="taker")
        session._on_engine_event(
            EngineEvent("fill", fill, session.now_utc()))
        session._on_engine_event(
            EngineEvent("fill", fill, session.now_utc()))  # duplicate
        assert session._position["exposure_noted"] is True
        assert session.policy._state.reservations == {}
        assert session.policy._state.open_position is True
        kinds = _checkpoints(store)
        assert kinds.count("exposure-noted") == 1
    finally:
        store.close()


def _reservation(session, rid="r-1", qty=1.0):
    from cryptobot.risk.state import Reservation
    now = session.now_utc()
    return Reservation(
        reservation_id=rid, intent_ref="t:1", instrument="BTCUSDT",
        side="LONG", notional=100.0 * qty, reserved_risk=1.0,
        created_utc=now.isoformat(),
        expires_utc=(now + timedelta(seconds=60)).isoformat(), qty=qty)


# --- inv 3: confirmed net + retired remainders ----------------------------

def test_ioc_remainder_retires_from_need(tmp_path):
    engine = _ScriptEngine()
    session, store = _session(tmp_path, engine)
    try:
        session._position = _position()
        session.policy._state.reservations["r-1"] = _reservation(session)
        session.policy.note_executable_qty("r-1", 0.6)
        session.ledger.record_fill("BUY", 0.6, 100.0, 0.03,
                                   session.now_utc(), "f1")
        # Entry terminal-cancelled (IOC remainder gone): need == net 0.6,
        # never the approved 1.0.
        statuses = {"e": _scripted_status("e", "cancelled", 1.0, 0.6,
                                          "r-1")}
        assert session._protection_need(session._position, statuses) == \
            pytest.approx(0.6)
        # Unknown entry outcome stays conservative (approved demand): a
        # second reservation with no narrowing demands its full 2.0.
        session.policy._state.reservations["r-2"] = _reservation(
            session, rid="r-2", qty=2.0)
        pos2 = _position(reservation_id="r-2")
        assert session._protection_need(pos2, {}) == pytest.approx(2.0)
    finally:
        store.close()


# --- inv 4: siblings + terminal tracking ----------------------------------

def test_stop_fill_settles_sibling_then_both_prune(tmp_path):
    engine = _ScriptEngine()
    session, store = _session(tmp_path, engine)
    try:
        session._position = _position(legs=["stop-1", "tgt-1"])
        engine.states = {
            "stop-1": _scripted_status("stop-1", "filled", 1.0, 1.0, "r-1"),
            "tgt-1": _scripted_status("tgt-1", "open", 1.0, 0.0, "r-1")}
        statuses = {s.client_order_id: s for s in engine.open_orders()}
        session._settle_leg_terminals(session._position, statuses)
        assert "tgt-1" in engine.cancelled  # sibling settled.
        assert session._position["legs"] == ["tgt-1"]  # winner pruned.
        engine.states["tgt-1"] = _scripted_status("tgt-1", "cancelled",
                                                 1.0, 0.0, "r-1")
        statuses = {s.client_order_id: s for s in engine.open_orders()}
        session._settle_leg_terminals(session._position, statuses)
        assert session._position["legs"] == []
    finally:
        store.close()


def test_absent_ids_never_pruned(tmp_path):
    engine = _ScriptEngine()
    session, store = _session(tmp_path, engine)
    try:
        session._position = _position(legs=["stop-9"])
        session._settle_leg_terminals(session._position, {})
        assert session._position["legs"] == ["stop-9"]
    finally:
        store.close()


# --- inv 5: idempotent flatten --------------------------------------------

def test_flatten_single_close_and_failed_cancel_retries(tmp_path):
    engine = _ScriptEngine()
    session, store = _session(tmp_path, engine)
    try:
        session._position = _position(legs=["stop-1"])
        session.ledger.record_fill("BUY", 1.0, 100.0, 0.05,
                                   session.now_utc(), "f1")
        engine.states = {"e": _scripted_status("e", "filled", 1.0, 1.0,
                                               "r-1"),
                         "stop-1": _scripted_status("stop-1", "open", 1.0,
                                                    0.0, "r-1")}
        engine.fail_cancel_once.add("stop-1")
        session._flatten("test")
        assert len(engine.submitted_immediate) == 1  # one close.
        assert engine.submitted_immediate[0].reduce_only is True
        assert engine.submitted_immediate[0].qty == pytest.approx(1.0)
        first_kinds = _checkpoints(store)
        assert first_kinds.count("flatten") == 1
        # Retry: failed cancel retried, close NOT duplicated (in flight).
        session._flatten("test")
        assert len(engine.submitted_immediate) == 1
        assert engine.cancelled.count("stop-1") == 1
        assert "e" not in engine.cancelled  # terminal: skipped.
    finally:
        store.close()


def test_emergency_latches_once_and_close_is_single(tmp_path):
    engine = _ScriptEngine()
    session, store = _session(tmp_path, engine)
    try:
        # Live exposure, attempts exhausted: emergency latches exactly
        # once and exactly one close is submitted across passes (the
        # absent close counts as in flight — reconcile before retry).
        session._position = _position(protect_attempts=3, attach_filled=1.0)
        session.ledger.record_fill("BUY", 1.0, 100.0, 0.05,
                                   session.now_utc(), "f1")
        engine.states = {"e": _scripted_status("e", "filled", 1.0, 1.0,
                                               "r-1")}
        for _ in range(3):
            session._ensure_protection(session._position)
        kinds = _checkpoints(store)
        assert kinds.count("protection-emergency") == 1
        assert kinds.count("flatten") == 1
        assert len(engine.submitted_immediate) == 1
    finally:
        store.close()


def test_vacuous_protection_stays_quiet(tmp_path):
    engine = _ScriptEngine()
    session, store = _session(tmp_path, engine)
    try:
        # Flat ledger, terminal entry: nothing to cover — repeated
        # protection passes stay silent (no checkpoints, no closes).
        session._position = _position()
        engine.states = {"e": _scripted_status("e", "filled", 1.0, 1.0,
                                               "r-1")}
        for _ in range(3):
            session._ensure_protection(session._position)
        kinds = _checkpoints(store)
        assert "protection-emergency" not in kinds
        assert "flatten" not in kinds
        assert engine.submitted_immediate == []
    finally:
        store.close()


# --- inv 6: real-engine exits (state transitions, in-bracket) --------

_RT0 = datetime(2026, 10, 12, 6, 0, tzinfo=timezone.utc)


def _paper_session(tmp_path):
    from cryptobot.adapters.paper_engine import NautilusPaperEngine
    engine = NautilusPaperEngine(
        taker_bps=5.0, now_utc=lambda: _RT0, submit_delay_ms=0,
        fill_delay_ms=1)
    engine.add_instrument("BTCUSDT", price_precision=2, size_precision=3,
                          tick_size=0.01, step_size=0.001, ts_utc=_RT0)
    session, store = _session(tmp_path, engine)
    try:
        engine.bind_sink(session.policy)
    except TypeError:
        # Post-migration paper requires an event callable; the
        # Session already bound its own handler at construction,
        # which then serves both push and booking (merge-proof).
        pass
    session.clock.set_ms(int(_RT0.timestamp() * 1000))
    session.policy.reconcile_day(120.0, 0.0)  # at the session day, not epoch.
    return session, store, engine


def _rintent(now, stop=99.0, target=102.0, exit_s=600):
    from cryptobot.coordination import (DataQuality, ForecastCost, Intent,
                                        Side, encode_exit_rule)
    from cryptobot.coordination.exits import ExitPolicy
    from cryptobot.coordination.selector import Candidate
    intent = Intent(
        strategy="S1", version="0.1.0", instrument="BTCUSDT", side=Side.LONG,
        evidence_ts_utc=now, entry_low=100.0, entry_high=100.5,
        entry_expiry_utc=now + timedelta(seconds=60),
        invalidation_price=99.0,
        exit_rule=encode_exit_rule(ExitPolicy(
            stop_price=stop, target_price=target,
            time_exit_utc=now + timedelta(seconds=exit_s),
            policy_id="test")),
        holding_limit_s=600, forecast_cost=ForecastCost(5.0, 5.0, 5.0, 1.0),
        evidence_ref="test:rt", data_quality=DataQuality.CLEAN)
    return [Candidate("S1", intent)]


def _seed_paper_mark(session):
    from cryptobot.app.session import _SymbolFeed
    feed = _SymbolFeed("BTCUSDT", 0)
    feed.mark = 100.2
    feed.mark_ts = session.now_utc()
    session._feeds["BTCUSDT"] = feed


def _paper_status(engine, cid):
    """Contract-tolerant order read (release migration rationale).

    Prefers order_status() when it returns contract truth, else the
    open_orders() snapshot (pre-migration paper keeps terminals
    there). Keeps these proofs green on both sides of W2's paper
    migration without weakening the asserted states.
    """
    query = getattr(engine, "order_status", None)
    if callable(query):
        try:
            status = query(cid)
        except (KeyError, ValueError):
            status = None
        if status is not None and hasattr(status, "state"):
            return status
    for status in engine.open_orders():
        if status.client_order_id == cid:
            return status
    raise KeyError(f"no tracked truth for {cid}")


def _pquote(engine, ms, bid, ask, bid_size=1.0, ask_size=1.0):
    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.model.objects import Price, Quantity
    ns = int((_RT0 + timedelta(milliseconds=ms)).timestamp() * 1e9)
    engine.feed(QuoteTick(
        engine.instrument_id("BTCUSDT"), Price(bid, 2), Price(ask, 2),
        Quantity(bid_size, 3), Quantity(ask_size, 3), ts_event=ns,
        ts_init=ns))


def _admit_paper(session, engine):
    _seed_paper_mark(session)
    _pquote(engine, 0, 100.0, 100.2)
    session._maybe_admit(_rintent(session.now_utc()))
    assert session._position is not None
    assert session._position["approved_qty"] == pytest.approx(
        session._position["executable_qty"])  # snapped pre-submit.
    _pquote(engine, 1000, 100.0, 100.2)
    session._drain_engine()
    assert session.ledger.has_position()
    assert session._position["protected"] is True
    assert len(session._position["legs"]) == 2
    return float(session.ledger.position_qty())


def test_paper_stop_exit_settles_sibling_and_clears(tmp_path):
    session, store, engine = _paper_session(tmp_path)
    try:
        qty = _admit_paper(session, engine)
        stop_id, tgt_id = session._position["legs"]
        # Drive through the stop: stop fills in-bracket, target settles.
        for ms, px in ((2000, 99.5), (3000, 98.9), (4000, 98.5)):
            _pquote(engine, ms, px - 0.1, px)
            session._drain_engine()
        stop = _paper_status(engine, stop_id)
        assert stop.state == "filled"
        assert stop.filled_qty == pytest.approx(qty)
        assert _paper_status(engine, tgt_id).state == "cancelled"  # settled.
        assert not session.ledger.has_position()
        assert session._position is None  # released on full agreement.
        assert session.policy._state.reservations == {}
        assert session.policy._state.open_position is False
        assert session.policy.booked_net("r-000001") == 0.0
        fills = [json.loads(r[0]) for r in store._db.execute(
            "SELECT payload FROM execution_events WHERE run_id='ready'"
            " AND kind='fill'").fetchall()]
        assert len(fills) == 2
        assert all(98.4 <= f["price"] <= 100.3 for f in fills)  # in-bracket.
    finally:
        store.close()


def test_paper_target_exit_settles_stop_and_clears(tmp_path):
    session, store, engine = _paper_session(tmp_path)
    try:
        qty = _admit_paper(session, engine)
        stop_id, tgt_id = session._position["legs"]
        for ms, px in ((2000, 101.5), (3000, 102.4), (4000, 102.8)):
            _pquote(engine, ms, px - 0.1, px)
            session._drain_engine()
        tgt = _paper_status(engine, tgt_id)
        assert tgt.state == "filled"
        assert tgt.filled_qty == pytest.approx(qty)
        assert _paper_status(engine, stop_id).state == "cancelled"  # settled.
        assert not session.ledger.has_position()
        assert session._position is None
        assert session.policy._state.reservations == {}
        fills = [json.loads(r[0]) for r in store._db.execute(
            "SELECT payload FROM execution_events WHERE run_id='ready'"
            " AND kind='fill'").fetchall()]
        assert len(fills) == 2
        assert all(99.9 <= f["price"] <= 102.9 for f in fills)  # in-bracket.
    finally:
        store.close()


def test_paper_time_exit_flattens_and_clears(tmp_path):
    session, store, engine = _paper_session(tmp_path)
    try:
        _admit_paper(session, engine)
        assert session.ledger.has_position()
        # Jump past the time exit with no price cross: flatten closes.
        from cryptobot.app.engine import EngineEvent
        session.clock.set_ms(int((_RT0 + timedelta(seconds=601)).timestamp()
                                 * 1000))
        session._update_position(
            EngineEvent("mark", None, session.now_utc()))
        _pquote(engine, 601000, 100.0, 100.2)
        session._drain_engine()
        _pquote(engine, 602000, 100.0, 100.2)
        session._drain_engine()
        assert not session.ledger.has_position()
        assert session._position is None
        assert session.policy._state.reservations == {}
        live = [s for s in engine.open_orders()
                if s.state in ("open", "partial")]
        assert live == []
    finally:
        store.close()


def test_paper_partial_entry_protects_filled_only(tmp_path):
    session, store, engine = _paper_session(tmp_path)
    try:
        _seed_paper_mark(session)
        _pquote(engine, 0, 100.0, 100.2, ask_size=0.050)
        session._maybe_admit(_rintent(session.now_utc()))
        pos = session._position
        approved = pos["approved_qty"]
        assert approved > 0.050
        _pquote(engine, 1000, 100.0, 100.2, ask_size=5.0)
        session._drain_engine()
        filled = session.ledger.position_qty()
        assert 0.0 < filled < approved  # partial at arrival.
        assert pos["protected"] is True
        assert pos["executable_qty"] == pytest.approx(approved)
        entry = _paper_status(engine, pos["entry_id"])
        assert entry.state in ("filled", "cancelled")  # IOC remainder out.
        stop = _paper_status(engine, pos["legs"][0])
        assert stop.state in ("open", "partial")
        assert stop.qty - stop.filled_qty + 1e-9 >= filled
        # Later size never revives the remainder or the legs.
        _pquote(engine, 2000, 100.0, 100.2, ask_size=5.0)
        session._drain_engine()
        assert session.ledger.position_qty() == pytest.approx(filled)
    finally:
        store.close()


def test_resize_on_additional_fills_replaces_pair(tmp_path):
    engine = _ScriptEngine()
    session, store = _session(tmp_path, engine)
    try:
        # Live partial entry: pair covers 0.4, verified.
        session._position = _position(legs=["stop-1"], protected=True)
        session.policy._state.reservations["r-1"] = _reservation(session)
        session.ledger.record_fill("BUY", 0.4, 100.0, 0.02,
                                   session.now_utc(), "f1")
        engine.states = {
            "e": _scripted_status("e", "partial", 1.0, 0.4, "r-1"),
            "stop-1": _scripted_status("stop-1", "open", 0.4, 0.0, "r-1")}
        statuses = {s.client_order_id: s for s in engine.open_orders()}
        session._reverify_protection(session._position, statuses)
        assert session._position["protected"] is True
        # More fills outgrow the pair: unprotect + replace with cover.
        session.ledger.record_fill("BUY", 0.3, 100.0, 0.02,
                                   session.now_utc(), "f2")
        engine.states.update({
            "e": _scripted_status("e", "partial", 1.0, 0.7, "r-1"),
            "stop-2": _scripted_status("stop-2", "open", 0.7, 0.0, "r-1")})
        engine.attach_script = [["stop-2"]]
        statuses = {s.client_order_id: s for s in engine.open_orders()}
        session._reverify_protection(session._position, statuses)
        assert session._position["protected"] is True
        assert session._position["legs"] == ["stop-2"]
        assert session._position["retired"] == ["stop-1"]
        assert "stop-1" in engine.cancelled
    finally:
        store.close()


# --- W3 telemetry: gap causes, milestones, gap counters ------------------

_RT0_MS = int(_RT0.timestamp() * 1000)


def _tev(seq, ts, **kw):
    ev = {"v": 1, "format": "cryptobot-events/1",
          "input_class": "synthetic-test", "source": "synthetic",
          "route": "test", "run_id": "sess", "seq": seq,
          "channel": "aggTrade", "symbol": "BTCUSDT",
          "exchange_ts_ms": ts, "local_recv_ms": ts + 5,
          "local_mono_ns": seq, "gap_kind": None, "venue_seq": seq,
          "payload": {"agg_id": seq, "price": 100.0, "qty": 1.0,
                      "first_id": seq, "last_id": seq,
                      "trade_ts_ms": ts, "buyer_is_maker": False}}
    ev.update(kw)
    return ev


def test_gap_cause_separates_in_quality_reason(tmp_path):
    from cryptobot.app.session import _SymbolFeed
    engine = _ScriptEngine()
    session, store = _session(tmp_path, engine)
    try:
        feed = _SymbolFeed("BTCUSDT", 3)
        feed.bars.extend([None, None])
        feed.missing_cause.extend(["id-jump", "quiet-window"])
        session._feeds["BTCUSDT"] = feed

        class _Stub:
            strategy_id = "S1"

            def evaluate(self, view):
                from types import SimpleNamespace
                _Stub.seen = view.quality_reason
                return SimpleNamespace(reject_reason="t", intent=None)

        session._evaluate_symbol("BTCUSDT", {"S1": _Stub()}, {})
        assert "gap:missing-windows:2" in _Stub.seen
        assert "gap:id-jump:1" in _Stub.seen
        assert "gap:quiet-window:1" in _Stub.seen
    finally:
        store.close()


def test_milestones_and_gap_counters_emitted(tmp_path):
    from cryptobot.app.session import Session
    from cryptobot.app.store import RunStore
    cap = tmp_path / "cap"
    cap.mkdir(parents=True, exist_ok=True)
    events = [_tev(seq, _RT0_MS + seq * 61000) for seq in range(1, 8)]
    (cap / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n")
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    session = Session(_config(tmp_path, warmup_bars=2), store,
                      tmp_path / "runs" / "ms", "ms")
    try:
        report = session.run_replay(cap, expect_class="synthetic-test")
        ms = report["milestones"]
        assert ms["first_event"]["channel"] == "aggTrade"
        assert "BTCUSDT" in ms["first_bar"]
        assert "BTCUSDT" in ms["ready"]
        assert ms["first_eval"], "no strategy eval recorded"
        assert ms["capture_end"]["rel_ms"] >= 0
        assert ms["eligible_s"]["BTCUSDT"] >= 0
        gaps = (session.workdir / "gap_windows.jsonl").read_text().splitlines()
        assert gaps, "no gap counters emitted"
        rows = [json.loads(line) for line in gaps]
        assert all(r["symbol"] == "BTCUSDT" for r in rows)
        assert max(r["window_bars"] for r in rows) == 7  # full lookback.
        assert all(set(r) >= {"ts_utc", "quiet", "id_jump"} for r in rows)
    finally:
        store.close()


# --- W5: malformed ingest fails closed ------------------------------------

@pytest.mark.parametrize("channel,payload", [
    ("aggTrade", None),
    ("aggTrade", {"no_price": 1.0}),
    ("aggTrade", {"price": "abc"}),
    ("bookTicker", None),
    ("bookTicker", {"bid": 1.0}),
    ("bookTicker", {"bid": 1.0, "ask": float("nan")}),
    ("depth", None),
    ("depth", [1, 2]),
    ("markPrice", None),
])
def test_malformed_payload_drops_loudly_never_raises(tmp_path, channel,
                                                     payload):
    engine = _ScriptEngine()
    noted = []
    engine.note_event = noted.append
    session, store = _session(tmp_path, engine)
    try:
        session._ingest({"channel": channel, "symbol": "BTCUSDT",
                         "ts": int(session.clock.now().timestamp() * 1000),
                         "payload": payload}, [], [])
        assert session._position is None
        assert noted == []
        assert session._reject_counts.get("event-malformed-payload") == 1
    finally:
        store.close()
