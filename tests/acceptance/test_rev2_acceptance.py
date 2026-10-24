"""REV2 R8 adversarial acceptance through ACTUAL default command paths.

Every case runs the operator path: the real default user-stream thread
(attach_user_stream with TRUE defaults — never start_thread=False or a
sync-poll substitute), a real RunStore, and the normal Session
admission/drain methods. No stub stores, no swallowed-exception
tolerance, no direct ledger calls for booking. Failure cases use fast
offline fault injection (scripted sockets/transports, monkeypatched
boundaries — never the network).

Red at early REV2 SHAs is an honest record of missing behavior: each
case first proves its setup established the precondition it challenges.
"""
import contextlib
import json
import os
import runpy
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tests" / "unit"))


@pytest.fixture(autouse=True)
def _w5rev2_cwd(monkeypatch):
    """Joint-test helpers open repo-relative configs: run this file's
    tests from the repo root whatever the pytest invocation."""
    monkeypatch.chdir(ROOT)

from cryptobot.adapters.user_stream import attach_user_stream  # noqa: E402
from cryptobot.app.engine import EngineOrder  # noqa: E402
from cryptobot.coordination.selector import Candidate  # noqa: E402

_CA = None
_FAKESOCK = None


def _ca():
    global _CA
    if _CA is None:
        _CA = runpy.run_path(str(
            ROOT / "tests" / "unit" / "test_release_checkpoint_a.py"))
    return _CA


def _socket():
    global _FAKESOCK
    if _FAKESOCK is None:
        mod = runpy.run_path(str(
            ROOT / "tests" / "unit" / "test_user_stream_attach.py"))
        _FAKESOCK = mod["FakeSocket"]
    return _FAKESOCK


def _until(fn, timeout_s=20.0, step_s=0.05):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if fn():
            return True
        time.sleep(step_s)
    return bool(fn())


def _halted(engine):
    """Exit-only across halt generations: the legacy boolean and the
    reason-keyed set (callable or attribute)."""
    if getattr(engine, "_exit_only", False):
        return True
    reasons = getattr(engine, "exit_only_reasons",
                      getattr(engine, "_exit_only_reasons", None))
    if callable(reasons):
        try:
            reasons = reasons()
        except TypeError:
            return True
    if reasons is None:
        return False
    if isinstance(reasons, bool):
        return reasons
    try:
        return len(reasons) > 0
    except TypeError:
        return bool(reasons)


def _pump_owner(session):
    """One owner tick: exactly the per-tick owner duties run_live
    performs — drain the attached user stream first (R1 owner
    application), then the engine. Guarded so the pre-fix tree
    (no attachment attribute) still pumps the engine."""
    stream = getattr(session, "_user_stream_attachment", None)
    if stream is not None:
        stream.drain_owner()
    session._drain_engine()


def _until_drained(session, fn, timeout_s=20.0, step_s=0.05,
                   ignore=()):
    """Bounded wait that pumps the NORMAL owner loop: the fixed
    architecture delivers on the thread and books on owner drain.
    Drain errors propagate (never swallowed) except an explicitly
    injected fault class under test."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        with contextlib.suppress(ignore):
            _pump_owner(session)
        if fn():
            return True
        time.sleep(step_s)
    with contextlib.suppress(ignore):
        _pump_owner(session)
    return bool(fn())


def _fills(store, run_id):
    return store._db.execute(
        "SELECT execution_id, payload FROM execution_events"
        " WHERE run_id=? AND kind='fill'", (run_id,)).fetchall()


def _checkpoints(store, run_id):
    return [r[0] for r in store._db.execute(
        "SELECT kind FROM checkpoints WHERE run_id=?",
        (run_id,)).fetchall()]


def _prelude(venues, ready):
    """Joint-test venue prelude, consumed lazily by admission."""
    return [
        ("GET", "/fapi/v2/account", None, ("ok", ready["account"])),
        ("GET", "/fapi/v1/openOrders", None, ("ok", [])),
        ("GET", "/fapi/v1/openAlgoOrders", None, ("ok", [])),
    ] + venues.ready_script(ready)


def _live_pair(tmp_path, run_id="rev2", prelude=True):
    """Live engine + Session over REAL RunStore (joint-test prelude)."""
    import venue_fixtures as venues
    ca = _ca()
    ready, orders = venues.ready_fixture(), venues.orders_fixture()
    script = _prelude(venues, ready) if prelude else []
    engine, transport = venues.make_engine(tmp_path, script)
    session, store = ca["_session"](tmp_path, engine, run_id)
    return ca, venues, ready, orders, engine, transport, session, store


def _reopen(ca, tmp_path, engine, run_id):
    """Reopen an EXISTING run after a crash: the joint-test _session
    construction minus create_run — the run row survived the crash,
    so recreating it would be the harness's bug, not the test."""
    cfg = ca["load_config"](ca["_config"](tmp_path))
    store = ca["RunStore"](tmp_path / "runs" / "cryptobot.db")
    session = ca["Session"](cfg, store, tmp_path / "runs" / run_id,
                            run_id, engine=engine)
    now = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
    session.clock.set_ms(int(now.timestamp() * 1000))
    session.policy.reconcile_day(120.0, 0.0)
    session.arm_replay_filters(
        {"BTCUSDT": {"tick_size": 0.10, "step_size": 0.001,
                     "min_qty": 0.001, "min_notional": 5.0}},
        origin=ca["MECHANICS"], asof_utc=now)
    from cryptobot.app.session import _SymbolFeed
    feed = _SymbolFeed("BTCUSDT", 0)
    feed.mark = 100.0
    feed.mark_ts = now
    session._feeds["BTCUSDT"] = feed
    return session, store


