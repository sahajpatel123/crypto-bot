#!/usr/bin/env python3
"""Owner-run demo drill (F4.2). NEVER run by the agent/CI.

This is the credentialed harness described in OWNER_ACTIONS.md. It uses
demo/testnet keys from the environment, verifies account modes, places a
minimum-size demo entry, attaches a protective stop/target, then flattens
and confirms flat. It never touches production keys or the production
host. The report contains no secrets.

Without `--execute-orders` it performs read-only checks and exits
BLOCKED, so a smoke test cannot place anything by accident.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main(argv: list[str] | None = None) -> int:
    from cryptobot import netguard  # opt-in DNS-sinkhole fallback (CRYPTOBOT_DOH=1)

    netguard.install_from_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/demo.toml")
    ap.add_argument("--out", default="drill.json")
    ap.add_argument("--execute-orders", action="store_true")
    ap.add_argument("--symbol", default="BTCUSDT")
    args = ap.parse_args(argv)

    from cryptobot.app.config import load_config
    from cryptobot.adapters.binance_live import BinanceLiveEngine
    from cryptobot.app.engine import EngineOrder

    config = load_config(args.config)
    if not config.engine_demo:
        print("demo-drill-live: REFUSED config is not demo", file=sys.stderr)
        return 2
    # Credentials: the demo profile only. `cryptobot keys set --profile demo`
    # stores CRYPTOBOT_DEMO_KEY/SECRET in the Keychain or the git-ignored
    # dotenv file; the previously documented BINANCE_DEMO_KEY/SECRET keep
    # working as an environment fallback. A production key never satisfies
    # this drill, because the profiles are disjoint names.
    from cryptobot.ops import credentials as _creds

    resolved = _creds.load_credentials(profile=_creds.PROFILE_DEMO)
    steps: list[dict] = []
    if not resolved.complete:
        steps.append({"step": "credentials", "status": "BLOCKED",
                      "detail": "demo credentials not set: "
                                + ", ".join(resolved.missing)
                                + "; store them with `cryptobot keys set "
                                  "--profile demo` (BINANCE_DEMO_KEY/SECRET "
                                  "are still accepted)"})
        _write(args.out, "BLOCKED", steps, config.engine_base_url)
        return 2
    key_obj, secret_obj = resolved.require()
    key, secret = key_obj.reveal(), secret_obj.reveal()
    if not args.execute_orders:
        steps.append({"step": "read-only", "status": "PASS",
                      "detail": "credentials present; pass --execute-orders "
                                "to run the demo drill"})
        _write(args.out, "BLOCKED", steps, config.engine_base_url)
        return 2

    engine = BinanceLiveEngine(
        api_key=key, api_secret=secret,
        journal_path=Path("runs") / "demo-drill" / "journal.jsonl",
        expected_leverage=int(config.leverage_cap), run_tag="drill",
        live_enable=True, demo=True,
        base_url=config.engine_base_url)
    try:
        t0 = time.perf_counter()
        modes = engine.verify_account_modes(
            [args.symbol], leverage_cap=config.leverage_cap)
        steps.append({"step": "auth+modes", "status": "PASS",
                      "latency_ms": _ms(t0), "detail": modes})
        snap = engine.account_snapshot()
        if snap is None or not getattr(snap, "complete", False):
            raise RuntimeError("account snapshot incomplete")
        filt = engine._filters[args.symbol]
        mark = float(engine.valuation_mark(args.symbol)
                     or snap.wallet_equity_usdt or 0.0)
        if mark <= 0:
            raise RuntimeError("no mark price for drill symbol")
        qty = max(float(filt["min_qty"]),
                  float(filt.get("min_notional", 0.0) or 0.0) / mark)
        qty = max(qty, float(filt["step"]))
        t0 = time.perf_counter()
        cid = engine.submit(EngineOrder(
            args.symbol, "BUY", qty, "MARKET", reservation_id="drill-entry",
            role="entry"))
        steps.append({"step": "tiny-entry-ack", "status": "PASS",
                      "latency_ms": _ms(t0), "client_id": cid})
        filled = _wait_filled(engine, cid, timeout_s=15.0)
        if filled <= 0:
            raise RuntimeError("demo entry did not fill")
        steps.append({"step": "tiny-entry-fill", "status": "PASS",
                      "qty": filled})
        _status = engine.order_status(cid)
        entry_px = float(getattr(_status, "avg_price", None) or mark)
        stop = entry_px * (1.0 - 25.0 / 10_000.0)
        target = entry_px * (1.0 + 50.0 / 10_000.0)
        t0 = time.perf_counter()
        legs = engine.attach_protection(cid, stop, target)
        steps.append({"step": "protection-attach", "status": "PASS",
                      "latency_ms": _ms(t0), "legs": list(legs)})
        # Flatten reduce-only and confirm flat.
        t0 = time.perf_counter()
        close = engine.submit_immediate(EngineOrder(
            args.symbol, "SELL", filled, "MARKET", reduce_only=True,
            reservation_id="drill-entry", role="target"))
        flat = _wait_flat(engine, args.symbol, timeout_s=20.0)
        if not flat:
            raise RuntimeError("demo flatten did not reach flat")
        steps.append({"step": "sigterm-flatten-equivalent", "status": "PASS",
                      "latency_ms": _ms(t0), "close_id": close})
        verdict = "PASS"
        rc = 0
    except Exception as exc:  # noqa: BLE001 — owner report, never hides
        steps.append({"step": "drill", "status": "FAIL",
                      "error": f"{type(exc).__name__}: {exc}"})
        verdict, rc = "FAIL", 1
    finally:
        engine.close()
    _write(args.out, verdict, steps, config.engine_base_url)
    return rc


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 3)


def _wait_filled(engine, cid: str, *, timeout_s: float) -> float:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        engine.poll()
        status = engine.lookup(cid)
        if status is not None and status.state == "filled":
            return float(status.filled_qty or 0.0)
        time.sleep(0.25)
    return float(engine.filled_qty(cid) or 0.0)


def _wait_flat(engine, symbol: str, *, timeout_s: float) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        engine.poll()
        snap = engine.account_snapshot()
        if snap is not None and getattr(snap, "complete", False):
            qty = sum(abs(float(getattr(p, "qty", 0.0) or 0.0))
                      for p in snap.positions
                      if getattr(p, "instrument", "") == symbol)
            if qty <= 1e-9:
                return True
        time.sleep(0.25)
    return False


def _write(out: str, verdict: str, steps: list[dict], venue: str) -> None:
    # Positive venue proof (gate-tightening D-066): a PASS verdict implies
    # the engine session ran against exactly this base_url (the engine is
    # constructed with it); BLOCKED docs are gate-refused regardless.
    doc = {"drill": "demo-drill-live", "verdict": verdict,
           "provenance": "DEMO", "venue": venue,
           "created_utc": _now(), "steps": steps,
           "note": "demo/testnet only; never proof of live edge"}
    doc["sha256"] = hashlib.sha256(
        json.dumps(doc, sort_keys=True).encode()).hexdigest()
    p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                 encoding="utf-8")
    print(json.dumps(doc, indent=1, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
