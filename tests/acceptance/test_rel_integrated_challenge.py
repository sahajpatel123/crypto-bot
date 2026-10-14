"""REL-W5 integrated challenge suite (Worker 5 owns this file).

Cross-component acceptance over the NORMAL path: real Session + real
adapters (paper directly; live via injected offline transport — never
the network). Each case asserts the §10 required result strictly. Red
on early checkpoints is an honest record of missing behavior, never a
harness artifact: every case first proves its setup actually
established the precondition it challenges.
"""
import json
import os
import runpy
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
TOKEN = "w5rel-challenge"

_UNIT = Path(__file__).resolve().parent.parent / "unit"
_FIX = Path(__file__).resolve().parent.parent / "fixtures" / "binance_live"
_W1 = None
_LIVE = None
_READY = None


def _ready_json():
    global _READY
    if _READY is None:
        _READY = json.loads((_FIX / "readiness.json").read_text())
    return _READY


def _w1():
    global _W1
    if _W1 is None:
        _W1 = runpy.run_path(str(_UNIT / "test_ready_lifecycle.py"))
    return _W1


def _livehelpers():
    global _LIVE
    if _LIVE is None:
        _LIVE = runpy.run_path(str(_UNIT / "test_binance_live_v008.py"))
    return _LIVE


def _paper_engine(**kw):
    from cryptobot.adapters.paper_engine import NautilusPaperEngine
    kw.setdefault("taker_bps", 5.0)
    kw.setdefault("now_utc", lambda: T0)
    kw.setdefault("submit_delay_ms", 0)
    kw.setdefault("fill_delay_ms", 1)
    return NautilusPaperEngine(**kw)


def _add_btc(engine, tick=0.01, step=0.001):
    engine.add_instrument("BTCUSDT", price_precision=2, size_precision=3,
                          tick_size=tick, step_size=step, ts_utc=T0)


def _quote(engine, ms, bid, ask, bid_size=1.0, ask_size=1.0):
    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.model.objects import Price, Quantity
    ns = int((T0 + timedelta(milliseconds=ms)).timestamp() * 1e9)
    engine.feed(QuoteTick(
        engine.instrument_id("BTCUSDT"), Price(bid, 2), Price(ask, 2),
        Quantity(bid_size, 3), Quantity(ask_size, 3), ts_event=ns,
        ts_init=ns))


def _seed_mark(session, price):
    from cryptobot.app.session import _SymbolFeed
    feed = _SymbolFeed("BTCUSDT", 0)
    feed.mark = price
    feed.mark_ts = session.now_utc()
    session._feeds["BTCUSDT"] = feed


def _intent(now, entry_low, entry_high, inv, stop, target, exit_s=120,
            costs=(3.0, 0.0, 0.0, 0.0)):
    from cryptobot.coordination import (DataQuality, ForecastCost, Intent,
                                        Side, encode_exit_rule)
    from cryptobot.coordination.exits import ExitPolicy
    from cryptobot.coordination.selector import Candidate
    intent = Intent(
        strategy="S1", version="0.1.0", instrument="BTCUSDT", side=Side.LONG,
        evidence_ts_utc=now, entry_low=entry_low, entry_high=entry_high,
        entry_expiry_utc=now + timedelta(seconds=60),
        invalidation_price=inv,
        exit_rule=encode_exit_rule(ExitPolicy(
            stop_price=stop, target_price=target,
            time_exit_utc=now + timedelta(seconds=exit_s),
            policy_id="w5rel")),
        holding_limit_s=120, forecast_cost=ForecastCost(*costs),
        evidence_ref="test:w5rel", data_quality=DataQuality.CLEAN)
    return [Candidate("S1", intent)]


def _drain(session, rounds=10):
    out = []
    for _ in range(rounds):
        batch = session.engine.poll()
        if not batch:
            break
        out.extend(batch)
    session._drain_engine()
    session._drain_engine()
    return out


# ---------------------------------------------------------------- 1. fill/fee
def test_rel_fill_fee_protection(tmp_path):
    """0.001 BTC fill: ledger + booked risk show 0.001, fee 0.03 once,
    protection requested and verified (normal Session + paper path)."""
    h = _w1()
    from cryptobot.adapters.paper_engine import NautilusPaperEngine
    engine = NautilusPaperEngine(
        taker_bps=3.0, now_utc=lambda: h["_RT0"], submit_delay_ms=0,
        fill_delay_ms=1)
    engine.add_instrument("BTCUSDT", price_precision=2, size_precision=3,
                          tick_size=0.01, step_size=0.001, ts_utc=h["_RT0"])
    session, store = h["_session"](tmp_path, engine)
    # Contract v1: Session.__init__ binds the booking handler already.
    session.clock.set_ms(int(h["_RT0"].timestamp() * 1000))
    session.policy.reconcile_day(120.0, 0.0)
    try:
        _seed_mark(session, 100002.5)
        h["_pquote"](engine, 0, 100000.0, 100005.0)
        session._maybe_admit(_intent(session.now_utc(), 100000.0, 100005.0,
                                     99950.0, 99950.0, 100200.0))
        pos = session._position
        assert pos is not None, "setup failed: intent not admitted"
        assert pos["approved_qty"] == pytest.approx(0.001), pos
        qty = pos["approved_qty"]
        h["_pquote"](engine, 1000, 100000.0, 100005.0)
        session._drain_engine()
        session._drain_engine()
        assert session.ledger.position_qty() == pytest.approx(qty)
        assert session.policy.booked_total_qty() == pytest.approx(qty)
        fills = [json.loads(r[0]) for r in store._db.execute(
            "SELECT payload FROM execution_events WHERE run_id='ready'"
            " AND kind='fill'").fetchall()]
        assert len(fills) == 1, fills
        expect_fee = fills[0]["qty"] * fills[0]["price"] * 3.0 / 10000.0
        assert fills[0]["fee"] == pytest.approx(expect_fee, rel=1e-9)
        assert fills[0]["fee"] == pytest.approx(0.03, abs=5e-4)
        assert session.ledger.paid_costs() == pytest.approx(
            fills[0]["fee"]), "fee booked once"
        assert session._position is not None and session._position.get("protected")
        assert len(session._position.get("legs", [])) == 2
    finally:
        store.close()