def _admit_limit(ca, orders, engine, transport, session, store):
    """Admit one LIMIT intent through the NORMAL Session path."""
    transport.append(
        ("POST", "/fapi/v1/order", {"type": "LIMIT"},
         ("ok", orders["orderAck"])))
    session._maybe_admit([Candidate("S1", ca["_intent"](session.now_utc()))])
    assert session._position is not None, "setup: intent not admitted"
    qty = ca["_submitted_qty"](transport)
    assert qty > 0, "setup: no entry submitted"
    return session._position["entry_pre_id"], qty


def _trade(orders, entry_cid, qty, price="100.50"):
    import copy
    stream = copy.deepcopy(orders["userStreamTrade"])
    stream["o"]["c"] = entry_cid
    stream["o"]["l"] = stream["o"]["z"] = f"{qty:.3f}"
    stream["o"]["L"] = stream["o"]["ap"] = price
    return stream


def _algo_scripts(transport, entry, qty=None, trade_id=None):
    # Connect order: listen-key, reconnect lookup of the live entry
    # (still NEW — the stream fill has not arrived), then the fill's
    # own push dialogue (entry-truth lookup + tape for the protection
    # attach), then protection.
    transport.append(
        ("POST", "/fapi/v1/listenKey", None, ("ok", {"listenKey": "K"})),
        ("GET", "/fapi/v1/order", {"origClientOrderId": entry},
         ("ok", {"orderId": 5, "origClientOrderId": entry,
                 "status": "NEW", "executedQty": "0.0",
                 "avgPrice": "0.0"})))
    if qty is not None:
        transport.append(
            ("GET", "/fapi/v1/order", None,
             ("ok", {"orderId": 7, "status": "FILLED",
                     "executedQty": f"{qty:.3f}",
                     "avgPrice": "100.50"})),
            ("GET", "/fapi/v1/userTrades", {"orderId": 7},
             ("ok", [{"id": trade_id, "orderId": 7,
                      "symbol": "BTCUSDT", "qty": f"{qty:.3f}",
                      "price": "100.50", "commission": "0.03000000",
                      "commissionAsset": "USDT", "buyer": True}])))
    transport.append(
        ("POST", "/fapi/v1/algoOrder", {"reduceOnly": "true"},
         ("ok", {"algoId": 11, "algoStatus": "WORKING"})),
        ("POST", "/fapi/v1/algoOrder", {"reduceOnly": "true"},
         ("ok", {"algoId": 12, "algoStatus": "WORKING"})),
        ("GET", "/fapi/v1/openOrders", None, ("ok", [])),
        ("GET", "/fapi/v1/openAlgoOrders", None, ("ok", [])))


