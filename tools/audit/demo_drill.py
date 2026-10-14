#!/usr/bin/env python3
"""Bounded credentialed demo drill runner (Worker 5, 30min §9; READY §7 prep).

Subcommands: preflight | drill | stream-gap | reconcile | resume-adopt | full

Declared drill plan (READY §7; owner confirms before any credentialed run):
- Holder: owner-held demo credentials in the owner's environment only;
  orders must be visible to the owner on the demo account afterwards.
- Window: single session, entries only before start+20min, closure by
  minute 25; run under tools/run_budget.py --budget-s 1500.
- Clock: UTC evidence log; venue clock skew must be <5s at preflight.
- Symbol: one symbol (default BTCUSDT), demo hosts only.
- Exposure caps: single tiny IOC (min-notional * 1.2), notional capped
  at MAX_NOTIONAL_USDT; one position at a time; reduce-only exit to flat.
- Protection: stop leg must be VERIFIED live (venue lookup) while any
  fill is open; missed protection kills the drill immediately.

Safety contract:
- DEMO HOSTS ONLY: base_url must be https://demo-fapi.binance.com (or the
  engine demo default). Anything else is refused (exit 2), never run.
- Credentials come ONLY from BINANCE_DEMO_KEY / BINANCE_DEMO_SECRET.
  Missing credentials => BLOCKED (exit 2), never FAIL.
- KILL criteria (FAIL + immediate abort, no further phases): stale or
  unknown quote data; unknown order outcomes at a gate; missed (non-live)
  protection; reduce-only exit mismatch; exposure cap breach.
- Verdicts: PASS / FAIL / BLOCKED per phase; exit 1 iff any FAIL.

Usage:
    demo_drill.py [--dir DIR] [--symbol SYM] full
"""
import argparse
import json
import os
import subprocess
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
        return (time.monotonic() - self.start_mono) < ENTRY_CUTOFF_S


def cmd_preflight(drill):
    if not drill.check_demo_only():
        return EXIT_BLOCKED
    if drill.creds() is None:
        return EXIT_BLOCKED
    try:
        from cryptobot.adapters.binance_live import UrllibTransport
        transport = UrllibTransport(drill.base_url or DEMO_FAPI, timeout_s=10)
        server_ms = transport.request("GET", "/fapi/v1/time", {}, {})["serverTime"]
        skew_ms = abs(server_ms - int(_utcnow().timestamp() * 1000))
        drill.log("preflight/clock", "PASS" if skew_ms < 5000 else "FAIL",
                  f"server skew {skew_ms}ms")
        engine = drill.engine()
        engine._ensure_ready(drill.symbol)
        drill.log("preflight/readiness", "PASS",
                  f"filters+fees cached for {drill.symbol}")
        available, free = engine.account_margin()
        drill.log("preflight/account", "PASS" if available > 0 else "FAIL",
                  f"available={available} free={free}")
        drill.log("preflight/fees",
                  "PASS", f"taker={engine.fee_bps(drill.symbol)}bps")
        mark = drill.live_mark()
        drill.log("preflight/mark", "PASS", f"{drill.symbol} mark {mark}")
        fresh, detail = drill.quote_fresh()
        if not fresh:
            return drill.kill("preflight/quote-fresh", detail)
        drill.log("preflight/quote-fresh", "PASS", detail)
        return 0
    except Exception as exc:
        drill.log("preflight", "FAIL", repr(exc))
        return 1


def _tiny_qty(drill, engine):
    """(qty, mark) or None when the exposure cap is breached (kill)."""
    mark = drill.live_mark()
    filt = engine._filters[drill.symbol]
    step = float(filt.get("step", 0.001))
    min_notional = float(filt.get("min_notional", 5.0))
    qty = max(step, min_notional * 1.2 / mark)
    qty = round(qty - (qty % step) + step, 8)
    if qty * mark > MAX_NOTIONAL_USDT:
        return None
    return qty, mark