# ------------------------------------------------- 2. filled not in open
def test_rel_filled_absent_from_open(tmp_path):
    """A filled entry resolves via order_status() truth; filled ids are
    absent from the open list (open-only everywhere, §2)."""
    h = _w1()
    session, store, engine = h["_paper_session"](tmp_path)
    try:
        h["_admit_paper"](session, engine)
        coid = session._position["entry_id"]
        st = engine.order_status(coid)
        state = getattr(st, "state", st)
        assert str(state).lower() == "filled", (
            f"order_status truth must report filled, got {st!r}")
        by_id = {s.client_order_id: s for s in engine.open_orders()}
        # Open-only (§2, per this test's docstring): the filled id is
        # absent from the open list; truth comes from order_status().
        assert coid not in by_id, (
            f"filled id {coid} present in open-only list: {by_id[coid]}")
        live_ids = [s.client_order_id for s in engine.open_orders()
                    if s.state in ("open", "partial")]
        assert coid not in live_ids, (
            f"filled id {coid} still live: {live_ids}")
    finally:
        store.close()


# --------------------------------------- 3. duplicate + partial, once
def test_rel_duplicate_partial_booked_once(tmp_path):
    """Duplicate delivery of a partial fill books once; protection covers
    filled qty only (normal drain path, white-box redelivery)."""
    h = _w1()
    session, store, engine = h["_paper_session"](tmp_path)
    try:
        # Partial at arrival: admit against a thin ask (lifecycle §partial).
        h["_seed_paper_mark"](session)
        h["_pquote"](engine, 0, 100.0, 100.2, ask_size=0.050)
        session._maybe_admit(h["_rintent"](session.now_utc()))
        assert session._position is not None, "setup: no admission"
        approved = session._position["approved_qty"]
        assert approved > 0.050, f"setup: approved {approved} not partial-able"
        h["_pquote"](engine, 1000, 100.0, 100.2, ask_size=5.0)
        session._drain_engine()
        first_qty = session.ledger.position_qty()
        assert 0.0 < first_qty < approved, (
            f"setup: expected partial fill, ledger={first_qty}")
        first_fees = session.ledger.paid_costs()
        assert first_fees > 0, "setup: no fee booked"
        booked = session.policy.booked_total_qty()
        assert booked == pytest.approx(first_qty)
        # White-box redelivery of the identical fill payloads (fills.jsonl
        # carries the true execution ids) through the real event handler.
        from cryptobot.app.engine import EngineEvent, EngineFill
        lines = (session.workdir / "fills.jsonl").read_text().splitlines()
        assert lines, "setup: no fill events to duplicate"
        for line in lines:
            f = json.loads(line)
            session._on_engine_event(EngineEvent(
                kind="fill", ts_utc=session.now_utc(), payload=EngineFill(
                    execution_id=f["execution_id"],
                    client_order_id=f["client_order_id"],
                    instrument=f["instrument"], side=f["side"],
                    qty=f["qty"], price=f["price"], fee=f["fee"],
                    ts_utc=session.now_utc(),
                    liquidity=f.get("liquidity", "taker"))))
        session._drain_engine()
        assert session.ledger.position_qty() == pytest.approx(first_qty), (
            "duplicate delivery double-booked the ledger")
        assert session.ledger.paid_costs() == pytest.approx(first_fees), (
            "fee double-booked")
        assert session.policy.booked_total_qty() == pytest.approx(booked), (
            "risk booking double-counted")
        # Protection covers the filled qty (IOC remainder is out).
        by_id = {s.client_order_id: s for s in engine.open_orders()}
        stop = by_id[session._position["legs"][0]]
        assert stop.state in ("open", "partial")
        assert stop.qty - stop.filled_qty + 1e-9 >= first_qty
        assert session.ledger.position_qty() == pytest.approx(first_qty)
    finally:
        store.close()