# --------------------------------------- 1. thread fill books+protects
def test_rev2_thread_fill_books_and_protects(tmp_path):
    """Default-thread user-stream fill: exactly one durable booking,
    ledger position, verified 2-leg protection, zero thread errors."""
    ca, venues, ready, orders, engine, transport, session, store = _live_pair(
        tmp_path)
    att = None
    try:
        entry, qty = _admit_limit(ca, orders, engine, transport, session,
                                  store)
        trade = _trade(orders, entry, qty)
        _algo_scripts(transport, entry, qty, trade["o"]["t"])
        # ACTUAL DEFAULT command path: default thread, real store.
        att = attach_user_stream(session, engine,
                                 lambda url: _socket()([trade]))
        assert _until_drained(session, lambda: len(_fills(store, "rev2")) == 1), (
            "thread fill never durably booked")
        assert session.ledger.has_position(), "ledger missing position"
        assert session.policy.booked_total_qty() == pytest.approx(qty)
        assert _until_drained(session, lambda: session._position.get("protected") is True), (
            "protection never attached")
        assert len(session._position.get("legs", [])) == 2
        algos = [r for r in transport.requests
                 if r[1] == "/fapi/v1/algoOrder"]
        assert len(algos) == 2, f"protection posts: {algos}"
        assert att.errors == 0, "thread callback errors swallowed"
        assert _fills(store, "rev2")[0][0], "missing execution id"
    finally:
        if att is not None:
            att.close()
        store.close()


# --------------------------------------- 2. thread duplicate books once
def test_rev2_thread_duplicate_books_once(tmp_path):
    """Same stream event twice through the default thread: booked once,
    no duplicate venue protection, ledger qty exactly once."""
    ca, venues, ready, orders, engine, transport, session, store = _live_pair(
        tmp_path)
    att = None
    try:
        entry, qty = _admit_limit(ca, orders, engine, transport, session,
                                  store)
        trade = _trade(orders, entry, qty)
        _algo_scripts(transport, entry, qty, trade["o"]["t"])
        att = attach_user_stream(
            session, engine, lambda url: _socket()([trade, trade]))
        assert _until_drained(session, lambda: len(_fills(store, "rev2")) == 1), (
            "setup: first delivery never booked")
        # Let the duplicate arrive + settle through the owner loop.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            _pump_owner(session)
            time.sleep(0.05)
        _pump_owner(session)
        rows = _fills(store, "rev2")
        assert len(rows) == 1, f"duplicate booked: {len(rows)} rows"
        assert session.ledger.position_qty() == pytest.approx(qty)
        assert session.policy.booked_total_qty() == pytest.approx(qty)
        algos = [r for r in transport.requests
                 if r[1] == "/fapi/v1/algoOrder"]
        assert len(algos) == 2, f"duplicate re-attached: {algos}"
        assert att.errors == 0
    finally:
        if att is not None:
            att.close()
        store.close()


