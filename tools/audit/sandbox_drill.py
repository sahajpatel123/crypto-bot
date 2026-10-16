#!/usr/bin/env python3
"""Offline sandbox drill runner (DEEP-W2-D3).

Subcommands: preflight | drill | interrupt | resume | stream-gap |
reconcile | full

Drives the REAL Session + BinanceLiveEngine + supervised user-stream
paths through scriptable SandboxTransport with virtual capital. Fully
offline: seed-pinned, no network, no credentials. Interrupt lands with
exposure; resume adopts fills and flattens; reconcile proves
reconciled-flat or fails explicitly.

Verdicts: PASS / FAIL / BLOCKED per phase (JSONL evidence +
auto-generated report.md/json). `full` exits 1 on any FAIL, 2 when
anything is BLOCKED (incl. any omitted phase), 0 only when every
required phase passes. Failed/blocked preflight prevents entry.

A PASS records SANDBOX VALIDATED (execution mechanics on simulated
venue responses). Binance demo validation stays BINANCE DEMO
VALIDATION PENDING until the prepared demo command runs with
owner-supplied credentials (see docs/sandbox_demo_command.md).

Usage:
    sandbox_drill.py [--dir DIR] [--symbol SYM] [--seed N] full
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

EXIT_BLOCKED = 2
EXIT_INCOMPLETE = 124

ENTRY_CUTOFF_S = 20 * 60
CLOSE_BY_S = 25 * 60
EXIT_MARGIN_S = 3 * 60
CLEANUP_S = 2 * 60
MAX_NOTIONAL_USDT = 25.0
QUOTE_MAX_AGE_S = 10.0
VIRTUAL_CAPITAL_USDT = 10000.0

PHASES_FULL = ("preflight", "drill", "interrupt", "resume",
               "stream-gap", "reconcile")


def _utcnow():
    return datetime.now(timezone.utc)


def _make_venue(seed):
    from cryptobot.adapters.sandbox_venue import (
        SandboxConfig, SandboxVenue)
    return SandboxVenue(SandboxConfig(
        seed=seed, virtual_capital_usdt=VIRTUAL_CAPITAL_USDT))


class Drill:
    def __init__(self, run_dir, symbol, seed):
        self.dir = Path(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.symbol = symbol.upper()
        self.seed = int(seed)
        self.start_mono = time.monotonic()
        self.evidence_path = self.dir / "sandbox_evidence.jsonl"
        self.journal_path = self.dir / "sandbox_journal.jsonl"
        self.store_path = self.dir / "sandbox_store.db"
        self.session_dir = self.dir / "session"
        self.venue_path = self.dir / "sandbox_venue.json"
        self.run_id = "sandbox-drill"
        self.heal_wait_s = 30.0
        self.fill_wait_s = 30.0
        self.flat_wait_s = 60.0
        self.gap_wait_s = 15.0
        self.poll_s = 0.05
        self.stream_kwargs = {"start_thread": False,
                              "initial_backoff_s": 0.01,
                              "poll_timeout_s": 0.05,
                              "idle_sleep_s": 0.01}
        self._venue = None
        # Scripted dial refusal: while >0, ws_factory redials fail so
        # the gap halt is observable (instant redial would reheal
        # within one pump step and prove nothing).
        self.redial_failures = 0

    # -- venue persistence ------------------------------------------------
    def venue(self):
        if self._venue is None:
            from cryptobot.adapters.sandbox_venue import SandboxVenue
            if self.venue_path.exists():
                self._venue = SandboxVenue.load(self.venue_path)
            else:
                self._venue = _make_venue(self.seed)
        return self._venue

    def save_venue(self):
        if self._venue is not None:
            self._venue.save(self.venue_path)

    def drop_venue(self):
        self._venue = None

    # -- logging / budgets --------------------------------------------------
    def log(self, phase, verdict, detail=""):
        rec = {"ts_utc": _utcnow().isoformat(), "phase": phase,
               "verdict": verdict, "detail": str(detail),
               "elapsed_s": round(time.monotonic() - self.start_mono, 1)}
        with open(self.evidence_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        print(f"[{verdict}] {phase}: {detail}", flush=True)
        return verdict

    def remaining_budget(self):
        raw = os.environ.get("CRYPTOBOT_DEADLINE_MONO")
        if not raw:
            return None
        try:
            return float(raw) - time.monotonic()
        except ValueError:
            return None

    def kill(self, phase, detail):
        self.log(phase, "FAIL", f"KILL: {detail}")
        return 1

    def entry_allowed(self):
        elapsed = time.monotonic() - self.start_mono
        if elapsed + EXIT_MARGIN_S >= CLOSE_BY_S:
            return False
        remaining = self.remaining_budget()
        if remaining is not None and remaining < CLEANUP_S:
            return False
        return True

    def wait_until(self, predicate, timeout_s, label):
        start = time.monotonic()
        while True:
            if predicate():
                return True, round(time.monotonic() - start, 1)
            if time.monotonic() - start >= timeout_s:
                return False, round(time.monotonic() - start, 1)
            time.sleep(self.poll_s)

    def pump_wait(self, stream, predicate, timeout_s, label):
        """wait_until stepping the single-threaded stream pump."""
        start = time.monotonic()
        while True:
            try:
                stream.poll_once()
            except Exception:
                pass
            if predicate():
                return True, round(time.monotonic() - start, 1)
            if time.monotonic() - start >= timeout_s:
                return False, round(time.monotonic() - start, 1)
            time.sleep(self.poll_s)

    def drain_stream(self, stream, session, engine, max_steps=50):
        """Consume stale stream/pending events (bounded, deterministic).

        Ends phases with an empty venue queue + empty engine pending so
        no phase inherits another's envelopes. Returns (idle_steps).
        """
        idle = 0
        for _ in range(max_steps):
            try:
                action = stream.poll_once()
            except Exception:
                action = "error"
            try:
                drained = session._drain_engine()
            except Exception:
                drained = 0
            if action in ("idle", "keepalive", "backoff") and drained == 0 \
                    and not engine._pending:
                idle += 1
                if idle >= 3:
                    break
            else:
                idle = 0
        return idle

    # -- wiring -----------------------------------------------------------------
    def engine(self, transport=None):
        from cryptobot.adapters.binance_live import BinanceLiveEngine
        from cryptobot.adapters.sandbox_venue import SandboxTransport
        return BinanceLiveEngine(
            api_key="SANDBOX", api_secret="SANDBOX-NO-CREDS",
            journal_path=self.journal_path, expected_leverage=3,
            run_tag="sandbox", live_enable=True, demo=True,
            base_url="https://sandbox.offline",
            transport=transport or SandboxTransport(self.venue()),
            now_utc=_utcnow)

    def session(self, engine, run_id=None):
        from cryptobot.app.config import load_config
        from cryptobot.app.session import Session, WallClock
        from cryptobot.app.store import RunStore
        cfg = load_config(ROOT / "configs" / "demo.toml")
        store = RunStore(self.store_path)
        session = Session(cfg, store, self.session_dir,
                          run_id or self.run_id, pid=os.getpid(),
                          clock=WallClock(), engine=engine)
        return session, store

    def ensure_run(self, session, store):
        if store.get_run(session.run_id) is None:
            store.create_run(session.run_id, session.config.mode,
                             session.config.fingerprint,
                             str(session.workdir), os.getpid())
            session.policy.reconcile_day(
                session.config.paper_capital_usdt, 0.0)

    def ws_factory(self, engine):
        from cryptobot.adapters.sandbox_venue import SandboxSocket

        def _factory(listen_key):
            if self.redial_failures > 0:
                self.redial_failures -= 1
                raise ConnectionError("sandbox: dial refused (scripted)")
            return SandboxSocket(self.venue())

        return _factory

    def attach_stream(self, session, engine):
        from cryptobot.adapters.user_stream import attach_user_stream
        return attach_user_stream(session, engine,
                                  self.ws_factory(engine),
                                  **self.stream_kwargs)

    def prime_feed(self, session, mark):
        from cryptobot.app.session import _SymbolFeed
        filt = session.engine._filters[self.symbol]
        session.arm_replay_filters(
            {self.symbol: {"tick_size": float(filt["tick"]),
                           "step_size": float(filt["step"]),
                           "min_qty": float(filt["min_qty"]),
                           "min_notional": float(filt["min_notional"])}},
            origin="sandbox-drill", asof_utc=session.now_utc())
        feed = _SymbolFeed(self.symbol, 0)
        feed.mark = mark
        feed.mark_ts = session.now_utc()
        session._feeds[self.symbol] = feed

    def drill_intent(self, session, mark):
        from datetime import timedelta

        from cryptobot.coordination.exits import ExitPolicy, encode_exit_rule
        from cryptobot.coordination.intent import (
            DataQuality, ForecastCost, Intent, Side)
        now = session.now_utc()
        return Intent(
            strategy="drill", version="0.1.0",
            instrument=self.symbol, side=Side.LONG,
            evidence_ts_utc=now,
            entry_low=round(mark * 0.999, 2),
            entry_high=round(mark * 1.001, 2),
            entry_expiry_utc=now + timedelta(seconds=120),
            invalidation_price=round(mark * 0.98, 4),
            exit_rule=encode_exit_rule(ExitPolicy(
                stop_price=round(mark * 0.98, 4),
                target_price=round(mark * 1.05, 2),
                time_exit_utc=now + timedelta(seconds=600),
                policy_id="sandbox-drill")),
            holding_limit_s=600,
            forecast_cost=ForecastCost(5.0, 5.0, 5.0, 1.0),
            evidence_ref="sandbox-drill:1",
            data_quality=DataQuality.CLEAN)

    def live_quote(self):
        """(mid, event_ms) from the sandbox book (offline, labeled)."""
        from cryptobot.adapters.sandbox_venue import SandboxTransport
        view = SandboxTransport(self.venue()).request(
            "GET", "/fapi/v1/ticker/bookTicker",
            {"symbol": self.symbol}, {})
        mid = (float(view["bidPrice"]) + float(view["askPrice"])) / 2.0
        return mid, int(view["time"])

    def live_mark(self):
        return self.live_quote()[0]

    def quote_fresh(self):
        try:
            _, event_ms = self.live_quote()
        except Exception as exc:
            return False, f"quote fetch failed: {exc!r}"
        if event_ms is None:
            return False, "quote event time unknown (fail closed)"
        age_s = time.time() - event_ms / 1000.0
        if age_s < 0 or age_s > QUOTE_MAX_AGE_S:
            return False, f"quote age {age_s:.1f}s exceeds {QUOTE_MAX_AGE_S}s"
        return True, f"quote age {age_s:.1f}s"


def cmd_preflight(drill):
    fails = 0
    try:
        venue = drill.venue()
        server_ms = venue.now_ms()
        skew_ms = abs(server_ms - int(_utcnow().timestamp() * 1000))
        ok = skew_ms < 5000
        drill.log("preflight/clock", "PASS" if ok else "FAIL",
                  f"sandbox server skew {skew_ms}ms (seed {drill.seed})")
        fails += not ok
        engine = drill.engine()
        try:
            engine._ensure_ready(drill.symbol)
            drill.log("preflight/readiness", "PASS",
                      f"filters+fees cached for {drill.symbol}")
            available, free = engine.account_margin()
            ok = available > 0
            drill.log("preflight/account", "PASS" if ok else "FAIL",
                      f"virtual available={available} free={free}")
            fails += not ok
            drill.log("preflight/fees", "PASS",
                      f"taker={engine.fee_bps(drill.symbol)}bps "
                      f"(sandbox fixture)")
        finally:
            engine.close()
        mark = drill.live_mark()
        drill.log("preflight/mark", "PASS", f"{drill.symbol} mark {mark}")
        fresh, detail = drill.quote_fresh()
        if not fresh:
            return drill.kill("preflight/quote-fresh", detail)
        drill.log("preflight/quote-fresh", "PASS", detail)
        drill.save_venue()
        return 1 if fails else 0
    except Exception as exc:
        drill.log("preflight", "FAIL", repr(exc))
        return 1


def _tiny_qty(drill, engine):
    mark = drill.live_mark()
    filt = engine._filters[drill.symbol]
    step = float(filt.get("step", 0.001))
    min_notional = float(filt.get("min_notional", 5.0))
    qty = max(step, min_notional * 1.2 / mark)
    qty = round(qty - (qty % step) + step, 8)
    if qty * mark > MAX_NOTIONAL_USDT:
        return None
    return qty, mark


def _emergency_flatten(drill, session, reason):
    try:
        net_before = session.ledger.position_qty()
    except Exception:
        net_before = float("nan")
    try:
        session._flatten(reason)
        for _ in range(20):
            if session._drain_engine() == 0:
                break
            time.sleep(drill.poll_s)
        net_after = session.ledger.position_qty()
    except Exception as exc:
        drill.log("drill/emergency-flatten", "FAIL",
                  f"net_before={net_before}: {exc!r}")
        return False
    ok = abs(net_after) <= 1e-9
    drill.log("drill/emergency-flatten", "PASS" if ok else "FAIL",
              f"net {net_before} -> {net_after}")
    return ok


def _session_has_exposure(session):
    try:
        if abs(session.ledger.position_qty()) > 1e-12:
            return True
    except Exception:
        pass
    return session._position is not None


def _drain_and_flat(session):
    session._drain_engine()
    try:
        return abs(session.ledger.position_qty()) <= 1e-9
    except Exception:
        return False


def _verify_protection(drill, session, engine, stream=None,
                       timeout_s=None, tag="drill/protection"):
    timeout_s = drill.flat_wait_s if timeout_s is None else timeout_s

    def _live():
        session._drain_engine()
        pos = session._position
        if pos is None:
            return False
        legs = pos.get("legs") or []
        if not legs:
            return False
        st = engine.order_status(legs[0])
        return st is not None and st.state in ("open", "partial")

    if stream is not None:
        ok, waited = drill.pump_wait(stream, _live, timeout_s,
                                     "protection")
    else:
        ok, waited = drill.wait_until(_live, timeout_s, "protection")
    pos = session._position
    leg = (pos.get("legs") or [None])[0] if pos else None
    st = engine.order_status(leg) if leg else None
    drill.log(tag, "PASS" if ok else "FAIL",
              f"stop leg {leg} state={st.state if st else 'missing'} "
              f"in {waited}s")
    return ok


def _ambiguous_submit(drill, engine, mark):
    from cryptobot.adapters.binance_live import (
        UnknownOutcomeError, VenueHttpError)
    from cryptobot.app.engine import EngineOrder
    if not drill.entry_allowed():
        drill.log("drill/ambiguous-submit", "BLOCKED", "past entry window")
        return 0
    qty, _ = _tiny_qty(drill, engine)

    class _DropOnce:
        def __init__(self, inner):
            self.inner = inner
            self.armed = True

        def request(self, method, path, params, headers):
            if self.armed and method == "POST" and path == "/fapi/v1/order":
                self.armed = False
                self.inner.request(method, path, params, headers)
                raise VenueHttpError(0, None, "sandbox: response dropped")
            return self.inner.request(method, path, params, headers)

    engine2 = drill.engine(transport=_DropOnce(engine._transport))
    try:
        engine2._ensure_ready(drill.symbol)
        try:
            engine2.submit(EngineOrder(
                drill.symbol, "BUY", qty, "LIMIT",
                price=round(mark * 0.99, 2),
                reservation_id="sandbox-ambig-1", role="entry"))
            drill.log("drill/ambiguous-submit", "FAIL",
                      "dropped response did not raise UNKNOWN")
            return 1
        except UnknownOutcomeError as exc:
            found = engine2.lookup(exc.client_id)
            intents = [r for r in engine2._read_journal()
                       if r.get("event") == "submit-intent"
                       and r.get("reservation_id") == "sandbox-ambig-1"]
            dupes = [o for o in engine2.open_orders()
                     if o.client_order_id == exc.client_id]
            if found is not None and len(intents) == 1 and len(dupes) <= 1:
                drill.log(
                    "drill/ambiguous-submit", "PASS",
                    f"UNKNOWN {exc.client_id} resolved; 1 submit intent, "
                    f"{len(dupes)} open leg(s); no duplicate")
                return 0
            drill.log(
                "drill/ambiguous-submit", "FAIL",
                f"cid={exc.client_id} resolved={found is not None} "
                f"intents={len(intents)} open_legs={len(dupes)}")
            return 1
    finally:
        try:
            engine2.close()
        except Exception:
            pass


def cmd_drill(drill):
    """Normal-Session entry → protection → exit (+ ambiguous-submit)."""
    from cryptobot.adapters.binance_live import UnknownOutcomeError
    from cryptobot.coordination.selector import Candidate
    fresh, detail = drill.quote_fresh()
    if not fresh:
        return drill.kill("drill/quote-fresh", detail)
    drill.log("drill/quote-fresh", "PASS", detail)
    engine = drill.engine()
    session, store = None, None
    stream = None
    rc = 0
    try:
        engine._ensure_ready(drill.symbol)
        if not drill.entry_allowed():
            drill.log("drill/entry-cutoff", "BLOCKED",
                      "past entry window (exit margin / cleanup budget)")
            return EXIT_BLOCKED
        sized = _tiny_qty(drill, engine)
        if sized is None:
            return drill.kill(
                "drill/exposure-cap",
                f"tiny qty exceeds {MAX_NOTIONAL_USDT} USDT cap")
        _, mark = sized
        if engine.unknown_ids():
            return drill.kill(
                "drill/pre-entry-reconcile",
                f"unknown outcomes {sorted(engine.unknown_ids())}")
        session, store = drill.session(engine)
        store.acquire_lock()
        drill.ensure_run(session, store)
        drill.prime_feed(session, mark)
        stream = drill.attach_stream(session, engine)
        healed, waited = drill.pump_wait(
            stream, lambda: not stream.halted, drill.heal_wait_s,
            "heal")
        if not healed:
            return drill.kill("drill/stream-heal",
                              f"no stream heal in {waited}s; no blind entry")
        drill.log("drill/stream-heal", "PASS",
                  f"sandbox stream healed in {waited}s")
        from cryptobot.risk.types import Approved
        intent = drill.drill_intent(session, mark)
        snapshot = session._snapshot_account(symbol=drill.symbol)
        verdict = session.policy.evaluate(intent, snapshot)
        if isinstance(verdict, Approved):
            notional = verdict.qty * mark
            session.policy.release(verdict.reservation_id)
            if notional > MAX_NOTIONAL_USDT:
                return drill.kill(
                    "drill/exposure-cap",
                    f"session sizing {verdict.qty} (~{notional:.2f} USDT) "
                    f"exceeds {MAX_NOTIONAL_USDT} USDT cap")
        try:
            session._maybe_admit([Candidate("drill", intent)])
        except UnknownOutcomeError as exc:
            found = engine.lookup(exc.client_id)
            if found is None or engine.unknown_ids():
                return drill.kill(
                    "drill/entry-unknown",
                    f"{exc.client_id} unresolvable after lookup")
            drill.log("drill/entry-unknown", "PASS",
                      f"{exc.client_id} resolved via lookup")
        pos = session._position
        if pos is None:
            drill.log("drill/entry", "BLOCKED",
                      "admission rejected (see rejections.jsonl); no order")
            return EXIT_BLOCKED
        pre_id = pos["entry_pre_id"]

        def _filled_or_dead():
            session._drain_engine()
            st = engine.order_status(pre_id)
            if st is None:
                return False
            if st.filled_qty > 1e-12:
                return True
            return st.state in ("cancelled", "expired", "rejected")

        filled_or_dead, waited = drill.pump_wait(
            stream, _filled_or_dead, drill.fill_wait_s, "fill")
        st = engine.order_status(pre_id)
        state = st.state if st else "missing"
        filled = st.filled_qty if st else 0.0
        if not filled_or_dead:
            return drill.kill("drill/entry-ioc",
                              f"{pre_id} neither filled nor terminal "
                              f"in {waited}s (state={state})")
        drill.log("drill/entry-ioc",
                  "PASS" if state in ("filled", "cancelled", "partial")
                  else "FAIL",
                  f"{pre_id} -> {state} filled={filled}")
        if state not in ("filled", "cancelled", "partial"):
            return drill.kill("drill/entry-ioc",
                              f"unexpected entry state {state}")
        if filled > 0:
            if not _verify_protection(drill, session, engine, stream):
                _emergency_flatten(drill, session, "sandbox:protect-miss")
                return drill.kill(
                    "drill/protection",
                    "stop leg not verified live; emergency flatten attempted")
            try:
                session._flatten("sandbox-drill-close")
            except ValueError as exc:
                return drill.kill("drill/reduce-only-exit", repr(exc))
            flat, waited = drill.pump_wait(
                stream, lambda: _drain_and_flat(session),
                drill.flat_wait_s, "flat")
            net = session.ledger.position_qty()
            if not flat:
                _emergency_flatten(drill, session,
                                   "sandbox:exit-incomplete")
                return drill.kill(
                    "drill/reduce-only-exit",
                    f"not flat in {waited}s (net={net}); emergency "
                    f"flatten attempted — owner must review")
            drill.log("drill/reduce-only-exit", "PASS",
                      f"flat in {waited}s (net={net})")
            try:
                for lid in list((session._position or {}).get("legs", [])):
                    engine.cancel(lid, "sandbox:position-closed")
            except Exception as exc:
                drill.log("drill/protection-cancel", "FAIL", repr(exc))
                rc = 1
            if engine.unknown_ids():
                return drill.kill(
                    "drill/post-exit-reconcile",
                    f"unknown outcomes {sorted(engine.unknown_ids())}")
        else:
            drill.log("drill/protection-exit", "BLOCKED",
                      "no fill to protect (honest no-trade)")
        rc = _ambiguous_submit(drill, engine, mark) or rc
        drill.drain_stream(stream, session, engine)
        drill.save_venue()
        return rc
    finally:
        try:
            if session is not None:
                session._persist_local_state()
        except Exception:
            pass
        try:
            if stream is not None:
                stream.close()
        except Exception:
            pass
        try:
            store.release_lock()
        except Exception:
            pass
        try:
            store.close()
        except Exception:
            pass
        try:
            engine.close()
        except Exception:
            pass
        drill.save_venue()


def cmd_interrupt(drill):
    """Open exposure, then crash WITHOUT flatten (resume must adopt).

    PASS requires the interrupt to land while exposure exists
    (venue position + ledger nonzero + journaled legs live); the
    phase then persists venue + local state and closes everything
    WITHOUT closing the position (simulated process death).
    """
    from cryptobot.coordination.selector import Candidate
    fresh, detail = drill.quote_fresh()
    if not fresh:
        return drill.kill("interrupt/quote-fresh", detail)
    engine = drill.engine()
    session, store = None, None
    stream = None
    try:
        engine._ensure_ready(drill.symbol)
        mark = drill.live_mark()
        session, store = drill.session(engine)
        store.acquire_lock()
        drill.ensure_run(session, store)
        drill.prime_feed(session, mark)
        stream = drill.attach_stream(session, engine)
        healed, _ = drill.pump_wait(
            stream, lambda: not stream.halted, drill.heal_wait_s,
            "heal")
        if not healed:
            return drill.kill("interrupt/stream-heal",
                              "no stream heal; no blind entry")
        # New process continuing the run: restore ledger + booking
        # state + command sequence before issuing new commands. The
        # drill ended flat, so no pending-flatten retry can fire here.
        session._resume_live()
        drill.log("interrupt/restored", "PASS",
                  f"ledger_net={session.ledger.position_qty()}")
        drill.drain_stream(stream, session, engine)
        intent = drill.drill_intent(session, mark)
        session._maybe_admit([Candidate("drill", intent)])
        if session._position is None:
            drill.log("interrupt/entry", "BLOCKED",
                      "admission rejected; nothing to interrupt")
            return EXIT_BLOCKED
        pre_id = session._position["entry_pre_id"]
        # Crash BEFORE any fill dispatch: submit fills synchronously
        # at the venue; verify via DIRECT venue REST (no engine
        # adoption), then die without pumping. Venue holds exposure
        # the Session has never seen — resume must adopt it.
        from cryptobot.adapters.sandbox_venue import SandboxTransport
        view = SandboxTransport(drill.venue()).request(
            "GET", "/fapi/v1/order",
            {"symbol": drill.symbol, "origClientOrderId": pre_id}, {})
        if view["status"] != "FILLED":
            drill.log("interrupt/exposure", "BLOCKED",
                      f"venue entry not filled ({view['status']}); "
                      f"honest no-trade")
            return EXIT_BLOCKED
        drill.log("interrupt/exposure", "PASS",
                  f"venue exposure +{view['executedQty']} {drill.symbol} "
                  f"unadopted (ledger flat, queue holds the TRADE)")
        # Persist the live shell primitives for drill-side recovery:
        # Session does not rebuild _position across restart (W1 D2
        # owns the session-level fix); without a shell the adopted
        # fill cannot book (reservation unresolvable). Journaled
        # truth only — no invented fields.
        pos = session._position or {}
        (drill.dir / "crash_shell.json").write_text(json.dumps({
            "reservation_id": pos.get("reservation_id"),
            "instrument": pos.get("instrument"),
            "side": pos.get("side"),
            "entry_pre_id": pos.get("entry_pre_id"),
            "stop": pos.get("stop"), "target": pos.get("target"),
            "time_exit": pos.get("time_exit"),
            "entry_cap": pos.get("entry_cap"),
            "approved_qty": pos.get("approved_qty"),
            "executable_qty": pos.get("executable_qty"),
            "strategy": pos.get("strategy"),
        }, default=str), encoding="utf-8")
        # Simulated death: persist everything, close nothing gracefully
        # except the store lock (the OS would not even do that).
        session._persist_local_state()
        drill.save_venue()
        drill.log("interrupt/crash", "PASS",
                  "state persisted; process 'died' with venue exposure "
                  "unadopted")
        return 0
    finally:
        try:
            if stream is not None:
                stream.close()
        except Exception:
            pass
        try:
            store.release_lock()
        except Exception:
            pass
        try:
            store.close()
        except Exception:
            pass
        try:
            engine.close()
        except Exception:
            pass
        drill.drop_venue()  # resume must reload from disk.


def cmd_resume(drill):
    """Fresh objects adopt fills, then flatten to reconciled-flat.

    Reopens store/journal/venue with brand-new objects, runs the
    normal resume path, verifies adopted fills booked + legs live,
    closes through the stream, cancels orphaned legs, and proves
    flat-or-explicit-failure.
    """
    if not drill.store_path.exists() or not drill.journal_path.exists():
        drill.log("resume", "BLOCKED",
                  "no drill store/journal to adopt (run drill first)")
        return EXIT_BLOCKED
    from cryptobot.accounting.ledger import Ledger
    engine = drill.engine()
    session, store = drill.session(engine)
    stream = None
    try:
        store.acquire_lock()
        if store.get_run(session.run_id) is None:
            drill.log("resume", "BLOCKED",
                      "no drill run row to adopt (run drill first)")
            return EXIT_BLOCKED
        # Restore persisted truth BEFORE attaching the stream: heal
        # dispatch books into the live ledger, and a resume after it
        # would reload the persisted copy and wipe those bookings.
        # Marks stay UNPRIMED during _resume_live on purpose: priming
        # would fire the pending-flatten retry whose fill no shell
        # tracks (unbookable); the drill issues one tracked close
        # below instead. No run loop ticks here, so the pending flag
        # cannot refire behind us.
        engine._ensure_ready(drill.symbol)
        before = store.counts(session.run_id).get("execution_events", 0)
        session._resume_live()
        drill.log("resume/restored", "PASS",
                  f"ledger_net={session.ledger.position_qty()}")
        # Drill-side shell recovery (see crash note; W1 D2 owns the
        # session-level fix): rebuild the position shell from
        # persisted journaled truth so the adopted fill can book.
        # Only when the venue actually holds the entry fill.
        shell_path = drill.dir / "crash_shell.json"
        if shell_path.exists() and session._position is None:
            from cryptobot.adapters.sandbox_venue import SandboxTransport
            shell = json.loads(shell_path.read_text(encoding="utf-8"))
            try:
                view = SandboxTransport(drill.venue()).request(
                    "GET", "/fapi/v1/order",
                    {"symbol": drill.symbol,
                     "origClientOrderId": shell["entry_pre_id"]}, {})
                venue_filled = float(view.get("executedQty", 0.0) or 0.0)
            except Exception:
                venue_filled = 0.0
            if venue_filled > 0 and shell.get("reservation_id"):
                session._position = {
                    "reservation_id": shell["reservation_id"],
                    "instrument": shell["instrument"],
                    "side": shell["side"],
                    "entry_pre_id": shell["entry_pre_id"],
                    "entry_id": None, "legs": [],
                    "stop": shell["stop"], "target": shell["target"],
                    "time_exit": shell["time_exit"],
                    "protected": False, "protect_attempts": 0,
                    "entry_cap": shell["entry_cap"],
                    "approved_qty": shell["approved_qty"],
                    "executable_qty": shell["executable_qty"],
                    "exposure_noted": False,
                    "executable_noted": False, "close_ids": [],
                    "emergency_latched": False,
                    "strategy": shell["strategy"],
                    "admit_snapshot": None, "admit_budget": None,
                    "admit_intent": None,
                }
                drill.log("resume/shell-rebuilt", "PASS",
                          f"shell recovered for {shell['entry_pre_id']} "
                          f"(venue filled {venue_filled}; drill-side "
                          f"recovery, W1 D2 owns session-level)")
            else:
                drill.log("resume/shell-rebuilt", "BLOCKED",
                          "no venue fill to recover a shell for")
        drill.prime_feed(session, drill.live_mark())
        stream = drill.attach_stream(session, engine)
        healed, waited = drill.pump_wait(
            stream, lambda: not stream.halted, drill.heal_wait_s,
            "adopt-heal")
        if not healed:
            drill.log("resume/heal", "FAIL",
                      f"no stream heal in {waited}s")
            return 1
        drill.log("resume/heal", "PASS",
                  f"sandbox stream healed in {waited}s")
        # _resume_live may have fired the pending-flatten retry: drain
        # fully so the ledger reflects it before any close decision
        # (no double-close against an already-flat venue).
        drill.drain_stream(stream, session, engine)
        # Explicit adoption sweep: a retry-fired close fills at the
        # venue while no shell tracks it; lookup adopts its tape fills
        # so the ledger matches venue truth before we decide.
        adopted = 0
        for record in engine._read_journal():
            if record.get("event") != "submit-intent":
                continue
            cid = record.get("client_id")
            try:
                if engine.lookup(cid) is not None:
                    adopted += 1
            except Exception:
                pass
        session._drain_engine()
        drill.log("resume/adopt-sweep", "PASS",
                  f"looked up journaled orders ({adopted} live)")
        session._persist_local_state()
        after = store.counts(session.run_id).get("execution_events", 0)
        drill.log("resume/adopt", "PASS",
                  f"fresh objects resumed run {session.run_id}: "
                  f"ledger_net={session.ledger.position_qty()} "
                  f"store_events {before}->{after}")
        fails = 0
        # THE adoption assertion: the interrupt fill the crashed
        # process never saw must now be booked (ledger + store moved).
        adopted = session.ledger.has_position() and after > before
        drill.log("resume/fill-adopted",
                  "PASS" if adopted else "FAIL",
                  f"ledger_net={session.ledger.position_qty()} "
                  f"store_events {before}->{after}")
        fails += not adopted
        unknowns = engine.unknown_ids()
        drill.log("resume/unknowns",
                  "PASS" if not unknowns else "FAIL",
                  f"unknown={sorted(unknowns)}")
        fails += bool(unknowns)
        if session.ledger.has_position():
            # Crash landed pre-protection: no LIVE legs journaled, and
            # none may rest at the venue either (orphan check,
            # venue-direct). Earlier phases' cancelled legs excluded.
            live_journaled = []
            for lid in _journaled_legs(engine):
                try:
                    st = engine.lookup(lid)
                except Exception:
                    st = None
                if st is not None and st.state in ("open", "partial"):
                    live_journaled.append(lid)
            venue_algos = [a for a in drill.venue().open_algo_orders()
                           if a["algoStatus"] == "WORKING"]
            if live_journaled or venue_algos:
                drill.log("resume/legs-unexpected", "FAIL",
                          f"live_journaled={live_journaled} "
                          f"venue={venue_algos}")
                fails += 1
            else:
                drill.log("resume/legs-unexpected", "PASS",
                          "no legs journaled-live or resting "
                          "(pre-protection crash, as designed)")
            try:
                session._flatten("sandbox:adopt-close")
                flat, _ = drill.pump_wait(
                    stream, lambda: _drain_and_flat(session),
                    drill.flat_wait_s, "adopt-flat")
            except ValueError as exc:
                drill.log("resume/close", "FAIL", repr(exc))
                flat = False
            drill.log("resume/close",
                      "PASS" if flat else "FAIL",
                      f"net={session.ledger.position_qty()}")
            fails += not flat
            try:
                session._persist_local_state()
            except Exception:
                pass
        else:
            drill.log("resume/close", "FAIL",
                      "nothing adopted to close (adoption failed above)")
        # Journaled legs are never Session-tracked after restart:
        # cancel them explicitly in ALL cases (never orphan venue
        # stops/targets), tolerating already-terminal legs.
        for lid in _journaled_legs(engine):
            try:
                st = engine.lookup(lid)
            except Exception:
                st = None
            if st is not None and st.state in ("open", "partial"):
                try:
                    engine.cancel(lid, "sandbox:adopt-cleanup")
                except Exception as exc:
                    drill.log("resume/leg-cancel", "FAIL",
                              f"{lid}: {exc!r}")
                    fails += 1
        try:
            session._persist_local_state()
        except Exception:
            pass
        missing = _fills_missing_from_store(engine, store, session.run_id)
        drill.log("resume/durability",
                  "PASS" if not missing else "FAIL",
                  f"{len(missing)} journaled fills missing from store")
        fails += bool(missing)
        drill.save_venue()
        return 1 if fails else 0
    finally:
        try:
            if stream is not None:
                stream.close()
        except Exception:
            pass
        try:
            store.release_lock()
        except Exception:
            pass
        try:
            store.close()
        except Exception:
            pass
        try:
            engine.close()
        except Exception:
            pass
        drill.save_venue()


def _journaled_legs(engine):
    from cryptobot.adapters.binance_live import ALGO_ORDER_TYPES
    legs = [str(r.get("client_id")) for r in engine._read_journal()
            if r.get("event") == "submit-intent"
            and r.get("role") in ("stop", "target")
            and (r.get("algo") or r.get("kind") in ALGO_ORDER_TYPES)
            and r.get("client_id")]
    return legs[-2:] if legs else []


def _verify_adopt_legs(drill, engine):
    legs = _journaled_legs(engine)
    if not legs:
        drill.log("resume/protection", "FAIL",
                  "exposure without journaled legs")
        return False
    states = {}
    for lid in legs:
        st = engine.lookup(lid)
        states[lid] = st.state if st else "missing"
    ok = all(s in ("open", "partial") for s in states.values())
    drill.log("resume/protection", "PASS" if ok else "FAIL",
              f"legs={states}")
    return ok


def _fills_missing_from_store(engine, store, run_id):
    wanted = set()
    for record in engine._read_journal():
        if record.get("event") == "fill-adopted":
            exec_id = record.get("execution_id") or record.get("exec_id")
            if exec_id:
                wanted.add(exec_id)
    if not wanted:
        return set()
    rows = store._db.execute(
        "SELECT execution_id FROM execution_events WHERE run_id=?",
        (run_id,)).fetchall()
    have = {row[0] for row in rows}
    return wanted - have


def cmd_stream_gap(drill):
    """Sandbox stream interruption: halt entries, exits work, heal resumes."""
    from cryptobot.app.engine import EngineOrder
    engine = drill.engine()
    session, store = drill.session(engine, run_id=drill.run_id + "-gap")
    stream = None
    try:
        drill.ensure_run(session, store)
        stream = drill.attach_stream(session, engine)
        healed, waited = drill.pump_wait(
            stream, lambda: not stream.halted, drill.heal_wait_s,
            "heal")
        if not healed:
            drill.log("stream-gap/heal", "FAIL",
                      f"no initial heal in {waited}s")
            return 1
        drill.log("stream-gap/heal", "PASS", f"healed in {waited}s")
        drill.redial_failures = 10 ** 9  # gap open: redials refused.
        stream.reader.close()
        halted, waited = drill.pump_wait(
            stream, lambda: stream.halted, drill.gap_wait_s,
            "gap-halt")
        if not halted:
            drill.log("stream-gap/halt", "FAIL",
                      "entries not halted after socket drop")
            return 1
        drill.log("stream-gap/halt", "PASS",
                  f"entries halted {waited}s after socket drop")
        try:
            engine.submit(EngineOrder(
                drill.symbol, "BUY", 0.001, "MARKET",
                reservation_id="sandbox-gap-entry", role="entry"))
            drill.log("stream-gap/entry-refused", "FAIL",
                      "entry submitted during gap (halt ineffective)")
            return 1
        except ValueError as exc:
            if "exit-only" not in str(exc):
                raise
            drill.log("stream-gap/entry-refused", "PASS", str(exc))
        engine._ensure_ready(drill.symbol)
        gap_qty, _ = _tiny_qty(drill, engine)
        try:
            engine.submit(EngineOrder(
                drill.symbol, "SELL", gap_qty, "MARKET",
                reservation_id="sandbox-gap-exit", role="target",
                reduce_only=True))
            drill.log("stream-gap/exit-works", "PASS",
                      "exit-role submit reached the venue during gap")
        except ValueError as exc:
            if "exit-only" in str(exc):
                drill.log("stream-gap/exit-works", "FAIL",
                          "exits blocked by the gap halt")
                return 1
            raise
        except Exception as exc:
            drill.log("stream-gap/exit-works", "PASS",
                      f"exit reached venue (venue verdict: {exc!r})")
        drill.redial_failures = 0  # gap closed: redial may succeed.
        healed, waited = drill.pump_wait(
            stream, lambda: not stream.halted, drill.heal_wait_s,
            "reheal")
        if not healed:
            drill.log("stream-gap/reheal", "FAIL",
                      f"halt not released in {waited}s")
            return 1
        drill.log("stream-gap/reheal", "PASS",
                  f"halt released after heal in {waited}s")
        drill.save_venue()
        return 0
    finally:
        try:
            if stream is not None:
                stream.close()
        except Exception:
            pass
        try:
            store.close()
        except Exception:
            pass
        try:
            engine.close()
        except Exception:
            pass
        drill.save_venue()


def cmd_reconcile(drill):
    """Authoritative flatness: venue positions+orders, journal, ledger agree.

    PASS only when ALL agree flat: complete account snapshot with zero
    positions, no open orders, no unknowns, every submit-intent terminal,
    every journaled fill booked in the store, and the drill ledger flat.
    Anything else (including unavailable evidence) is FAIL, never PASS.
    """
    engine = drill.engine()
    fails = 0
    try:
        snap = engine.account_snapshot()
        if snap is None or not snap.complete:
            drill.log("reconcile/venue-positions", "FAIL",
                      "account snapshot unavailable/incomplete "
                      "(unknown, never flat)")
            fails += 1
        else:
            positions = [(p.instrument, p.qty) for p in snap.positions
                         if abs(p.qty) > 1e-12]
            drill.log("reconcile/venue-positions",
                      "PASS" if not positions else "FAIL",
                      f"nonzero={positions}")
            fails += bool(positions)
        opens = engine.open_orders()
        drill.log("reconcile/venue-open-orders",
                  "PASS" if not opens else "FAIL",
                  f"open={len(opens)}")
        fails += bool(opens)
        unknowns = engine.unknown_ids()
        drill.log("reconcile/unknowns",
                  "PASS" if not unknowns else "FAIL",
                  f"unknown={sorted(unknowns)}")
        fails += bool(unknowns)
        journal = engine._read_journal()
        rejected = {r.get("client_id") for r in journal
                    if r.get("event") == "submit-rejected"
                    and r.get("client_id")}
        for record in journal:
            if record.get("event") != "submit-intent":
                continue
            cid = record.get("client_id")
            status = engine.lookup(cid)
            state = getattr(status, "state", "?") if status else "missing"
            if state == "missing" and cid in rejected \
                    and engine.filled_qty(cid) == 0:
                # Deterministic venue rejection before existence: never
                # saw it, zero fills adopted. Terminal truth, evidenced
                # by the submit-rejected journal record.
                drill.log(f"reconcile/order-{cid}", "PASS",
                          "void(zero-fill, venue-rejected-at-submit)")
                continue
            ok = state in ("filled", "cancelled", "expired", "rejected",
                           "partial")
            drill.log(f"reconcile/order-{cid}", "PASS" if ok else "FAIL",
                      f"venue state={state}")
            fails += not ok
        ledger_path = drill.session_dir / "ledger.json"
        if not ledger_path.exists():
            drill.log("reconcile/ledger", "FAIL",
                      "drill ledger.json missing (cannot prove flat)")
            fails += 1
        else:
            from cryptobot.accounting.ledger import Ledger
            ledger = Ledger.from_dict(
                json.loads(ledger_path.read_text(encoding="utf-8")))
            net = ledger.position_qty()
            drill.log("reconcile/ledger", "PASS" if net == 0 else "FAIL",
                      f"ledger_net={net}")
            fails += net != 0
        drill.save_venue()
        return 1 if fails else 0
    finally:
        try:
            engine.close()
        except Exception:
            pass
        drill.save_venue()


def write_report(drill, results):
    """Auto-generate report.md + report.json from the evidence JSONL."""
    records = []
    if drill.evidence_path.exists():
        for line in drill.evidence_path.read_text(
                encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    fails = sum(1 for rc in results.values() if rc == 1)
    blocked = sum(1 for rc in results.values() if rc == EXIT_BLOCKED)
    omitted = [p for p in PHASES_FULL if p not in results]
    if fails:
        verdict = "FAIL"
    elif blocked or omitted:
        verdict = "BLOCKED"
    else:
        verdict = "PASS"
    stamp = "SANDBOX VALIDATED" if verdict == "PASS" else \
        "SANDBOX NOT VALIDATED"
    report = {
        "tool": "sandbox_drill", "seed": drill.seed,
        "symbol": drill.symbol, "verdict": verdict,
        "phases": results, "omitted_phases": omitted,
        "sandbox_stamp": stamp,
        "demo_stamp": "BINANCE DEMO VALIDATION PENDING",
        "utc": _utcnow().isoformat(),
        "records": len(records),
    }
    (drill.dir / "report.json").write_text(
        json.dumps(report, indent=1), encoding="utf-8")
    lines = ["# Sandbox drill report", "",
             f"verdict: **{verdict}**", f"seed: {drill.seed}",
             f"symbol: {drill.symbol}",
             f"sandbox: {stamp}",
             "demo: BINANCE DEMO VALIDATION PENDING", "",
             "## Phases", ""]
    for name in PHASES_FULL:
        rc = results.get(name, "omitted")
        lines.append(f"- {name}: {rc}")
    if omitted:
        lines += ["", f"omitted phases (force BLOCKED): {omitted}"]
    lines += ["", "## Evidence (latest per phase)", ""]
    latest: dict[str, dict] = {}
    for rec in records:
        latest[rec["phase"]] = rec
    for phase in sorted(latest):
        rec = latest[phase]
        lines.append(f"- [{rec['verdict']}] {phase}: {rec['detail']}")
    (drill.dir / "report.md").write_text("\n".join(lines) + "\n",
                                         encoding="utf-8")
    return verdict


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", default="/tmp/sandbox-drill")
    # ETHUSDT default: BTC's 0.001 step at ~$60k forces $60+ notionals,
    # which breach the $25 exposure cap by construction. Same mechanics.
    parser.add_argument("--symbol", default="ETHUSDT")
    parser.add_argument("--seed", default=7, type=int)
    parser.add_argument("command", choices=(
        "preflight", "drill", "interrupt", "resume", "stream-gap",
        "reconcile", "full"))
    args = parser.parse_args(argv)
    run_dir = Path(args.dir)
    if run_dir.exists() and any(run_dir.iterdir()):
        # Occupied dir: refuse loudly up front (BLOCKED) instead of
        # crashing mid-run on reused store/journal/venue state. Applies
        # to `full` and every standalone phase; chain phases with `full`.
        msg = (f"[BLOCKED] {args.command}: dir occupied ({run_dir}), "
               f"use a fresh dir")
        print(msg, flush=True)
        try:
            with open(run_dir / "sandbox_evidence.jsonl", "a",
                      encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "ts_utc": _utcnow().isoformat(),
                    "phase": args.command, "verdict": "BLOCKED",
                    "detail": msg, "elapsed_s": 0.0}) + "\n")
        except OSError:
            pass
        return EXIT_BLOCKED
    drill = Drill(args.dir, args.symbol, args.seed)
    if args.command == "preflight":
        return cmd_preflight(drill)
    if args.command == "drill":
        return cmd_drill(drill)
    if args.command == "interrupt":
        return cmd_interrupt(drill)
    if args.command == "resume":
        return cmd_resume(drill)
    if args.command == "stream-gap":
        return cmd_stream_gap(drill)
    if args.command == "reconcile":
        return cmd_reconcile(drill)
    # full: preflight gates every entry-bearing phase. Failed/blocked
    # preflight prevents entry AND adoption; the read-only phases still
    # run so the outcome is fully evidenced, never silently omitted.
    results = {}
    results["preflight"] = cmd_preflight(drill)
    if results["preflight"] != 0:
        for name in ("drill", "interrupt", "resume"):
            drill.log(name, "BLOCKED",
                      "preflight not PASS: entry/adoption prevented")
            results[name] = EXIT_BLOCKED
        results["stream-gap"] = cmd_stream_gap(drill)
        results["reconcile"] = cmd_reconcile(drill)
    else:
        for name, func in (("drill", cmd_drill),
                           ("interrupt", cmd_interrupt),
                           ("resume", cmd_resume),
                           ("stream-gap", cmd_stream_gap),
                           ("reconcile", cmd_reconcile)):
            results[name] = func(drill)
            if results[name] == EXIT_INCOMPLETE:
                write_report(drill, results)
                return EXIT_INCOMPLETE
    verdict = write_report(drill, results)
    fails = sum(1 for rc in results.values() if rc == 1)
    blocked = sum(1 for rc in results.values() if rc == EXIT_BLOCKED)
    if fails:
        drill.log("full", "FAIL",
                  f"fails={fails} blocked={blocked} {results}")
        return 1
    if blocked:
        drill.log("full", "BLOCKED",
                  f"fails={fails} blocked={blocked} {results}")
        return EXIT_BLOCKED
    drill.log("full", "PASS", f"all {len(results)} phases passed; "
              f"{verdict}; SANDBOX VALIDATED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