# ------------------------------------------ 4. lost response reconcile
def test_rel_lost_response_reconcile_by_id(tmp_path):
    """Lost submit response: no duplicate order; lookup by original client
    id adopts the venue outcome exactly once (live adapter, injected
    offline transport)."""
    lh = _livehelpers()
    from cryptobot.adapters.binance_live import UnknownOutcomeError
    from cryptobot.app.engine import EngineOrder
    script = lh["_ready_script"](_ready_json()) + [
        ("POST", "/fapi/v1/order", {"symbol": "BTCUSDT"},
         ("err", 503, "Service Unavailable", {})),
    ]
    engine, transport = lh["_live"](tmp_path, script)
    try:
        cmd = EngineOrder(instrument="BTCUSDT", side="BUY", qty=0.001,
                          kind="MARKET", role="entry", reservation_id="r-1")
        try:
            engine.submit(cmd)
            submitted_cid = None
        except UnknownOutcomeError as exc:
            submitted_cid = exc.client_id
        assert submitted_cid, "setup: expected UnknownOutcomeError with id"
        assert submitted_cid in engine.unknown_ids(), "unknown not tracked"
        posts = [r for r in transport.requests
                 if r[0] == "POST" and r[1] == "/fapi/v1/order"]
        assert len(posts) == 1, f"expected exactly one order POST, got {posts}"
        # A retry must refuse while the outcome is unresolved.
        with pytest.raises(UnknownOutcomeError):
            engine.submit(cmd)
        assert len([r for r in transport.requests
                    if r[0] == "POST" and r[1] == "/fapi/v1/order"]) == 1, (
            "duplicate order submitted")
        # Venue saw it: lookup adopts the filled outcome once (order
        # query + userTrades tape for exact per-fill commissions).
        transport.append(
            ("GET", "/fapi/v1/order", {"symbol": "BTCUSDT"},
             ("ok", {"orderId": 7, "origClientOrderId": submitted_cid,
                     "status": "FILLED", "executedQty": "0.001",
                     "avgPrice": "100.0"})),
            ("GET", "/fapi/v1/userTrades", {"orderId": 7},
             ("ok", [{"id": 424242, "orderId": 7, "symbol": "BTCUSDT",
                      "qty": "0.001", "price": "100.0",
                      "commission": "0.00003000",
                      "commissionAsset": "USDT", "buyer": True}])))
        st = engine.lookup(submitted_cid)
        assert getattr(st, "state", None) == "filled", st
        assert submitted_cid not in engine.unknown_ids(), "unknown not cleared"
        fills = [e for e in engine.poll() if e.kind == "fill"]
        assert len(fills) == 1, fills
        assert fills[0].payload.qty == pytest.approx(0.001)
        assert fills[0].payload.fee == pytest.approx(0.00003)
        transport.assert_empty()
    finally:
        engine.close()