# --------------------------------------- 3. booking failure halts+keeps
def test_rev2_booking_failure_halts_entries_keeps_exits(tmp_path,
                                                        monkeypatch):
    """Injected durable-booking failure on the thread path: new entries
    halt with a recorded reason (never silent), exits stay available,
    error evidence is kept."""
    ca, venues, ready, orders, engine, transport, session, store = _live_pair(
        tmp_path)
    att = None
    try:
        entry, qty = _admit_limit(ca, orders, engine, transport, session,
                                  store)
        real_record = store.record_event

        def fail_fill(run_id, execution_id, kind, payload, ts_utc=None):
            if kind == "fill":
                raise RuntimeError("w5rev2 injected booking failure")
            return real_record(run_id, execution_id, kind, payload,
                               ts_utc=ts_utc)
        trade = _trade(orders, entry, qty)
        # Minimal dialogue: the booking fault trips the fill's push
        # BEFORE position sync, so the fill-pair/algos are never
        # consumed — scripting them would strand the exit probe.
        transport.append(
            ("POST", "/fapi/v1/listenKey", None,
             ("ok", {"listenKey": "K"})),
            ("GET", "/fapi/v1/order", {"origClientOrderId": entry},
             ("ok", {"orderId": 5, "origClientOrderId": entry,
                     "status": "NEW", "executedQty": "0.0",
                     "avgPrice": "0.0"})))
        # The fill is delivered only AFTER the heal is proven and the
        # booking fault armed: appending to the live socket script is
        # the deterministic injection point (no race with heal).
        box = {}

        def factory(url):
            sock = _socket()([None])
            box["sock"] = sock
            return sock

        att = attach_user_stream(session, engine, factory)
        assert _until_drained(session, lambda: not att.halted,
                                timeout_s=20.0), (
            "setup: stream never healed")
        assert not _halted(engine), "setup: still halted after heal"
        monkeypatch.setattr(store, "record_event", fail_fill)
        box["sock"].script.append(trade)
        # Adapter-side adoption proves the fill ARRIVED (thread-safe).
        assert _until_drained(
            session,
            lambda: engine._adopted_qty.get(entry, 0.0) > 0,
            timeout_s=20.0), "setup: fill never arrived"
        # Entries must halt: the failure is visible, never swallowed.
        # (The injected RuntimeError surfacing through drain is the
        # fault under test, not harness noise.)
        assert _until_drained(session, lambda: _halted(engine),
                              timeout_s=20.0, ignore=(RuntimeError,)), (
            "booking failure did not halt entries")
        kinds = _checkpoints(store, "rev2")
        assert "user-stream-apply-failed" in kinds, (
            f"no apply-failure checkpoint: {sorted(kinds)}")
        assert att.pending_failures(), (
            "apply failure not kept as evidence")
        reasons = engine.exit_only_reasons()
        assert any("user-stream" in r for r in reasons), (
            f"halt reason does not name the stream: {reasons}")
        # New admission must refuse while halted (behavioral).
        before = session._position["entry_pre_id"]
        session._maybe_admit(
            [Candidate("S1", ca["_intent"](session.now_utc()))])
        assert session._position["entry_pre_id"] == before, (
            "admitted while booking-halted")
        # Exits stay available: exit submit accepted, entry refused.
        transport.append(
            ("POST", "/fapi/v1/order", {"reduceOnly": "true"},
             ("ok", {"orderId": 9001,
                     "origClientOrderId": "w5rev2-exit-probe",
                     "status": "NEW", "executedQty": "0.0",
                     "avgPrice": "0.0"})))
        engine.submit(EngineOrder(
            instrument="BTCUSDT", side="SELL", qty=qty, kind="MARKET",
            role="target", reservation_id="r-exit-ok",
            reduce_only=True))
        with pytest.raises(ValueError, match="exit-only"):
            engine.submit(EngineOrder(
                instrument="BTCUSDT", side="BUY", qty=qty, kind="MARKET",
                role="entry", reservation_id="r-entry-no"))
    finally:
        if att is not None:
            att.close()
        store.close()


# --------------------------------------- 4. disconnect then recovery
def test_rev2_disconnect_recovery_heals(tmp_path):
    """Socket death halts entries with a gap checkpoint; a fresh socket
    heals through the SAME default attachment; entries resume."""
    ca, venues, ready, orders, engine, transport, session, store = _live_pair(
        tmp_path, run_id="rev2gap", prelude=False)
    att = None
    sockets = [_socket()(["die"]), _socket()([None])]

    def factory(url):
        assert sockets, "reconnect beyond scripted sockets"
        return sockets.pop(0)
    try:
        transport.append(
            ("POST", "/fapi/v1/listenKey", None,
             ("ok", {"listenKey": "K"})))
        att = attach_user_stream(session, engine, factory)
        assert _until_drained(session, lambda: _halted(engine),
                                timeout_s=20.0), (
            "disconnect did not halt entries")
        assert "user-stream-gap" in _checkpoints(store, "rev2gap")
        assert _until_drained(session, lambda: not _halted(engine)
                                and not att.halted, timeout_s=30.0), (
            "reconnect did not heal")
        assert "user-stream-healed" in _checkpoints(store, "rev2gap")
        # Entries genuinely resume: a real admission works.
        transport.append(*_prelude(venues, ready))
        _admit_limit(ca, orders, engine, transport, session, store)
        assert att.errors == 1, (
            f"injected death counted {att.errors}x, want exactly once")
        assert getattr(att, "fatal_error", None) is None, (
            "pump died instead of reporting")
    finally:
        if att is not None:
            att.close()
        store.close()


