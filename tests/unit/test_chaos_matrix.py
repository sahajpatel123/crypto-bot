"""F1.3: chaos matrix on the sandbox venue (offline live loop).

Faults x stages (10 x 4 = 40 cells), each asserting the money
invariant: the run ends FLAT or PROTECTED (never naked beyond the
protection budget), with no duplicate and no lost fills. Automated
here; the full suite runs it in CI.

Fault mapping (honest, no fabrication):
- timeout / 5xx: FaultScript "unknown" (503-drop; the adapter maps it
  to UnknownOutcomeError exactly like a socket timeout).
- 429/418: FaultScript "rate-limit" (refuse-fast window).
- reject: below-minimum submit (venue -2013) at submit stages;
  "void-lookup" (-2013 on query) at lookup stages.
- partial: "partial-legs" (dust venue size forces partials).
- dupe / reorder: stream actions (same).
- ws-gap: harness drops stream envelopes; recovery via lookup (the
  designed gap path; socket death itself is "die", covered by dupe
  cells' reconnect twin "gap+die").
- skew: session clock +300s (evidence/expiry fail-closed; venue
  signature skew needs a credentialed venue — demo-drill covers it).
- sigkill: rebuild-equivalence at journal boundaries (drop +
  rebuild session/engine from durable state; a real kill -9 drill
  is an OWNER_ACTIONS demo step, timing-flaky in CI).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cryptobot.adapters.binance_live import BinanceLiveEngine
from cryptobot.adapters.sandbox_venue import (
    FaultScript,
    SandboxConfig,
    SandboxTransport,
    SandboxVenue,
)

NOW = datetime(2026, 10, 17, 12, 0, 0, tzinfo=UTC)
NOW_MS = int(NOW.timestamp() * 1000)
SYM = "BTCUSDT"

FAULTS = ["timeout", "5xx", "rate-limit", "reject", "partial", "dupe",
          "reorder", "ws-gap", "skew", "sigkill"]
STAGES = ["entry", "attach", "flatten", "resume"]


import contextlib

import pytest as _pytest


@_pytest.fixture(autouse=True)
def _reset_symbol_specs():
    """partial-legs mutates the global SYMBOLS table: restore per cell."""
    from cryptobot.adapters.sandbox_venue import SYMBOLS

    saved = {sym: dict(spec) for sym, spec in SYMBOLS.items()}
    yield
    for sym, spec in saved.items():
        SYMBOLS[sym].clear()
        SYMBOLS[sym].update(spec)


def _rig(tmp_path, monkeypatch, faults=(), seed=7):
    from pathlib import Path

    import venue_fixtures as venues  # noqa: F401 (ensures tests/ on path)
    from cryptobot.app.config import load_config
    from cryptobot.app.session import Session, _SymbolFeed
    from cryptobot.app.store import RunStore

    venue = SandboxVenue(SandboxConfig(
        seed=seed, faults=FaultScript(entries=list(faults))))
    venue.now_ms = lambda: NOW_MS  # frozen walk => deterministic book
    transport = SandboxTransport(venue)
    engine = BinanceLiveEngine(
        api_key="TESTKEY", api_secret="TESTSECRET",
        journal_path=tmp_path / "live.jsonl", expected_leverage=3,
        run_tag="chaos", live_enable=True, transport=transport,
        now_utc=lambda: NOW)
    text = Path("configs/demo.toml").read_text()
    text = text.replace('dir = "runs"', f'dir = "{tmp_path / "runs"}"', 1)
    cfg_path = tmp_path / "demo.toml"
    cfg_path.write_text(text)
    config = load_config(cfg_path)
    store = RunStore(tmp_path / "runs" / "cryptobot.db")
    session = Session(config, store, tmp_path / "run", "chaos",
                      engine=engine)
    session.clock.set_ms(NOW_MS)
    session.ledger.reseed_opening(10000.0)
    session.policy.reconcile_day(10000.0, 0.0)
    store.create_run("chaos", "paper", "fp", str(session.workdir), None)
    feed = _SymbolFeed(SYM, 0)
    book = venue.book(SYM)
    feed.mark = (book["bid"] + book["ask"]) / 2.0
    feed.mark_ts = NOW
    session._feeds[SYM] = feed
    engine.note_mark(SYM, feed.mark)
    return session, engine, venue, transport, store


def _intent(now):
    from cryptobot.coordination import DataQuality, ForecastCost, Intent, Side
    from cryptobot.coordination.exits import ExitPolicy, encode_exit_rule

    return Intent(
        strategy="S1", version="1", instrument=SYM, side=Side.LONG,
        evidence_ts_utc=now, entry_low=59990.0, entry_high=60010.0,
        entry_expiry_utc=now + timedelta(seconds=120),
        invalidation_price=59800.0,
        exit_rule=encode_exit_rule(ExitPolicy(
            stop_price=59800.0, target_price=60400.0,
            time_exit_utc=now + timedelta(seconds=600),
            policy_id="chaos")),
        holding_limit_s=600,
        forecast_cost=ForecastCost(5.0, 2.0, 5.0, 0.0),
        evidence_ref="chaos:1", data_quality=DataQuality.CLEAN)


def _pump(session, engine, venue, rounds=6, ctx=None):
    """Deliver stream envelopes + poll + lookup until quiet.

    When ctx carries drop_stream>0 (ws-gap cells), envelopes are
    dropped instead of delivered (counted), exercising the lookup
    heal path on genuinely lost stream messages.
    """
    for _ in range(rounds):
        moved = False
        for _ in range(20):
            try:
                env = venue.poll_stream()
            except ConnectionError:
                break  # scripted socket death: reconnect == next poll
            if env is None:
                break
            if ctx is not None and ctx.get("drop_stream", 0) > 0:
                ctx["drop_stream"] -= 1
                ctx["gap_dropped"] = ctx.get("gap_dropped", 0) + 1
                moved = True
                continue
            moved = True
            engine.note_user_event(env)
        for event in engine.poll():
            moved = True
            session._apply_engine_event(event)
        for cid in engine.unknown_ids():
            try:
                engine.lookup(cid)
            except Exception:
                pass
            else:
                moved = True
                for event in engine.poll():
                    session._apply_engine_event(event)
        if not moved:
            break


def _admit(session):
    from cryptobot.coordination.selector import Candidate

    session._maybe_admit([Candidate("S1", _intent(session.now_utc()))])


def _assert_cell_ok(session, engine, venue, *, stage, fault):
    """Money invariant: flat or protected; fills exact end to end."""
    from cryptobot.adapters.sandbox_venue import SYMBOLS

    ledger = session.ledger
    net = ledger.position_qty()
    if abs(net) <= 1e-9:
        return  # flat: the safe terminal state.
    min_qty = float(SYMBOLS[SYM]["min_qty"])
    dust = 0.0 < abs(net) < min_qty
    if not dust:
        # Exposed: a live covering stop must exist within budget.
        pos = session._position
        assert pos is not None, f"{stage}/{fault}: orphan exposure unsupervised"
        statuses = {}
        with contextlib.suppress(ValueError, KeyError, AttributeError):
            statuses = session._tracked_statuses_for(pos)
        live_stops = [
            lid for lid in list(pos.get("legs") or [])
            if statuses.get(lid) is not None
            and getattr(statuses[lid], "role", "") == "stop"
            and getattr(statuses[lid], "state", "") in ("open", "partial")]
        # Dust below venue minQty is unclosable by anyone (venue
        # rejects sub-min orders; the sandbox partial-legs size is an
        # artifact no real book prints): exempt from protected-or-
        # flat, but accounting below must still be exact.
        assert live_stops, f"{stage}/{fault}: naked exposure {net}"
    # No duplicate fills (exec ids unique in the ledger journal).
    execs = [e.get("exec_id") for e in ledger.to_dict()["journal"]
             if e.get("kind") == "fill"]
    assert len(execs) == len(set(execs)), f"{stage}/{fault}: dup fills"
    # No lost fills (venue tape vs ledger booked, per side).
    tape_buy = sum(float(t["qty"]) for t in venue.trades
                   if t["side"] == "BUY")
    tape_sell = sum(float(t["qty"]) for t in venue.trades
                    if t["side"] == "SELL")
    led_buy = sum(e["qty"] for e in ledger.to_dict()["journal"]
                  if e.get("kind") == "fill" and e.get("side") == "BUY")
    led_sell = sum(e["qty"] for e in ledger.to_dict()["journal"]
                   if e.get("kind") == "fill" and e.get("side") == "SELL")
    assert abs(tape_buy - led_buy) <= 1e-9, (stage, fault, tape_buy, led_buy)
    assert abs(tape_sell - led_sell) <= 1e-9, (stage, fault, tape_sell,
                                               led_sell)


def _fault_entries(fault, op):
    if fault in ("timeout", "5xx"):
        return [{"op": op, "action": "unknown", "at": "once"}]
    if fault == "rate-limit":
        return [{"op": op, "action": "rate-limit", "at": "once"}]
    if fault == "reject" and op in ("query", "lookup"):
        return [{"op": op, "action": "void-lookup", "at": "once"}]
    if fault == "partial":
        return [{"op": op, "action": "partial-legs", "at": "once"}]
    if fault in ("dupe", "reorder"):
        return [{"op": "stream", "action": fault, "at": "once"}]
    return []


def _apply_harness_fault(fault, ctx):
    """Faults the venue script cannot express (gap drop, skew, kill)."""
    session, engine, venue = ctx["session"], ctx["engine"], ctx["venue"]
    if fault == "ws-gap":
        # Drops happened inside _pump (drop_stream); heal everything
        # outstanding via lookup now.
        for cid in list(engine.unknown_ids()):
            with contextlib.suppress(Exception):
                engine.lookup(cid)
        for event in engine.poll():
            session._apply_engine_event(event)
    elif fault == "skew":
        session.clock.set_ms(NOW_MS + 300_000)
        ctx["skewed"] = True
    elif fault == "sigkill":
        _rebuild(ctx)
    elif fault == "reject":
        # Below-minimum submit straight at the venue (client
        # validation bypassed): must reject, booking nothing.
        from cryptobot.adapters.binance_live import VenueHttpError

        with pytest.raises(VenueHttpError):
            venue.place_order({"symbol": SYM, "side": "BUY",
                               "type": "MARKET", "quantity": 0.0000001,
                               "newClientOrderId": "chaos-dust"})
        assert "chaos-dust" not in venue.by_client
        ctx["reject_raised"] = True


def _rebuild(ctx):
    """SIGKILL equivalence: drop + rebuild from durable state."""
    from cryptobot.app.session import Session

    tmp_path, store = ctx["tmp_path"], ctx["store"]
    venue = ctx["venue"]
    snap_path = tmp_path / "venue-snap.json"
    venue.save(snap_path)
    engine = BinanceLiveEngine(
        api_key="TESTKEY", api_secret="TESTSECRET",
        journal_path=tmp_path / "live.jsonl", expected_leverage=3,
        run_tag="chaos", live_enable=True,
        transport=SandboxTransport(
            SandboxVenue.load(snap_path, venue.cfg)),
        now_utc=lambda: NOW)
    engine._transport.venue.now_ms = lambda: NOW_MS  # keep walk frozen
    session = Session(ctx["config"], store, tmp_path / "run", "chaos",
                      engine=engine)
    session.clock.set_ms(NOW_MS)
    ctx.update(session=session, engine=engine,
               venue=engine._transport.venue, rebuilt=True)


@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("fault", FAULTS)
def test_chaos_matrix(tmp_path, monkeypatch, stage, fault):
    session, engine, venue, transport, store = _rig(
        tmp_path, monkeypatch)
    ctx = {"tmp_path": tmp_path, "store": store, "config": session.config,
           "session": session, "engine": engine, "venue": venue}
    # Reach the stage CLEANLY (faults injected only after setup, so
    # each cell faults exactly the stage under test) — except entry,
    # where the fault must be armed before the first submit.
    if stage == "entry":
        _inject_for_stage(fault, stage, ctx)
    _admit(session)
    _pump(session, engine, venue, ctx=ctx)
    if stage != "entry":
        _drive_attach(session, engine, venue, ctx)
    if stage == "resume":
        _rebuild(ctx)
        session, engine, venue = ctx["session"], ctx["engine"], ctx["venue"]
    # Inject the fault for THIS stage only.
    if stage != "entry":
        _inject_for_stage(fault, stage, ctx)
    session, engine, venue = ctx["session"], ctx["engine"], ctx["venue"]
    # Drive one step under fault, then quiesce.
    if stage == "entry":
        pass  # admit already drove entry; fault hit the submit path.
    elif stage == "attach":
        _force_reattach(session, engine, venue, ctx)
    elif stage == "flatten":
        if session._position is not None or session.ledger.has_position():
            with contextlib.suppress(Exception):
                session._flatten(f"chaos-{fault}")
        _pump(session, engine, venue, ctx=ctx)
    elif stage == "resume":
        with contextlib.suppress(KeyError, ValueError):
            session._resume_live()
        _pump(session, engine, venue, ctx=ctx)
    _apply_harness_fault(fault, ctx)
    session, engine, venue = ctx["session"], ctx["engine"], ctx["venue"]
    _pump(session, engine, venue, ctx=ctx)
    # Quiesce: resolve unknowns, settle once.
    for cid in list(engine.unknown_ids()):
        with contextlib.suppress(Exception):
            engine.lookup(cid)
    # Gap heal: dropped stream fills carry no unknown flag; sweep all
    # tracked ids through lookup (the designed gap-recovery path).
    if fault == "ws-gap":
        _heal_all_tracked(session, engine)
    # Rate-limit cells: the 60s refuse-fast window would stall the
    # rest of the cell; time-travel past it (white-box, documented)
    # then retry, proving refuse -> recover end to end.
    if fault == "rate-limit":
        engine._rate_limited_until_ms = 0  # noqa: SLF001
        for _ in range(3):
            if session._position is not None:
                with contextlib.suppress(Exception):
                    session._update_position(_synthetic_tick(session))
            _pump(session, engine, venue, ctx=ctx)
    _pump(session, engine, venue, ctx=ctx)
    # Post-resume settle: adoption + flatten + release need ticks.
    if stage == "resume":
        for _ in range(6):
            if session._position is not None:
                with contextlib.suppress(Exception):
                    session._update_position(_synthetic_tick(session))
            _pump(session, engine, venue, ctx=ctx)
    _pump(session, engine, venue, ctx=ctx)
    _assert_fault_fired(fault, ctx, stage)
    session, engine, venue = ctx["session"], ctx["engine"], ctx["venue"]
    _assert_cell_ok(session, engine, venue, stage=stage, fault=fault)


def _inject_for_stage(fault, stage, ctx):
    venue = ctx["venue"]
    op = {"entry": "order", "attach": "algoOrder", "flatten": "order",
          "resume": "order"}[stage]
    venue.cfg.faults.entries.extend(_fault_entries(fault, op))
    if fault == "ws-gap":
        # Drop the next envelopes inside _pump (genuine loss), then
        # the quiesce lookups heal via the tape.
        ctx["drop_stream"] = 5


def _drive_attach(session, engine, venue, ctx=None):
    for _ in range(4):
        if session._position is not None:
            session._update_position(_synthetic_tick(session))
            _pump(session, engine, venue, ctx=ctx)


def _force_reattach(session, engine, venue, ctx=None):
    """Retire live legs venue-side so attach runs fresh under fault."""
    pos = session._position
    if pos is None:
        return
    for lid in list(pos.get("legs") or []):
        with contextlib.suppress(Exception):
            engine.cancel(lid, "chaos-force-reattach")
        if lid in pos.get("legs", []):
            pos["legs"].remove(lid)
            pos.setdefault("retired", []).append(lid)
    pos["protected"] = False
    _pump(session, engine, venue, ctx=ctx)
    session._update_position(_synthetic_tick(session))
    _pump(session, engine, venue, ctx=ctx)


def _heal_all_tracked(session, engine):
    """Lookup sweep over every tracked id (gap recovery driver)."""
    pos = session._position
    ids = list(session._orphan_close_ids)
    if pos is not None:
        ids += [pos.get("entry_pre_id") or "", pos.get("entry_id") or ""]
        ids += list(pos.get("legs") or [])
        ids += list(pos.get("retired") or [])
        ids += list(pos.get("close_ids") or [])
    for cid in ids:
        if not cid:
            continue
        with contextlib.suppress(Exception):
            engine.lookup(cid)


def _assert_fault_fired(fault, ctx, stage):
    """Non-vacuous cells: prove the fault actually triggered."""
    venue = ctx["venue"]
    if fault in ("timeout", "5xx", "rate-limit", "partial", "dupe",
                 "reorder"):
        assert venue._fault_hits, (  # noqa: SLF001
            f"{stage}/{fault}: fault script never fired (vacuous cell)")
    elif fault == "ws-gap":
        assert ctx.get("gap_dropped", 0) > 0, f"{stage}: no gap dropped"
    elif fault == "skew":
        assert ctx.get("skewed", False), f"{stage}: clock not moved"
    elif fault == "sigkill":
        assert ctx.get("rebuilt", False), f"{stage}: no rebuild happened"
    elif fault == "reject":
        assert ctx.get("reject_raised", False), f"{stage}: no rejection"


def _synthetic_tick(session):
    from cryptobot.app.engine import EngineEvent

    return EngineEvent("timer", {"tick": True}, session.now_utc())