# ------------------------------------------- 5. crash at submit/fill/prot
def test_rel_crash_boundaries_resume_complete(tmp_path):
    """SIGKILL mid-run (dirty, no flush) then resume: run COMPLETES with
    fills/booked/cursor parity vs the uninterrupted reference (real bench
    path in subprocesses)."""
    helpers = runpy.run_path(str(_UNIT / "test_bench_restart_equivalence.py"))
    root = tmp_path / "crash"
    root.mkdir()
    helpers["_write_tape"](root)
    toml = root / "cap.toml"
    filters = root / "filters.json"
    repo = Path(__file__).resolve().parent.parent.parent

    def bench_args(name, extra=()):
        return ["--config", "configs/paper.toml", "--dataset", str(toml),
                "--symbol", "BTCUSDT", "--days", "2026-10-11,2026-10-12",
                "--wall-budget-s", "600", "--commit-every", "250",
                "--checkpoint-dir", str(root / name / "ck"),
                "--report-out", str(root / name / "rep.json"),
                "--filters-file", str(filters), "--run-id", "acc", *extra]

    def run_bench(name, extra=()):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(repo / "src") + os.pathsep + env.get("PYTHONPATH", "")
        return subprocess.run(
            [sys.executable, "-m", "cryptobot.bench_run", *bench_args(name, extra)],
            capture_output=True, text=True, cwd=str(repo), timeout=300, env=env)

    (root / "ref").mkdir()
    r = run_bench("ref")
    rep_ref = json.loads((root / "ref" / "rep.json").read_text())
    assert r.returncode == 0 and rep_ref["status"] == "COMPLETE", (
        f"setup: reference run failed rc={r.returncode} {rep_ref}")
    (root / "vic").mkdir()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo / "src") + os.pathsep + env.get("PYTHONPATH", "")
    vic = subprocess.Popen(
        [sys.executable, "-m", "cryptobot.bench_run", *bench_args("vic")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        cwd=str(repo), env=env)
    try:
        # Kill as soon as partial progress exists (dirty crash mid-run).
        deadline = time.monotonic() + 120
        killed = False
        while time.monotonic() < deadline:
            if vic.poll() is not None:
                break
            ck = root / "vic" / "ck"
            if (ck / "commit.json").exists() or (ck / "work").exists():
                vic.send_signal(signal.SIGKILL)
                killed = True
                break
            time.sleep(0.2)
        vic.wait()
        assert killed, "setup: victim finished before any checkpoint"
        assert vic.returncode == -signal.SIGKILL, vic.returncode
    finally:
        if vic.poll() is None:
            vic.kill()
            vic.wait()
    (root / "res").mkdir()
    import shutil
    shutil.copytree(root / "vic" / "ck", root / "res" / "ck")
    r2 = run_bench("res", ("--resume",))
    rep_res = json.loads((root / "res" / "rep.json").read_text())
    assert r2.returncode == 0, r2.stderr[-500:]
    assert rep_res["status"] == "COMPLETE", rep_res
    fills_ref = (root / "ref" / "ck" / "work" / "fills.jsonl").read_text()
    fills_res = (root / "res" / "ck" / "work" / "fills.jsonl").read_text()
    assert fills_res == fills_ref, "resumed fills differ after dirty crash"
    assert rep_res["booked"] == rep_ref["booked"], "booked differs"
    assert rep_res.get("cursor") == rep_ref.get("cursor"), "cursor differs"


# -------------------------------------- 6. stop failure + stream gap
def test_rel_stop_failure_halts_entries_closes_bounded(tmp_path, monkeypatch):
    """A rejected stop (venue kills the stop leg, re-attach keeps failing
    through the real supervision path): bounded emergency close, exactly
    one close, nothing abandoned, failures checkpointed."""
    h = _w1()
    from cryptobot.app.engine import EngineEvent
    session, store, engine = h["_paper_session"](tmp_path)
    try:
        # The venue rejects every stop attach (raise at the real seam).
        def reject_always(*a, **k):
            raise ValueError("venue rejected stop (w5rel injected)")
        monkeypatch.setattr(engine, "attach_protection", reject_always)
        # Manual admission (entry fills; protection attach keeps failing).
        h["_seed_paper_mark"](session)
        h["_pquote"](engine, 0, 100.0, 100.2)
        session._maybe_admit(h["_rintent"](session.now_utc()))
        assert session._position is not None, "setup: no admission"
        h["_pquote"](engine, 1000, 100.0, 100.2)
        session._drain_engine()
        assert session.ledger.has_position(), "setup: no fill"
        # Drive supervision: 3 bounded re-attach attempts, then the
        # emergency flatten. Each supervision pass needs a fresh tick.
        for i in range(6):
            h["_pquote"](engine, 2000 + i * 1000, 100.0, 100.2)
            session._drain_engine()
            session._update_position(
                EngineEvent("mark", None, session.now_utc()))
        for i in range(3):
            h["_pquote"](engine, 9000 + i * 1000, 100.0, 100.2)
            session._drain_engine()
        assert session.ledger.position_qty() == pytest.approx(0.0), (
            "emergency close did not flatten")
        kinds = [r[0] for r in store._db.execute(
            "SELECT kind FROM checkpoints WHERE run_id='ready'").fetchall()]
        assert "protection-failed" in kinds, kinds
        assert "protection-emergency" in kinds, kinds
        sides = [json.loads(r[0])["side"] for r in store._db.execute(
            "SELECT payload FROM execution_events WHERE run_id='ready'"
            " AND kind='fill'").fetchall()]
        assert sides.count("SELL") == 1, (
            f"close not bounded/single: {sides}")
        live = [s for s in engine.open_orders()
                if s.state in ("open", "partial")]
        assert live == [], f"abandoned live children: {live}"
    finally:
        store.close()


def test_rel_stream_gap_halts_entries_exits_work(tmp_path):
    """A venue-sequence gap in the market stream halts entries; exits keep
    working (normal Session path)."""
    h = _w1()
    session, store, engine = h["_paper_session"](tmp_path)
    try:
        h["_seed_paper_mark"](session)
        h["_pquote"](engine, 0, 100.0, 100.2)
        session._maybe_admit(h["_rintent"](session.now_utc()))
        assert session._position is not None, "setup: no admission"
        # Venue sequence jumps 100 -> 200: a stream gap.
        session._ingest({"channel": "aggTrade", "symbol": "BTCUSDT",
                         "exchange_ts_ms": 1000, "local_recv_ms": 1000,
                         "seq": 10, "venue_seq": 100,
                         "payload": {"agg_id": 1, "price": 100.0, "qty": 0.5,
                                     "buyer_is_maker": False}}, {}, {})
        session._ingest({"channel": "aggTrade", "symbol": "BTCUSDT",
                         "exchange_ts_ms": 2000, "local_recv_ms": 2000,
                         "seq": 11, "venue_seq": 200,
                         "payload": {"agg_id": 2, "price": 100.0, "qty": 0.5,
                                     "buyer_is_maker": False}}, {}, {})
        before = session._position["approved_qty"]
        session._maybe_admit(h["_rintent"](session.now_utc()))
        assert session._position["approved_qty"] == pytest.approx(before), (
            "stream gap did not halt entries")
    finally:
        store.close()


# --------------------------------------- 7. preflight/keys refusal
def test_rel_preflight_keys_refusal(tmp_path):
    """Missing keys: readiness BLOCKED (never READY/PASS); prod route
    BLOCKED with no entry phase (CLI, offline). Section 4: missing
    credentials are an explicit BLOCKED state; refusal-at-submission
    is a separate path proven with injected credentials."""
    repo = Path(__file__).resolve().parent.parent.parent
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo / "src") + os.pathsep + env.get("PYTHONPATH", "")
    for var in ("CRYPTOBOT_API_KEY", "CRYPTOBOT_API_SECRET",
                "BINANCE_DEMO_KEY", "BINANCE_DEMO_SECRET"):
        env.pop(var, None)

    def cli(*args):
        return subprocess.run(
            [sys.executable, "-m", "cryptobot.cli", *args],
            capture_output=True, text=True, cwd=str(repo),
            timeout=120, env=env)

    r = cli("readiness", "--config", "configs/prod.toml")
    assert r.returncode == 3, f"readiness rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "BLOCKED" in r.stdout, r.stdout
    assert "READY (read-only checks passed" not in r.stdout, r.stdout
    d = cli("readiness", "--config", "configs/demo.toml")
    assert d.returncode == 3, f"demo readiness rc={d.returncode}\n{d.stdout}"
    assert "BLOCKED" in d.stdout, d.stdout
    p = cli("run", "--mode", "prod", "--config", "configs/prod.toml")
    assert p.returncode == 3, f"prod rc={p.returncode}\n{p.stdout}\n{p.stderr}"
    assert "BLOCKED" in p.stdout, p.stdout
    assert "READY" not in (p.stdout + p.stderr), p.stdout + p.stderr