# --------------------------------------- 5. halt independence
def test_rev2_halt_independence(tmp_path):
    """Healing the stream clears ONLY the stream reason: a standing
    operator halt still refuses admission afterwards (behavioral)."""
    ca, venues, ready, orders, engine, transport, session, store = _live_pair(
        tmp_path, run_id="rev2halt", prelude=False)
    att = None
    sockets = [_socket()(["die"]), _socket()([None])]

    def factory(url):
        assert sockets, "reconnect beyond scripted sockets"
        return sockets.pop(0)
    try:
        transport.append(
            ("POST", "/fapi/v1/listenKey", None,
             ("ok", {"listenKey": "K"})))
        # Standing operator halt, set before the stream episode.
        engine.set_exit_only(True, "halt:operator-stop")
        att = attach_user_stream(session, engine, factory)
        assert _until_drained(session, lambda: att.halted,
                                timeout_s=20.0), (
            "setup: stream gap halt never engaged")
        assert _until_drained(session, lambda: not att.halted,
                                timeout_s=30.0), (
            "setup: stream never healed")
        assert "user-stream-healed" in _checkpoints(store, "rev2halt")
        assert att.errors == 1, (
            f"injected death counted {att.errors}x, want exactly once")
        # The operator reason must persist: admission still refuses.
        transport.append(*_prelude(venues, ready))
        session._maybe_admit(
            [Candidate("S1", ca["_intent"](session.now_utc()))])
        assert session._position is None, (
            "heal cleared the standing operator halt (last-writer-wins)")
        assert _halted(engine), "engine exit-only cleared by heal"
    finally:
        if att is not None:
            att.close()
        store.close()


# --------------------------------------- 6. restart with exposure
def test_rev2_restart_with_exposure_adopts_once(tmp_path):
    """Crash after a thread-booked fill: restart re-adopts the exposure
    by order truth, redelivery books nothing twice, nothing resubmits."""
    ca, venues, ready, orders, engine, transport, session, store = _live_pair(
        tmp_path, run_id="rev2restart")
    att = None
    try:
        entry, qty = _admit_limit(ca, orders, engine, transport, session,
                                  store)
        trade = _trade(orders, entry, qty)
        _algo_scripts(transport, entry, qty, trade["o"]["t"])
        att = attach_user_stream(session, engine,
                                 lambda url: _socket()([trade]))
        assert _until_drained(
            session, lambda: len(_fills(store, "rev2restart")) == 1), (
            "setup: thread fill never booked")
        assert session.ledger.position_qty() == pytest.approx(qty)
        legs = list(session._position.get("legs", []))
        assert len(legs) == 2, "setup: protection legs missing"
        att.close()
        att = None
        store.close()
        # Dirty restart: fresh engine over the SAME journal, fresh
        # Session over the SAME RunStore file, same run id — then the
        # REAL operator resume (what run_live(resume=True) runs).
        engine2, transport2 = venues.make_engine(tmp_path, [])
        ca2 = _ca()
        session2, store2 = _reopen(ca2, tmp_path, engine2,
                                   "rev2restart")
        try:
            # Recovery dialogue: the entry is terminal in the journal
            # (no revisit); each open leg re-resolves on the algo rail.
            for i, leg in enumerate(legs):
                transport2.append(
                    ("GET", "/fapi/v1/algoOrder",
                     {"origClientAlgoId": leg},
                     ("ok", {"algoId": 11 + i, "algoStatus": "WORKING",
                             "origClientAlgoId": leg,
                             "executedQty": "0.0"})))
            session2._resume_live()
            session2._drain_engine()
            session2._drain_engine()
            assert session2.ledger.position_qty() == pytest.approx(qty), (
                "restart did not re-adopt the exposure")
            assert len(_fills(store2, "rev2restart")) == 1, (
                "restart duplicated the booking")
            posts = [r for r in transport2.requests
                     if r[0] == "POST"]
            assert posts == [], f"restart resubmitted: {posts}"
        finally:
            store2.close()
    finally:
        if att is not None:
            att.close()
        with contextlib.suppress(Exception):
            store.close()


def _scrub_env(monkeypatch):
    for var in ("CRYPTOBOT_API_KEY", "CRYPTOBOT_API_SECRET",
                "BINANCE_DEMO_KEY", "BINANCE_DEMO_SECRET"):
        monkeypatch.delenv(var, raising=False)


def _drill_mod():
    import tools.audit.demo_drill as demo_drill
    return demo_drill