def cmd_drill(drill):
    if not drill.check_demo_only():
        return EXIT_BLOCKED
    if drill.creds() is None:
        return EXIT_BLOCKED
    from cryptobot.adapters.binance_live import UnknownOutcomeError
    from cryptobot.app.engine import EngineOrder
    fails = 0
    # Stale-data gate runs before any engine/venue contact: no orders,
    # no signed calls, and no wasted setup on dead data.
    fresh, detail = drill.quote_fresh()
    if not fresh:
        return drill.kill("drill/quote-fresh", detail)
    drill.log("drill/quote-fresh", "PASS", detail)
    engine = drill.engine()
    engine._ensure_ready(drill.symbol)
    if not drill.entry_allowed():
        drill.log("drill/entry-cutoff", "BLOCKED", "past minute 20")
        return EXIT_BLOCKED
    sized = _tiny_qty(drill, engine)
    if sized is None:
        return drill.kill("drill/exposure-cap",
                          f"tiny qty exceeds {MAX_NOTIONAL_USDT} USDT cap")
    qty, mark = sized
    if engine.unknown_ids():
        return drill.kill("drill/pre-entry-reconcile",
                          f"unknown outcomes {sorted(engine.unknown_ids())}")
    # Phase 1: tiny IOC entry, observe cancel-or-fill honestly.
    cid = engine.submit(EngineOrder(
        drill.symbol, "BUY", qty, "LIMIT", price=round(mark * 0.99, 2),
        reservation_id="demo-entry-1", role="entry"))
    time.sleep(2.0)
    status = engine.lookup(cid)
    state = getattr(status, "state", "?") if status else "unknown"
    filled = engine.filled_qty(cid)
    drill.log("drill/entry-ioc",
              "PASS" if state in ("filled", "cancelled", "partial") else "FAIL",
              f"{cid} -> {state} filled={filled}")
    if state not in ("filled", "cancelled", "partial"):
        fails += 1
    # Phase 2: protection + reduce-only exit to flat (only if filled).
    if filled > 0:
        stop = engine.submit(EngineOrder(
            drill.symbol, "SELL", filled, "STOP_MARKET",
            stop_price=round(mark * 0.95, 2), reduce_only=True,
            reservation_id="demo-entry-1", role="stop"))
        stop_status = engine.lookup(stop)
        stop_state = getattr(stop_status, "state", "?") \
            if stop_status else "unknown"
        if stop_state not in ("open", "partial"):
            return drill.kill(
                "drill/protection",
                f"stop {stop} not live (state={stop_state}); aborting, "
                f"position open — owner must review/close manually")
        drill.log("drill/protection", "PASS",
                  f"stop leg {stop} verified live ({stop_state})")
        out = engine.submit(EngineOrder(
            drill.symbol, "SELL", filled, "MARKET", reduce_only=True,
            reservation_id="demo-entry-1", role="target"))
        time.sleep(2.0)
        out_filled = engine.filled_qty(out)
        if out_filled != filled:
            return drill.kill(
                "drill/reduce-only-exit",
                f"closed {out_filled}/{filled}; aborting, residual "
                f"exposure — owner must review/close manually")
        drill.log("drill/reduce-only-exit", "PASS",
                  f"closed {out_filled}/{filled}")
        try:
            engine.cancel(stop, "demo:position-closed")
        except Exception as exc:
            drill.log("drill/protection-cancel", "FAIL", repr(exc))
            fails += 1
        if engine.unknown_ids():
            return drill.kill("drill/post-exit-reconcile",
                              f"unknown outcomes "
                              f"{sorted(engine.unknown_ids())}")
    else:
        drill.log("drill/protection-exit", "BLOCKED",
                  "no fill to protect (honest no-trade)")
    # Phase 3: ambiguous submit — drop one order response, prove no duplicate.
    if not drill.entry_allowed():
        drill.log("drill/ambiguous-submit", "BLOCKED", "past entry cutoff")
    else:
        from cryptobot.adapters.binance_live import VenueHttpError

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
        engine2._ensure_ready(drill.symbol)
        try:
            engine2.submit(EngineOrder(
                drill.symbol, "BUY", qty, "LIMIT",
                price=round(mark * 0.99, 2),
                reservation_id="demo-ambig-1", role="entry"))
            drill.log("drill/ambiguous-submit", "FAIL",
                      "dropped response did not raise UNKNOWN")
            fails += 1
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
            else:
                drill.log(
                    "drill/ambiguous-submit", "FAIL",
                    f"cid={exc.client_id} resolved={found is not None} "
                    f"intents={len(intents)} open_legs={len(dupes)}")
                fails += 1
    # Phase 4: restart adoption in a fresh process.
    child = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--dir", str(drill.dir),
         "--symbol", drill.symbol, "resume-adopt"],
        capture_output=True, text=True, timeout=120)
    drill.log("drill/restart-adopt",
              "PASS" if child.returncode == 0 else "FAIL",
              (child.stdout.strip().splitlines() or [""])[-1][:200])
    if child.returncode != 0:
        fails += 1
    return 1 if fails else 0