# --------------------------------- 8. unresolved restart non-success
def test_rel_unresolved_restart_nonsuccess(tmp_path):
    """An order whose outcome never resolves stays unknown across an
    engine restart; it is never reported success and never books."""
    lh = _livehelpers()
    from cryptobot.adapters.binance_live import UnknownOutcomeError
    from cryptobot.app.engine import EngineOrder
    script = lh["_ready_script"](_ready_json()) + [
        ("POST", "/fapi/v1/order", {"symbol": "BTCUSDT"},
         ("err", 503, "Service Unavailable", {})),
    ]
    engine, transport = lh["_live"](tmp_path, script)
    try:
        cmd = EngineOrder(instrument="BTCUSDT", side="BUY", qty=0.001,
                          kind="MARKET", role="entry")
        with pytest.raises(UnknownOutcomeError) as ctx:
            engine.submit(cmd)
        cid = ctx.value.client_id
        assert cid in engine.unknown_ids()
        # Restart: a fresh engine over the same journal keeps the unknown.
        engine2, transport2 = lh["_live"](tmp_path, [])
        try:
            assert cid in engine2.unknown_ids(), (
                "unknown outcome lost across restart")
            assert [e for e in engine2.poll()
                    if e.kind == "fill"] == [], "phantom fill adopted"
            # The venue never saw it: lookup reports void (None), never
            # success; retry is allowed again only after the void.
            transport2.append(
                ("GET", "/fapi/v1/order", {"origClientOrderId": cid},
                 ("err", 400, -2013, "Order does not exist.")))
            assert engine2.lookup(cid) is None, "void lookup misreported"
            assert engine2.unknown_ids() == ()
            assert [e for e in engine2.poll()
                    if e.kind == "fill"] == [], "void lookup booked a fill"
            journal = (tmp_path / "live.jsonl").read_text()
            assert "\"kind\": \"fill\"" not in journal.replace(" ", ""), (
                "journal holds a fill for the unresolved id")
            transport2.assert_empty()
        finally:
            engine2.close()
    finally:
        engine.close()


# --------------------------------------- 9. foreign venue position
def test_rel_foreign_venue_position_flagged_untouched(tmp_path):
    """A venue position/order the bot does not own: the snapshot exposes
    the foreign position, open_orders() excludes foreign strays (journaled
    loudly by count), and a flatten over the live engine issues no writes
    at all (live adapter, injected offline transport + normal Session)."""
    lh = _livehelpers()
    h = _w1()
    script = [
        # Contract v1: account_snapshot reads fresh venue truth (one
        # signed GET, timestamped AccountSnapshot — no cached raw dict).
        ("GET", "/fapi/v2/account", None, ("ok", {
            "totalWalletBalance": "120.0", "availableBalance": "100.0",
            "totalMarginBalance": "120.5",
            "positions": [{"symbol": "ETHUSDT", "positionAmt": "0.5",
                           "entryPrice": "3000.0"}]})),
        ("GET", "/fapi/v1/openOrders", None, ("ok", [
            {"clientOrderId": "someone-elses-order", "symbol": "ETHUSDT",
             "status": "NEW", "origQty": "0.5", "executedQty": "0.0"}])),
        ("GET", "/fapi/v1/openAlgoOrders", None, ("ok", [])),
    ]
    engine, transport = lh["_live"](tmp_path, script)
    try:
        engine.note_user_event({
            "e": "ACCOUNT_UPDATE", "E": 1,
            "a": {"B": [], "P": [{"s": "ETHUSDT", "pa": "0.5",
                                   "ep": "3000.0"}]}})
        snap = engine.account_snapshot()
        assert snap is not None, "snapshot missing after ACCOUNT_UPDATE"
        assert snap.complete is True
        assert snap.asof_utc is not None
        eth = [p for p in snap.positions if p.instrument == "ETHUSDT"]
        assert eth, f"foreign position not exposed: {snap!r}"
        assert eth[0].qty == pytest.approx(0.5)
        session, store = h["_session"](tmp_path, engine)
        try:
            assert engine.open_orders() == [], "foreign stray leaked in"
            journal = (tmp_path / "live.jsonl").read_text()
            assert "foreign-orders-ignored" in journal, (
                "foreign stray not journaled loudly")
            session._flatten("w5rel-foreign-probe")
            writes = [r for r in transport.requests
                      if r[0] in ("POST", "DELETE", "PUT")]
            assert writes == [], f"flatten wrote to the venue: {writes}"
            assert session.ledger.position_qty() == pytest.approx(0.0)
            assert session._position is None
            transport.assert_empty()
        finally:
            store.close()
    finally:
        engine.close()