# --------------------------------------- 7. demo full without keys
def test_rev2_demo_full_without_keys_blocked(tmp_path, monkeypatch):
    """EXACT documented command, no credentials: the drill exits
    nonzero and its final verdict is not PASS (never 0/PASS with
    BLOCKED phases)."""
    _scrub_env(monkeypatch)
    env = {k: v for k, v in os.environ.items()
           if k not in ("CRYPTOBOT_API_KEY", "CRYPTOBOT_API_SECRET",
                        "BINANCE_DEMO_KEY", "BINANCE_DEMO_SECRET")}
    run_dir = tmp_path / "drill"
    proc = subprocess.run(
        [sys.executable, "tools/audit/demo_drill.py", "--dir", str(run_dir),
         "--symbol", "BTCUSDT", "full"],
        cwd=str(ROOT), env=env, capture_output=True, text=True,
        timeout=180)
    assert proc.returncode != 0, (
        f"full drill exited 0 without credentials:\n{proc.stdout}")
    final = [json.loads(line) for line in
             (run_dir / "drill_evidence.jsonl").read_text().splitlines()]
    assert final, "setup: no drill phases recorded"
    assert final[-1]["verdict"] != "PASS", (
        f"full drill PASSED without credentials: {final[-1]}")
    assert any(p.get("verdict") == "BLOCKED" for p in final), (
        "no BLOCKED phase recorded")


# --------------------------------------- 8. preflight failure stops drill
def test_rev2_demo_preflight_failure_prevents_entry(tmp_path, monkeypatch):
    """The REAL full command path with an injected preflight failure:
    the entry phase never executes and the drill exits nonzero."""
    demo_drill = _drill_mod()
    called = []
    monkeypatch.setattr(
        demo_drill, "cmd_preflight",
        lambda drill: (drill.log("preflight", "FAIL",
                                 "w5rev2 injected"), 1)[1])

    def record_drill(drill):
        called.append("drill")
        return 0
    monkeypatch.setattr(demo_drill, "cmd_drill", record_drill)
    rc = demo_drill.main(["--dir", str(tmp_path / "drill"),
                          "--symbol", "BTCUSDT", "full"])
    assert rc != 0, "full drill exited 0 after preflight failure"
    assert called == [], (
        f"entry phase executed after preflight failure: {called}")
    phases = [json.loads(line)["phase"] for line in
              (tmp_path / "drill" / "drill_evidence.jsonl").read_text(
              ).splitlines()]
    assert "preflight" in phases, f"setup: {phases}"


# --------------------------------------- 9. no pass with blocked/omitted leg
def test_rev2_demo_no_pass_with_blocked_or_omitted_leg(tmp_path,
                                                       monkeypatch):
    """The REAL full command: a BLOCKED leg forces a nonzero exit and a
    non-PASS verdict, and the executed legs include resume-adopt."""
    demo_drill = _drill_mod()
    monkeypatch.setattr(
        demo_drill, "cmd_drill",
        lambda drill: (drill.log("drill", "BLOCKED",
                                 "w5rev2 injected"), 2)[1])
    rc = demo_drill.main(["--dir", str(tmp_path / "drill"),
                          "--symbol", "BTCUSDT", "full"])
    assert rc != 0, "full drill exited 0 with a BLOCKED leg"
    recs = [json.loads(line) for line in
            (tmp_path / "drill" / "drill_evidence.jsonl").read_text().splitlines()]
    assert recs[-1]["verdict"] != "PASS", (
        f"full drill PASSED with a BLOCKED leg: {recs[-1]}")
    phases = [r["phase"] for r in recs]
    assert "resume-adopt" in phases, (
        f"full omits the resume-adopt leg: {phases}")


# --------------------------------------- 10. flat needs full agreement
def test_rev2_demo_flat_requires_full_agreement(tmp_path, monkeypatch):
    """Reconcile reports flat ONLY after venue positions, orders,
    journal and ledger agree: a foreign venue exposure fails it."""
    import venue_fixtures as venues
    demo_drill = _drill_mod()
    monkeypatch.setenv("BINANCE_DEMO_KEY", "k")
    monkeypatch.setenv("BINANCE_DEMO_SECRET", "s")
    drill = demo_drill.Drill(str(tmp_path / "drill"), "BTCUSDT", None)
    # Session-driven read order: account snapshot first, then the
    # open-order rails. The account read carries the foreign exposure
    # the fixed reconcile must consult.
    script = [
        ("GET", "/fapi/v2/account", None, ("ok", {
            "totalWalletBalance": "120.0", "availableBalance": "100.0",
            "totalMarginBalance": "115.0",
            "positions": [
                {"symbol": "ETHUSDT", "positionAmt": "0.5",
                 "entryPrice": "3000.0", "markPrice": "3010.0"},
                {"symbol": "BTCUSDT", "positionAmt": "0.0",
                 "entryPrice": "0.0", "markPrice": "100.0"}]})),
        ("GET", "/fapi/v1/openOrders", None, ("ok", [])),
        ("GET", "/fapi/v1/openAlgoOrders", None, ("ok", [])),
    ]
    transport = venues.ReplayTransport(script)
    real_engine = drill.engine
    drill.engine = lambda *a, **k: real_engine(transport)
    rc = demo_drill.cmd_reconcile(drill)
    assert rc != 0, (
        "reconcile PASSED with a foreign venue exposure (no "
        "positions/ledger agreement check)")
    recs = [json.loads(line) for line in
            (tmp_path / "drill" / "drill_evidence.jsonl").read_text(
            ).splitlines()]
    venue = [r for r in recs
             if r["phase"] == "reconcile/venue-positions"]
    assert venue and venue[0]["verdict"] == "FAIL", (
        f"venue-positions leg did not FAIL on the exposure: {venue}")
    assert "ETHUSDT" in venue[0]["detail"], (
        f"FAIL detail does not name the exposure: {venue[0]}")