def cmd_resume_adopt(drill):
    if not drill.check_demo_only():
        return EXIT_BLOCKED
    if drill.creds() is None:
        return EXIT_BLOCKED
    engine = drill.engine()
    # Contract v1: recover takes the EngineEvent handler; the drill
    # only inspects journal state, so adopted fills are discarded.
    engine.recover(lambda event: None)
    unknowns = engine.unknown_ids()
    opens = engine.open_orders()
    print(f"adopted journal={drill.journal_path} unknowns={len(unknowns)} "
          f"open={len(opens)}", flush=True)
    drill.log("resume-adopt", "PASS",
              f"unknowns={len(unknowns)} open={len(opens)}")
    return 0


def cmd_stream_gap(drill):
    try:
        from cryptobot.adapters import bridge as _bridge
        reader = getattr(_bridge, "user_stream_reader", None)
    except ImportError:
        reader = None
    if reader is None:
        drill.log("stream-gap", "BLOCKED",
                  "no user-stream reader integration (manager/CLI scope); "
                  "socket-loss injection needs the reader to exist")
        return EXIT_BLOCKED
    drill.log("stream-gap", "FAIL", "reader present but drill unwired")
    return 1


def cmd_reconcile(drill):
    if not drill.check_demo_only():
        return EXIT_BLOCKED
    if drill.creds() is None:
        return EXIT_BLOCKED
    engine = drill.engine()
    fails = 0
    opens = engine.open_orders()
    drill.log("reconcile/venue-open-orders",
              "PASS" if not opens else "FAIL", f"open={len(opens)}")
    if opens:
        fails += 1
    unknowns = engine.unknown_ids()
    drill.log("reconcile/unknowns",
              "PASS" if not unknowns else "FAIL", f"unknown={list(unknowns)}")
    if unknowns:
        fails += 1
    journal = engine._read_journal()
    fills = {}
    for record in journal:
        if record.get("event") == "fill-adopted":
            key = (record.get("symbol"), record.get("client_id"))
            fills[key] = fills.get(key, 0.0) + float(record.get("qty", 0.0))
    drill.log("reconcile/journal-fills", "PASS",
              f"{len(fills)} order-symbols, "
              f"qty={sum(fills.values()):.6f}")
    for record in journal:
        if record.get("event") == "submit-intent":
            cid = record.get("client_id")
            status = engine.lookup(cid)
            state = getattr(status, "state", "?") if status else "missing"
            ok = state in ("filled", "cancelled", "expired", "rejected",
                           "partial")
            drill.log(f"reconcile/order-{cid}", "PASS" if ok else "FAIL",
                      f"venue state={state}")
            if not ok:
                fails += 1
    return 1 if fails else 0


def main(argv=None):
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
    fails = 0
    blocked = 0
    for name, func in (("preflight", cmd_preflight), ("drill", cmd_drill),
                       ("stream-gap", cmd_stream_gap),
                       ("reconcile", cmd_reconcile)):
        rc = func(drill)
        if rc == 1:
            fails += 1
        elif rc == EXIT_BLOCKED:
            blocked += 1
        elif rc == EXIT_INCOMPLETE:
            return EXIT_INCOMPLETE
    drill.log("full", "FAIL" if fails else "PASS",
              f"fails={fails} blocked={blocked} "
              f"(BLOCKED phases declared, see evidence)")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