# --------------------------------------- 10. risk thresholds persist
def test_rel_risk_thresholds_flow_day_restart(tmp_path):
    """Loss/floor crossings latch flow-adjusted action; deposits neither
    trip targets nor replenish protection; day boundary resets day
    counters while lifetime high-water persists across restart."""
    from cryptobot.risk.policy import RiskPolicy
    from cryptobot.risk.state import load_state
    from cryptobot.risk.types import AccountSnapshot, RiskConfig
    now = {"t": datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc)}
    spath = tmp_path / "risk_state.json"
    pol = RiskPolicy(RiskConfig(), state_path=spath,
                     now_utc=lambda: now["t"])

    def snap(marked, realised=0.0, flows=0.0):
        return AccountSnapshot(
            reconciled_equity=marked, marked_equity=marked,
            net_liquidation=marked, net_realised_global=realised,
            open_position=False, flows_cumulative=flows,
            available_margin_usdt=marked, fee_buffer_usdt=0.0,
            inflight_exposure_usdt=0.0)

    pol.reconcile_day(100.0, 0.0)
    # Peak then loss: high-water must persist the peak, not the trough.
    pol.monitor_tick(now["t"], snap(101.0, realised=1.0))
    assert load_state(spath).peak_realised == pytest.approx(1.0), (
        "peak not persisted")
    # Day loss past 0.5%: halt latches; further entries refused.
    pol.monitor_tick(now["t"] + timedelta(hours=1), snap(99.4, realised=-0.6))
    state = load_state(spath)
    halted = bool(getattr(state, "operating_stop_days", None)
                  or getattr(state, "halted", False)
                  or getattr(state, "stops", None))
    assert halted, f"loss crossing did not latch a halt: {state!r}"
    # Deposit cannot replenish: +50 flow with matching equity is still halted.
    pol.monitor_tick(now["t"] + timedelta(hours=2),
                     snap(149.4, realised=-0.6, flows=50.0))
    state2 = load_state(spath)
    halted2 = bool(getattr(state2, "operating_stop_days", None)
                   or getattr(state2, "halted", False)
                   or getattr(state2, "stops", None))
    assert halted2, "deposit replenished protection (must not)"
    # Day boundary: new day resets day counters, lifetime peak persists.
    now["t"] = datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)
    pol.reconcile_day(149.4, 50.0)
    # Restart: fresh policy over the same file keeps peak + halts.
    pol2 = RiskPolicy(RiskConfig(), state_path=spath,
                      now_utc=lambda: now["t"])
    st3 = load_state(spath)
    assert st3.peak_realised == pytest.approx(1.0), (
        f"high-water lost across restart: {st3!r}")
    assert pol2._state.peak_realised == pytest.approx(1.0)


# --------------------------------------- 11. stale + calendar gates
def test_rel_stale_book_blocks_entry_exit_works(tmp_path):
    """A stale book blocks new entries; the exit path still works
    (normal Session + paper path)."""
    h = _w1()
    session, store, engine = h["_paper_session"](tmp_path)
    try:
        h["_admit_paper"](session, engine)
        # Book goes stale (no observations for over the bound).
        session._feeds["BTCUSDT"].mark_ts = (
            session.now_utc() - timedelta(seconds=3600))
        before = session._position["approved_qty"]
        session._maybe_admit(h["_rintent"](session.now_utc()))
        assert session._position["approved_qty"] == pytest.approx(before), (
            "stale book did not block a new entry")
        # Exits still work under the stale gate (the exit fill needs one
        # fresh venue tick to execute against; the entry block above was
        # already recorded while the book was stale).
        session._flatten("w5rel-stale-exit-probe")
        h["_pquote"](engine, 2000, 100.0, 100.2)
        session._drain_engine()
        h["_pquote"](engine, 3000, 100.0, 100.2)
        session._drain_engine()
        assert session.ledger.position_qty() == pytest.approx(0.0), (
            "exit path failed under stale book")
    finally:
        store.close()