def _crafted_row(ev_ms, evaluated_ms):
    """Real candidate-row schema (review probe): evidence time decides
    the touch search, evaluated_now_utc is the decision instant."""
    return {"evidence_ref": "crafted", "strategy": "S1", "side": "LONG",
            "instrument": "BTCUSDT", "_ev_ms": ev_ms,
            "evidence_ts_utc": _iso(ev_ms),
            "evaluated_now_utc": _iso(evaluated_ms),
            "_dec_ms": evaluated_ms,
            "entry_expiry_utc": _iso(10000), "entry_low": 99.0,
            "entry_high": 100.2, "stop_price": 99.0,
            "target_price": 102.0, "time_exit_utc": _iso(4000)}


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000,
                                  tz=UTC).isoformat()


# --------------------------------------- 11. causality: decision order
def test_rev2_causality_fill_never_before_decision(tmp_path, monkeypatch):
    """Crafted tape through the REAL scorer: a fill timestamped before
    its decision is unscorable (never scored), and a stop exit prices
    at the executable exit-side quote, never the trigger print."""
    from unittest.mock import patch

    import tools.hr2_diagnostic as hr2
    # Defect case (review §4.6): evidence 01.0, decision 02.5.
    tape = ([(1000, 99.9, 100.0, 1, 1), (2500, 100.9, 101.0, 1, 1)],
            [(1500, 1, 99.0, 1), (4500, 2, 101.0, 1)],
            [(1000, 100.0, None, 99999999)])
    row = _crafted_row(1000, 2500)
    with patch.object(hr2, "_load_window", return_value=tape):
        bad = hr2.evaluate_one(row)
    assert not (bad["entry"] == "filled"
                and bad["fill_ts_utc"] < row["evaluated_now_utc"]), (
        f"fill scored before its decision: {bad['entry']} "
        f"{bad.get('fill_ts_utc')} vs decision "
        f"{row['evaluated_now_utc']}")
    # Positive control: decision (00.5) at/before fill (01.0) scores;
    # stop trigger print 99.0 but exit-side bid is 98.5 after trigger.
    tape_ok = ([(500, 99.9, 100.0, 1, 1), (1000, 99.9, 100.0, 1, 1),
                (1500, 98.4, 98.6, 1, 1), (1600, 98.5, 98.7, 1, 1)],
               [(1500, 9, 99.0, 1)],
               [(1000, 100.0, None, 99999999), (31000, 99.9, None, 99999999), (61000, 99.9, None, 99999999),
                (121000, 99.9, None, 99999999), (301000, 99.9, None, 99999999)])
    with patch.object(hr2, "_load_window", return_value=tape_ok):
        good = hr2.evaluate_one(_crafted_row(500, 500))
    assert good["entry"] == "filled", (
        f"setup: causal row did not score: {good['entry']}")
    assert good["exit"] == "stop", f"setup: {good['exit']}"
    assert good["exit_price"] == pytest.approx(98.5), (
        f"stop exit used trigger print, not executable bid: {good}")


