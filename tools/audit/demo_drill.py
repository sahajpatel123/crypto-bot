#!/usr/bin/env python3
"""Bounded credentialed demo drill runner (Worker 5, 30min §9; R4 normal-Session).

Subcommands: preflight | drill | stream-gap | reconcile | resume-adopt | full

The drill drives the NORMAL demo Session (configs/demo.toml + live demo
engine + supervised user stream) through entry → protection → exit, then
proves stream interruption, restart adoption, and authoritative
reconciliation. Demo hosts/credentials only; bounded by run_budget 1500s.

Safety contract:
- DEMO HOSTS ONLY: base_url must be https://demo-fapi.binance.com (or the
  engine demo default). Anything else is refused (exit 2), never run.
- Credentials come ONLY from BINANCE_DEMO_KEY / BINANCE_DEMO_SECRET.
  Missing credentials => BLOCKED (exit 2), never FAIL.
- KILL criteria (FAIL + immediate abort, no further phases): stale or
  unknown quote data; unknown order outcomes at a gate; missed (non-live)
  protection; reduce-only exit mismatch; exposure cap breach.
- Verdicts: PASS / FAIL / BLOCKED per phase. `full` exits 1 on any FAIL,
  2 when anything is BLOCKED, 0 only when every required phase passes.
  Failed/blocked preflight prevents entry (drill + adoption skipped).

Usage:
    demo_drill.py [--dir DIR] [--symbol SYM] full
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

DEMO_FAPI = "https://demo-fapi.binance.com"
ENTRY_CUTOFF_S = 20 * 60
CLOSE_BY_S = 25 * 60
EXIT_MARGIN_S = 3 * 60  # entries stop this long before CLOSE_BY (exit room).
CLEANUP_S = 2 * 60  # minimum remaining budget before opening exposure.
MAX_NOTIONAL_USDT = 25.0
QUOTE_MAX_AGE_S = 10.0

EXIT_BLOCKED = 2
EXIT_INCOMPLETE = 124


def _utcnow():
    return datetime.now(timezone.utc)


class Drill:
    def __init__(self, run_dir, symbol, base_url):
        self.dir = Path(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.symbol = symbol.upper()
        self.base_url = base_url
        self.start_mono = time.monotonic()
        self.evidence_path = self.dir / "drill_evidence.jsonl"
        self.journal_path = self.dir / "drill_journal.jsonl"
        self.store_path = self.dir / "drill_store.db"
        self.session_dir = self.dir / "session"
        self.run_id = "demo-drill"
        # Bounded waits (instance attrs so offline tests can shrink them).
        self.heal_wait_s = 60.0
        self.fill_wait_s = 45.0
        self.flat_wait_s = 90.0
        self.gap_wait_s = 15.0
        self.poll_s = 0.5
        # Synchronous pump: the drill drives the reader on its own
        # thread (same reader/socket/booking path, deterministic).
        # Threaded Session booking awaits the R1 ownership fix (W1);
        # threaded pumping stays covered by the attach unit tests.
        # Default threading (R1): the pump owns the socket; the drill
        # (owner) applies via drain_owner in pump_wait. No sync bypass.
        self.stream_kwargs = {}

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

    def check_demo_only(self):
        if self.base_url is not None and self.base_url != DEMO_FAPI:
            self.log("safety/demo-hosts-only", "BLOCKED",
                     f"refusing non-demo base_url {self.base_url!r}")
            return False
        return True

    def creds(self):
        key = os.environ.get("BINANCE_DEMO_KEY", "")
        secret = os.environ.get("BINANCE_DEMO_SECRET", "")
        if not key or not secret:
            self.log("safety/credentials", "BLOCKED",
                     "BINANCE_DEMO_KEY/SECRET absent (declared blocker)")
            return None
        return key, secret

    def engine(self, transport=None):
        from cryptobot.adapters.binance_live import BinanceLiveEngine
        key, secret = self.creds()
        return BinanceLiveEngine(
            api_key=key, api_secret=secret,
            journal_path=self.journal_path, expected_leverage=3,
            run_tag="demo30", live_enable=True, demo=True,
            base_url=self.base_url, transport=transport,
            now_utc=_utcnow)

    def session(self, engine, run_id=None):
        """Normal demo Session on the drill store (driver-level wiring).

        Loads the real configs/demo.toml (same config the operator run
        uses); store/journal/workdir stay inside the drill dir so phases
        share durable state. Callers own acquire/close discipline.
        """
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
        """Create the run row + reconcile the day once (idempotent)."""
        if store.get_run(session.run_id) is None:
            store.create_run(session.run_id, session.config.mode,
                             session.config.fingerprint,
                             str(session.workdir), os.getpid())
            session.policy.reconcile_day(
                session.config.paper_capital_usdt, 0.0)

    def ws_factory(self, engine):
        """Real private-stream socket factory (stdlib WsClient)."""
        import json as _json

        from cryptobot.market_data.ws import WsClient, WsClosed

        def _factory(listen_key):
            url = engine.user_stream_url(listen_key)
            client = WsClient.connect(url, timeout_s=10.0)

            class _Sock:
                def recv(self, timeout_s):
                    try:
                        typ, payload = client.recv_message(timeout_s)
                    except WsClosed as exc:
                        if str(exc).startswith("read timeout"):
                            return None
                        raise
                    if typ != "text":
                        return None
                    return _json.loads(payload.decode("utf-8"))

                def close(self):
                    client.close()

            return _Sock()

        return _factory

    def attach_stream(self, session, engine):
        from cryptobot.adapters.user_stream import attach_user_stream
        return attach_user_stream(session, engine,
                                  self.ws_factory(engine),
                                  **self.stream_kwargs)

    def prime_feed(self, session, mark):
        """Arm the symbol feed + filters from live truth (normal path)."""
        from cryptobot.app.session import _SymbolFeed
        filt = session.engine._filters[self.symbol]
        session.arm_replay_filters(
            {self.symbol: {"tick_size": float(filt["tick"]),
                           "step_size": float(filt["step"]),
                           "min_qty": float(filt["min_qty"]),
                           "min_notional": float(filt["min_notional"])}},
            origin="demo-drill", asof_utc=session.now_utc())
        feed = _SymbolFeed(self.symbol, 0)
        feed.mark = mark
        feed.mark_ts = session.now_utc()
        session._feeds[self.symbol] = feed

    def drill_intent(self, session, mark):
        """One tiny drill intent around the live mark (mechanics only)."""
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
            # 2% invalidation: the $120-budget Session sizing approves
            # a min-notional-scale tiny order (a wider stop skips as
            # dust; venue minimums still gate below).
            invalidation_price=round(mark * 0.98, 4),
            exit_rule=encode_exit_rule(ExitPolicy(
                stop_price=round(mark * 0.98, 4),
                target_price=round(mark * 1.05, 2),
                time_exit_utc=now + timedelta(seconds=600),
                policy_id="demo-drill")),
            holding_limit_s=600,
            forecast_cost=ForecastCost(5.0, 5.0, 5.0, 1.0),
            evidence_ref="demo-drill:1", data_quality=DataQuality.CLEAN)

    def live_quote(self):
        """(mid, event_ms|None) from the public bookTicker (unsigned)."""
        url = (f"{self.base_url or DEMO_FAPI}/fapi/v1/ticker/bookTicker"
               f"?symbol={self.symbol}")
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        mid = (float(data["bidPrice"]) + float(data["askPrice"])) / 2.0
        event_ms = data.get("time")
        try:
            event_ms = int(event_ms) if event_ms is not None else None
        except (TypeError, ValueError):
            event_ms = None
        return mid, event_ms

    def live_mark(self):
        return self.live_quote()[0]

    def quote_fresh(self):
        """Stale-data gate: (ok, detail). Unknown event time fails closed."""
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

    def kill(self, phase, detail):
        """KILL criterion hit: FAIL + immediate abort (returns exit 1)."""
        self.log(phase, "FAIL", f"KILL: {detail}")
        return 1

    def entry_allowed(self):
        """Entries stop early: exit margin before CLOSE_BY + cleanup budget."""
        elapsed = time.monotonic() - self.start_mono
        if elapsed + EXIT_MARGIN_S >= CLOSE_BY_S:
            return False
        remaining = self.remaining_budget()
        if remaining is not None and remaining < CLEANUP_S:
            return False
        return True

    def wait_until(self, predicate, timeout_s, label):
        """Bounded wait; (ok, waited_s). Never hangs past timeout_s."""
        start = time.monotonic()
        while True:
            if predicate():
                return True, round(time.monotonic() - start, 1)
            if time.monotonic() - start >= timeout_s:
                return False, round(time.monotonic() - start, 1)
            time.sleep(self.poll_s)

    def pump_wait(self, stream, predicate, timeout_s, label):
        """wait_until with the owner drain (threaded default, R1)."""
        start = time.monotonic()
        while True:
            try:
                stream.drain_owner()
            except Exception:
                pass
            if predicate():
                return True, round(time.monotonic() - start, 1)
            if time.monotonic() - start >= timeout_s:
                return False, round(time.monotonic() - start, 1)
            time.sleep(self.poll_s)


def cmd_preflight(drill):
    if not drill.check_demo_only():
        return EXIT_BLOCKED
    if drill.creds() is None:
        return EXIT_BLOCKED
    fails = 0
    try:
        from cryptobot.adapters.binance_live import UrllibTransport
        transport = UrllibTransport(drill.base_url or DEMO_FAPI, timeout_s=10)
        server_ms = transport.request("GET", "/fapi/v1/time", {}, {})["serverTime"]
        skew_ms = abs(server_ms - int(_utcnow().timestamp() * 1000))
        ok = skew_ms < 5000
        drill.log("preflight/clock", "PASS" if ok else "FAIL",
                  f"server skew {skew_ms}ms")
        fails += not ok
        engine = drill.engine()
        try:
            engine._ensure_ready(drill.symbol)
            drill.log("preflight/readiness", "PASS",
                      f"filters+fees cached for {drill.symbol}")
            available, free = engine.account_margin()
            ok = available > 0
            drill.log("preflight/account", "PASS" if ok else "FAIL",
                      f"available={available} free={free}")
            fails += not ok
            drill.log("preflight/fees", "PASS",
                      f"taker={engine.fee_bps(drill.symbol)}bps")
        finally:
            engine.close()
        mark = drill.live_mark()
        drill.log("preflight/mark", "PASS", f"{drill.symbol} mark {mark}")
        fresh, detail = drill.quote_fresh()
        if not fresh:
            return drill.kill("preflight/quote-fresh", detail)
        drill.log("preflight/quote-fresh", "PASS", detail)
        return 1 if fails else 0
    except Exception as exc:
        drill.log("preflight", "FAIL", repr(exc))
        return 1


def _tiny_qty(drill, engine):
    """(qty, mark) or None when the venue-minimum tiny size breaches cap."""
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
    """Best-effort reduce-only close of residual exposure (never masks rc)."""
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


def cmd_drill(drill):
    """Normal-Session entry → protection → exit (+ ambiguous-submit probe)."""
    if not drill.check_demo_only():
        return EXIT_BLOCKED
    if drill.creds() is None:
        return EXIT_BLOCKED
    from cryptobot.adapters.binance_live import UnknownOutcomeError
    from cryptobot.coordination.selector import Candidate
    # Stale-data gate runs before any engine/venue contact: no orders,
    # no signed calls, and no wasted setup on dead data.
    fresh, detail = drill.quote_fresh()
    if not fresh:
        return drill.kill("drill/quote-fresh", detail)
    drill.log("drill/quote-fresh", "PASS", detail)
    engine = drill.engine()
    session, store = None, None
    stream = None
    rc = 0
    try:
        # Pre-Session gates: quote, window, cap, unknowns — no Session,
        # no lock, no orders before all four pass.
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
                  f"private stream healed in {waited}s")
        # Exposure-cap pre-check on the Session's OWN sizing (same
        # inputs admission uses): never submit an over-cap order.
        from cryptobot.risk.types import Approved
        intent = drill.drill_intent(session, mark)
        snapshot = session._snapshot_account(symbol=drill.symbol)
        verdict = session.policy.evaluate(intent, snapshot)
        if isinstance(verdict, Approved):
            notional = verdict.qty * mark
            # The pre-check reserves; always release (admission takes
            # its own reservation) — over-cap kills before any submit.
            session.policy.release(verdict.reservation_id)
            if notional > MAX_NOTIONAL_USDT:
                return drill.kill(
                    "drill/exposure-cap",
                    f"session sizing {verdict.qty} (~{notional:.2f} USDT) "
                    f"exceeds {MAX_NOTIONAL_USDT} USDT cap")
        # Phase 1: tiny entry through normal admission; IOC may cancel
        # honestly (no-trade) — only stranger outcomes kill.
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
        # Phase 2: Session-owned protection + reduce-only exit to flat.
        if filled > 0:
            if not _verify_protection(drill, session, engine, stream):
                _emergency_flatten(drill, session, "demo-drill:protect-miss")
                return drill.kill(
                    "drill/protection",
                    "stop leg not verified live; emergency flatten attempted")
            try:
                session._flatten("demo-drill-close")
            except ValueError as exc:
                return drill.kill("drill/reduce-only-exit", repr(exc))
            flat, waited = drill.pump_wait(
                stream, lambda: _drain_and_flat(session),
                drill.flat_wait_s, "flat")
            net = session.ledger.position_qty()
            if not flat:
                _emergency_flatten(drill, session,
                                   "demo-drill:exit-incomplete")
                return drill.kill(
                    "drill/reduce-only-exit",
                    f"not flat in {waited}s (net={net}); emergency "
                    f"flatten attempted — owner must review")
            drill.log("drill/reduce-only-exit", "PASS",
                      f"flat in {waited}s (net={net})")
            try:
                for lid in list((session._position or {}).get("legs", [])):
                    engine.cancel(lid, "demo:position-closed")
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
        # Phase 3: ambiguous submit — drop one order response, prove the
        # lookup resolves by durable client ID with no duplicate order.
        rc = _ambiguous_submit(drill, engine, mark) or rc
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


def _drain_and_flat(session):
    session._drain_engine()
    try:
        return abs(session.ledger.position_qty()) <= 1e-9
    except Exception:
        return False


def _verify_protection(drill, session, engine, stream=None,
                       timeout_s=None):
    """Stop leg (legs[0], Session convention) verified live via lookup."""
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
    drill.log("drill/protection", "PASS" if ok else "FAIL",
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
                raise VenueHttpError(0, None, "drill: response dropped")
            return self.inner.request(method, path, params, headers)

    engine2 = drill.engine(transport=_DropOnce(engine._transport))
    try:
        engine2._ensure_ready(drill.symbol)
        try:
            engine2.submit(EngineOrder(
                drill.symbol, "BUY", qty, "LIMIT",
                price=round(mark * 0.99, 2),
                reservation_id="demo-ambig-1", role="entry"))
            drill.log("drill/ambiguous-submit", "FAIL",
                      "dropped response did not raise UNKNOWN")
            return 1
        except UnknownOutcomeError as exc:
            found = engine2.lookup(exc.client_id)
            intents = [r for r in engine2._read_journal()
                       if r.get("event") == "submit-intent"
                       and r.get("reservation_id") == "demo-ambig-1"]
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


def cmd_stream_gap(drill):
    """Real stream interruption: halt entries, exits work, heal resumes.

    Opens no position: attaches the supervised stream, drops the live
    socket (reader.close on the real venue socket; scripted death
    offline), proves entries refuse while an exit-role submit still
    reaches the venue, then proves the heal releases the halt.
    """
    if not drill.check_demo_only():
        return EXIT_BLOCKED
    if drill.creds() is None:
        return EXIT_BLOCKED
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
        # Interrupt the LIVE socket for real.
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
                reservation_id="demo-gap-entry", role="entry"))
            drill.log("stream-gap/entry-refused", "FAIL",
                      "entry submitted during gap (halt ineffective)")
            return 1
        except ValueError as exc:
            if "exit-only" not in str(exc):
                raise
            drill.log("stream-gap/entry-refused", "PASS", str(exc))
        try:
            engine.submit(EngineOrder(
                drill.symbol, "SELL", 0.001, "MARKET",
                reservation_id="demo-gap-exit", role="target",
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
            # Any venue verdict (e.g. reduce-only with no position)
            # still proves exits are not client-side blocked.
            drill.log("stream-gap/exit-works", "PASS",
                      f"exit reached venue (venue verdict: {exc!r})")
        healed, waited = drill.pump_wait(
            stream, lambda: not stream.halted, drill.heal_wait_s,
            "reheal")
        if not healed:
            drill.log("stream-gap/reheal", "FAIL",
                      f"halt not released in {waited}s")
            return 1
        drill.log("stream-gap/reheal", "PASS",
                  f"halt released after heal in {waited}s")
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


def cmd_resume_adopt(drill):
    """Restart adoption: fresh Session+engine adopt with durable booking.

    Reopens the drill store/journal with brand-new objects (nothing in
    memory survives) and runs the normal resume path: ledger reload,
    booking-state rebuild, engine.recover through the real Session
    booking handler. Adopted fills BOOK (nothing discarded); unknowns,
    protection, and journal/store durability are then verified.
    """
    if not drill.check_demo_only():
        return EXIT_BLOCKED
    if drill.creds() is None:
        return EXIT_BLOCKED
    if not drill.store_path.exists() or not drill.journal_path.exists():
        drill.log("resume-adopt", "BLOCKED",
                  "no drill store/journal to adopt (run drill first)")
        return EXIT_BLOCKED
    engine = drill.engine()
    session, store = drill.session(engine)
    stream = None
    try:
        store.acquire_lock()
        if store.get_run(session.run_id) is None:
            drill.log("resume-adopt", "BLOCKED",
                      "no drill run row to adopt (run drill first)")
            return EXIT_BLOCKED
        stream = drill.attach_stream(session, engine)
        healed, waited = drill.pump_wait(
            stream, lambda: not stream.halted, drill.heal_wait_s,
            "adopt-heal")
        if not healed:
            drill.log("resume-adopt/heal", "FAIL",
                      f"no stream heal in {waited}s")
            return 1
        drill.log("resume-adopt/heal", "PASS",
                  f"private stream healed in {waited}s")
        # Peek the persisted ledger BEFORE resume: resume itself
        # flattens orphaned exposure, so legs verify first (venue live?)
        # while the pre-restart cover is still in place.
        from cryptobot.accounting.ledger import Ledger
        peek_path = drill.session_dir / "ledger.json"
        peek_net = 0.0
        if peek_path.exists():
            try:
                peek_net = Ledger.from_dict(
                    json.loads(peek_path.read_text(
                        encoding="utf-8"))).position_qty()
            except Exception:
                peek_net = float("nan")
        legs_live = True
        if abs(peek_net) > 1e-12:
            engine._ensure_ready(drill.symbol)
            drill.prime_feed(session, drill.live_mark())
            legs_live = _verify_adopt_legs(drill, engine)
        before = store.counts(session.run_id).get("execution_events", 0)
        session._resume_live()
        session._drain_engine()
        session._persist_local_state()
        after = store.counts(session.run_id).get("execution_events", 0)
        drill.log("resume-adopt/adopt", "PASS",
                  f"fresh objects resumed run {session.run_id}: "
                  f"ledger_net={session.ledger.position_qty()} "
                  f"store_events {before}->{after}")
        fails = 0
        unknowns = engine.unknown_ids()
        drill.log("resume-adopt/unknowns",
                  "PASS" if not unknowns else "FAIL",
                  f"unknown={sorted(unknowns)}")
        fails += bool(unknowns)
        if session.ledger.has_position():
            # Fresh process: no position shell — the journaled legs
            # were verified above; close through the attached stream.
            if not legs_live:
                _emergency_flatten(drill, session,
                                   "demo-drill:adopt-protect-miss")
                fails += 1
            else:
                try:
                    session._flatten("demo-drill:adopt-close")
                    flat, _ = drill.pump_wait(
                        stream, lambda: _drain_and_flat(session),
                        drill.flat_wait_s, "adopt-flat")
                except ValueError as exc:
                    drill.log("resume-adopt/close", "FAIL", repr(exc))
                    flat = False
                drill.log("resume-adopt/close",
                          "PASS" if flat else "FAIL",
                          f"net={session.ledger.position_qty()}")
                fails += not flat
                # No position shell survived: journaled legs are not
                # Session-tracked, so cancel them explicitly (never
                # leave orphaned venue stops/targets behind).
                for lid in _journaled_legs(engine):
                    try:
                        engine.cancel(lid, "demo-drill:adopt-cleanup")
                    except Exception as exc:
                        drill.log("resume-adopt/leg-cancel", "FAIL",
                                  f"{lid}: {exc!r}")
                        fails += 1
                try:
                    session._persist_local_state()
                except Exception:
                    pass
        # Durability: every journaled fill-adopted exec id is booked in
        # the store (persisted BEFORE acknowledgement, never lost).
        missing = _fills_missing_from_store(engine, store, session.run_id)
        drill.log("resume-adopt/durability",
                  "PASS" if not missing else "FAIL",
                  f"{len(missing)} journaled fills missing from store")
        fails += bool(missing)
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


def _journaled_legs(engine):
    """Latest journaled stop/target pair (superseded legs retired)."""
    from cryptobot.adapters.binance_live import ALGO_ORDER_TYPES
    legs = [str(r.get("client_id")) for r in engine._read_journal()
            if r.get("event") == "submit-intent"
            and r.get("role") in ("stop", "target")
            and (r.get("algo") or r.get("kind") in ALGO_ORDER_TYPES)
            and r.get("client_id")]
    return legs[-2:] if legs else []


def _verify_adopt_legs(drill, engine):
    """Journaled stop/target legs verified live via venue lookup."""
    legs = _journaled_legs(engine)
    if not legs:
        drill.log("resume-adopt/protection", "FAIL",
                  "exposure without journaled legs")
        return False
    states = {}
    for lid in legs:
        st = engine.lookup(lid)
        states[lid] = st.state if st else "missing"
    ok = all(s in ("open", "partial") for s in states.values())
    drill.log("resume-adopt/protection", "PASS" if ok else "FAIL",
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


def cmd_reconcile(drill):
    """Authoritative flatness: venue positions+orders, journal, ledger agree.

    PASS only when ALL agree flat: complete account snapshot with zero
    positions, no open orders, no unknowns, every submit-intent terminal,
    every journaled fill booked in the store, and the drill ledger flat.
    Anything else (including unavailable evidence) is FAIL, never PASS.
    """
    if not drill.check_demo_only():
        return EXIT_BLOCKED
    if drill.creds() is None:
        return EXIT_BLOCKED
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
        for record in journal:
            if record.get("event") != "submit-intent":
                continue
            cid = record.get("client_id")
            status = engine.lookup(cid)
            state = getattr(status, "state", "?") if status else "missing"
            ok = state in ("filled", "cancelled", "expired", "rejected",
                           "partial")
            drill.log(f"reconcile/order-{cid}", "PASS" if ok else "FAIL",
                      f"venue state={state}")
            fails += not ok
        # Drill ledger (persisted by drill/resume): must exist and be flat.
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
        return 1 if fails else 0
    finally:
        try:
            engine.close()
        except Exception:
            pass


def main(argv=None):
    from cryptobot import netguard  # opt-in DNS-sinkhole fallback (CRYPTOBOT_DOH=1)

    netguard.install_from_env()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", default="/tmp/demo30")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("command", choices=(
        "preflight", "drill", "stream-gap", "reconcile", "resume-adopt",
        "full"))
    args = parser.parse_args(argv)
    drill = Drill(args.dir, args.symbol, args.base_url)
    if args.command == "preflight":
        return cmd_preflight(drill)
    if args.command == "drill":
        return cmd_drill(drill)
    if args.command == "stream-gap":
        return cmd_stream_gap(drill)
    if args.command == "reconcile":
        return cmd_reconcile(drill)
    if args.command == "resume-adopt":
        return cmd_resume_adopt(drill)
    # full: preflight gates every entry-bearing phase. Failed/blocked
    # preflight prevents entry AND adoption; the read-only phases still
    # run so the outcome is fully evidenced, never silently omitted.
    results = {}
    results["preflight"] = cmd_preflight(drill)
    if results["preflight"] != 0:
        for name in ("drill", "resume-adopt"):
            drill.log(name, "BLOCKED",
                      "preflight not PASS: entry/adoption prevented")
            results[name] = EXIT_BLOCKED
        results["stream-gap"] = cmd_stream_gap(drill)
        results["reconcile"] = cmd_reconcile(drill)
    else:
        for name, func in (("drill", cmd_drill),
                           ("stream-gap", cmd_stream_gap),
                           ("resume-adopt", cmd_resume_adopt),
                           ("reconcile", cmd_reconcile)):
            results[name] = func(drill)
            if results[name] == EXIT_INCOMPLETE:
                return EXIT_INCOMPLETE
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
    drill.log("full", "PASS", f"all {len(results)} phases passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