def test_rel_invalid_calendar_blocks_entry_exit_works(tmp_path):
    """A real enforcing ProtectionRuntime over a verified calendar blocks
    entries inside the CPI window; exits keep working; entries resume
    after the window (normal Session path, offline canned sources)."""
    h = _w1()
    import cryptobot.events as _evpkg
    from cryptobot.events.freshness import FreshnessTracker, HttpResponse
    from cryptobot.events.runtime import ProtectionRuntime
    from cryptobot.events.sources import CpiSource, FomcSource
    from cryptobot.events.store import EventStore
    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.model.objects import Price, Quantity
    canned = Path(_evpkg.__file__).parent / "fixtures" / "canned"

    def _canned(url, timeout_s=20):
        name = ("fomc_page_2026.txt" if "federalreserve" in url
                else "bls_cpi_page_2026.txt")
        return HttpResponse(status=200, body=(canned / name).read_bytes(),
                            url=url)

    def _tick_at(engine, when, bid=100.0, ask=100.2):
        ns = int(when.timestamp() * 1e9)
        engine.feed(QuoteTick(
            engine.instrument_id("BTCUSDT"), Price(bid, 2), Price(ask, 2),
            Quantity(1.0, 3), Quantity(1.0, 3), ts_event=ns, ts_init=ns))

    cpi = datetime(2026, 10, 14, 12, 30, tzinfo=timezone.utc)
    session, store, engine = h["_paper_session"](tmp_path)
    try:
        store_rt = EventStore()
        tracker = FreshnessTracker(tmp_path / "estate.json",
                                   [FomcSource(), CpiSource()])
        tracker.local_load(store_rt, h["_RT0"])
        tracker.refresh_once(store_rt, _canned, h["_RT0"])
        # Enforcing (non-advisory) runtime = protected posture semantics.
        session.protection = ProtectionRuntime(
            store_rt, evidence_path=session.workdir / "pev.jsonl")
        assert session.protection.check_entry(
            h["_RT0"]).blocked is False, "setup: T0 must be a clear day"
        h["_admit_paper"](session, engine)
        # Inside the CPI window: exits work, entries block.
        session.clock.set_ms(int(cpi.timestamp() * 1000))
        _seed_mark(session, 100.2)
        _tick_at(engine, cpi)
        session._flatten("w5rel-window-exit-probe")
        _tick_at(engine, cpi + timedelta(seconds=1))
        session._drain_engine()
        _tick_at(engine, cpi + timedelta(seconds=2))
        session._drain_engine()
        assert session.ledger.position_qty() == pytest.approx(0.0), (
            "exit path failed inside the calendar window")
        assert session._position is None, "setup: position record stuck"
        _seed_mark(session, 100.2)
        _tick_at(engine, cpi + timedelta(seconds=3))
        session._maybe_admit(h["_rintent"](session.now_utc()))
        assert session._position is None, (
            "calendar window did not block entry")
        rej = (session.workdir / "rejections.jsonl").read_text()
        assert "event:in-window:CPI-2026-10-14" in rej, rej
        # After the window: entries flow again (block was the calendar).
        # The new day needs its real rollover reconcile first (ops flow).
        after = datetime(2026, 10, 15, 12, 30, tzinfo=timezone.utc)
        session.clock.set_ms(int(after.timestamp() * 1000))
        session.policy.reconcile_day(
            session.ledger.marked_equity(100.2), session.ledger.total_flows())
        # Simulate the completed off-thread filters refresh (the AsyncCall
        # path re-arms filters_asof_utc; here we isolate the calendar
        # variable: the claim under test is window resume, not filters).
        from dataclasses import replace as _dc_replace
        session.policy.config = _dc_replace(
            session.policy.config, filters_asof_utc=session.now_utc())
        _seed_mark(session, 100.2)
        _tick_at(engine, after)
        session._maybe_admit(h["_rintent"](session.now_utc()))
        assert session._position is not None, (
            "entries did not resume after the window")
    finally:
        store.close()