# --------------------------------------- 12. causality: horizon coverage
def test_rev2_causality_unsupported_horizons_unscorable(tmp_path,
                                                        monkeypatch):
    """Crafted tape through the REAL scorer: markout horizons past mark
    coverage are unscorable, never carried-forward marks."""
    from unittest.mock import patch

    import tools.hr2_diagnostic as hr2
    # Marks end at +60s; horizons 120/300 have no coverage. Books
    # and prints near the 30/60s marks keep those horizons covered.
    tape = ([(500, 99.9, 100.0, 1, 1), (1000, 99.9, 100.0, 1, 1),
             (1500, 102.4, 102.6, 1, 1), (1600, 102.5, 102.7, 1, 1),
             (30000, 100.0, 100.2, 1, 1), (60000, 100.1, 100.3, 1, 1)],
            [(1500, 9, 102.5, 1), (30000, 10, 100.1, 1),
             (60000, 11, 100.2, 1)],
            [(1000, 100.0, None, 99999999), (31000, 100.1, None, 99999999), (61000, 100.2, None, 99999999)])
    with patch.object(hr2, "_load_window", return_value=tape):
        got = hr2.evaluate_one(_crafted_row(500, 500))
    assert got["entry"] == "filled", (
        f"setup: causal row did not score: {got['entry']}")
    marks = got["markouts_bps"]
    assert isinstance(marks["30"], (int, float)), "setup broken"
    for horizon in ("120", "300"):
        val = marks[horizon]
        assert isinstance(val, str) and val.startswith("unscorable"), (
            f"horizon {horizon} carried a stale mark forward: {val}")


# --------------------------------------- 13. deadline: fix or refuse
def test_rev2_deadline_descendant_fix_or_refuse(tmp_path):
    """Deployment-target reparent proof with born verification: on a
    subreaper platform the daemon MUST be born, containment MUST verify
    and no marker may exist; elsewhere the report must refuse
    (UNVERIFIED + explicit note). No weakened assertions."""
    token = "w5rev2-challenge"
    marker = tmp_path / "daemon-done.txt"
    pidfile = tmp_path / "daemon.pid"
    child = (
        "import os, sys, time\n"
        f"MARK = {str(marker)!r}\n"
        f"PIDF = {str(pidfile)!r}\n"
        f"# {token}\n"
        "mid = os.fork()\n"
        "if mid > 0:\n"
        "    time.sleep(60)\n"
        "    sys.exit(0)\n"
        "os.setsid()\n"
        "d = os.fork()\n"
        "if d > 0:\n"
        "    os._exit(0)\n"
        "open(PIDF, 'w').write(str(os.getpid()))\n"
        "time.sleep(10)\n"
        "open(MARK, 'w').write('daemon-survived')\n"
    )
    # Enforce-or-refuse contract: strict (default) refuses outright on
    # hosts without a verified subreaper+scan. This test explicitly opts
    # into best-effort to prove the legacy containment semantics below.
    cmd = [sys.executable, "tools/run_budget.py", "--allow-best-effort",
           "--budget-s", "2",
           "--checkpoint-dir", str(tmp_path / "ckpt"), "--report-out",
           str(tmp_path / "rep.json"), "--term-grace-s", "1",
           "--", sys.executable, "-c", child]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                          cwd=str(ROOT))
    try:
        assert proc.returncode == 124, (
            f"rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}")
        rep = json.loads((tmp_path / "rep.json").read_text())
        assert rep["status"] == "INCOMPLETE_BUDGET", rep
        assert rep["elapsed_s"] == pytest.approx(3.0, abs=2.5), rep
        # Born verification: the scenario genuinely challenged
        # containment (a never-born daemon would be a vacuous pass).
        assert pidfile.exists(), (
            "setup: daemon never born; containment unchallenged")
        if rep.get("subreaper"):
            time.sleep(10.5)
            assert rep.get("enforcement") == "verified", rep
            assert not marker.exists(), (
                "daemon survived on a subreaper platform")
        else:
            # Enforce-or-refuse contract: strict mode would refuse this
            # host outright (exit 125, child never spawned); under the
            # explicit --allow-best-effort opt-in above, the report must
            # still disclose the subreaper gap explicitly.
            assert "subreaper" in (rep.get("platform_note") or ""), rep
            assert rep.get("enforcement") in ("verified",
                                              "UNVERIFIED"), rep
    finally:
        try:
            pid = int(pidfile.read_text().strip())
        except (OSError, ValueError):
            pid = None
        if pid is not None:
            try:
                ps = subprocess.run(
                    ["ps", "-o", "command=", "-p", str(pid)],
                    capture_output=True, text=True, timeout=10).stdout
                if token in ps:
                    os.kill(pid, signal.SIGKILL)
            except (OSError, subprocess.SubprocessError):
                pass