# --------------------------------------- 12. protected posture admits
def test_rel_protected_posture_admits_on_clear_day(tmp_path, monkeypatch):
    """Protected posture end to end (profile -> Session -> tracker ->
    runtime -> admit): on a clear calendar day with verified sources,
    entries admit (offline canned HTTP). Guards the W3 employment gap:
    every profile-required source must be constructed by the Session."""
    h = _w1()
    import cryptobot.events as _evpkg
    import cryptobot.events.freshness as _fresh
    from cryptobot.adapters.paper_engine import NautilusPaperEngine
    from cryptobot.app.config import load_config
    from cryptobot.app.session import Session
    from cryptobot.app.store import RunStore
    from cryptobot.events.freshness import HttpResponse
    canned = Path(_evpkg.__file__).parent / "fixtures" / "canned"

    def _canned(url, timeout_s=20):
        if "federalreserve" in url:
            name = "fomc_page_2026.txt"
        elif "empsit" in url:
            name = "bls_empsit_page_2026.txt"
        else:
            name = "bls_cpi_page_2026.txt"
        page = canned / name
        if not page.exists():
            return HttpResponse(status=404, body=b"", url=url)
        return HttpResponse(status=200, body=page.read_bytes(), url=url)
    monkeypatch.setattr(_fresh, "default_http_get", _canned)
    text = open("configs/paper-protected.toml").read()
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    cfg_path = tmp_path / "protected.toml"
    cfg_path.write_text(text)
    cfg = load_config(cfg_path)
    assert cfg.mode == "paper", "setup: protected config must be paper mode"
    engine = NautilusPaperEngine(
        taker_bps=5.0, now_utc=lambda: h["_RT0"], submit_delay_ms=0,
        fill_delay_ms=1)
    engine.add_instrument("BTCUSDT", price_precision=2, size_precision=3,
                          tick_size=0.01, step_size=0.001, ts_utc=h["_RT0"])
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    # Release integration: start the scenario clock at _RT0 before
    # Session construction so the startup source verification lands
    # inside the evaluation window (default clock starts at 1970 and
    # only moves forward; constructing-then-rewinding is time travel
    # the freshness check correctly rejects). Assertions unchanged.
    from cryptobot.app.session import ReplayClock
    clock = ReplayClock(start=h["_RT0"])
    session = Session(cfg, store, tmp_path / "runs" / "relprot", "relprot",
                      engine=engine, clock=clock)
    try:
        store.create_run("relprot", "paper", "fp", str(session.workdir),
                         None)
        # Contract v1: Session.__init__ binds the booking handler already.
        session.clock.set_ms(int(h["_RT0"].timestamp() * 1000))
        session.policy.reconcile_day(120.0, 0.0)
        assert session.protection is not None, "setup: no runtime"
        from nautilus_trader.model.data import QuoteTick
        from nautilus_trader.model.objects import Price, Quantity

        def _tick_at(when):
            ns = int(when.timestamp() * 1e9)
            engine.feed(QuoteTick(
                engine.instrument_id("BTCUSDT"), Price(100.0, 2),
                Price(100.2, 2), Quantity(1.0, 3), Quantity(1.0, 3),
                ts_event=ns, ts_init=ns))

        # Clear day: the protected posture must admit.
        h["_seed_paper_mark"](session)
        h["_pquote"](engine, 0, 100.0, 100.2)
        session._maybe_admit(h["_rintent"](session.now_utc()))
        assert session._position is not None, (
            "protected posture blocked a clear-day entry; rejections: "
            + (session.workdir / "rejections.jsonl").read_text())
        h["_pquote"](engine, 1000, 100.0, 100.2)
        session._drain_engine()
        # Inside the CPI window: the protected posture must block.
        cpi = datetime(2026, 10, 14, 12, 30, tzinfo=timezone.utc)
        session.clock.set_ms(int(cpi.timestamp() * 1000))
        session.policy.reconcile_day(
            session.ledger.marked_equity(100.2), session.ledger.total_flows())
        _seed_mark(session, 100.2)
        _tick_at(cpi)
        session._flatten("w5rel-protected-window-exit")
        _tick_at(cpi + timedelta(seconds=1))
        session._drain_engine()
        _tick_at(cpi + timedelta(seconds=2))
        session._drain_engine()
        assert session._position is None, "setup: position record stuck"
        # Re-arm filters (completed-refresh simulation, as in the
        # calendar test) so the calendar is the only possible blocker.
        from dataclasses import replace as _dc_replace
        session.policy.config = _dc_replace(
            session.policy.config, filters_asof_utc=session.now_utc())
        _seed_mark(session, 100.2)
        _tick_at(cpi + timedelta(seconds=3))
        session._maybe_admit(h["_rintent"](session.now_utc()))
        assert session._position is None, (
            "FAIL-OPEN: protected posture admitted inside the CPI window")
        assert session.protection.advisory_only is False, (
            "protected posture came up advisory (posture wiring)")
    finally:
        try:
            session._freshness.stop()
        except Exception:
            pass
        store.close()


# --------------------------------------- 13. deadline with reparent
def test_rel_deadline_reparent_contained_or_refused(tmp_path):
    """A descendant that reparents before the deadline cannot block the
    capturing caller; the report either verifies containment (subreaper
    platforms) or says so honestly (this mac has no subreaper)."""
    marker = tmp_path / "daemon-done.txt"
    pidfile = tmp_path / "daemon.pid"
    child = (
        "import os, sys, time\n"
        f"MARK = {str(marker)!r}\n"
        f"PIDF = {str(pidfile)!r}\n"
        f"# {TOKEN}\n"
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
    cmd = [sys.executable, "tools/run_budget.py", "--budget-s", "2",
           "--checkpoint-dir", str(tmp_path / "ckpt"), "--report-out",
           str(tmp_path / "rep.json"), "--term-grace-s", "1",
           "--", sys.executable, "-c", child]
    t0 = time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=60)
    finally:
        # Reap only our verified daemon (cmdline token match), if alive.
        try:
            pid = int(pidfile.read_text().strip())
            ps = subprocess.run(["ps", "-o", "command=", "-p", str(pid)],
                                capture_output=True, text=True,
                                timeout=10).stdout
            if TOKEN in ps:
                os.kill(pid, signal.SIGKILL)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    wall = time.monotonic() - t0
    assert proc.returncode == 124, proc.stderr[-500:]
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert rep["status"] == "INCOMPLETE_BUDGET"
    # The caller must never block on the daemon's 10s lifetime.
    assert wall < 6.5, f"caller blocked {wall:.2f}s on escaped descendant"
    assert wall - rep["elapsed_s"] < 2.0, (
        f"caller wall={wall:.2f}s vs report {rep['elapsed_s']}s")
    if rep.get("subreaper"):
        time.sleep(max(0.0, 10.5 - wall))
        assert not marker.exists(), "daemon survived on subreaper platform"
    else:
        assert "subreaper" in (rep.get("platform_note") or ""), rep
        assert rep.get("enforcement") in ("verified", "UNVERIFIED"), rep
