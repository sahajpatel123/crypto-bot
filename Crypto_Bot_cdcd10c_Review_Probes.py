"""Read-only, offline review probes for crypto-bot cdcd10c.

Run FROM that repository with its environment:
  PYTHONPATH=src python /path/to/Crypto_Bot_cdcd10c_Review_Probes.py

All trading below is synthetic and local. No exchange connection is allowed.
Outputs observations, NOT a profitability test or a release acceptance gate.
Keep the JSON with the source/config SHA. This script changes no repo code.
"""
from __future__ import annotations

import argparse
import json
import runpy
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace


def deny_network(*args, **kwargs):
    raise RuntimeError("Review probes are offline: network connection forbidden")


socket.socket.connect = deny_network
socket.create_connection = deny_network

from cryptobot.app.config import load_config
from cryptobot.app.engine import EngineOrder
from cryptobot.app.session import Session, ReplayClock, _SymbolFeed, STRATEGY_ARMS
from cryptobot.app.store import RunStore
from cryptobot.bench_run import BenchRunner

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
SYM = "BTCUSDT"


def ioc_probe():
    helpers = runpy.run_path("tests/unit/test_ioc_arrival.py")
    engine = helpers["_engine"](submit_delay_ms=50, fill_delay_ms=50)
    quote, drain = helpers["_quote"], helpers["_drain"]
    try:
        quote(engine, T0, 99.0, 101.0)
        cid = engine.submit(EngineOrder(
            instrument=SYM, side="BUY", qty=.001, kind="LIMIT",
            price=101.5, role="entry"))
        engine.advance_to(T0 + timedelta(milliseconds=200))
        early = drain(engine)
        quote(engine, T0 + timedelta(seconds=10), 89.0, 90.0)
        late = drain(engine)
        def rows(events):
            return [{"kind": e.kind, "time": e.ts_utc.isoformat(),
                     "price": getattr(e.payload, "price", None)} for e in events]
        result = {"arrival_ask": 101.0, "later_ask": 90.0,
                  "at_200ms": rows(early), "at_10s": rows(late),
                  "defect_observed": any(
                      e.kind == "fill" and e.payload.price == 90.0 for e in late)}
        # Finish a local round-trip, then inspect the real engine's status API.
        engine.submit_immediate(EngineOrder(
            instrument=SYM, side="SELL", qty=.001, kind="MARKET",
            reduce_only=True, role="exit"))
        quote(engine, T0 + timedelta(seconds=11), 89.0, 90.0)
        terminal = drain(engine)
        statuses = engine.open_orders()
        dummy = SimpleNamespace(_position=None, engine=engine)
        result["after_roundtrip"] = {
            "exit_events": rows(terminal),
            "states_returned_by_open_orders": [x.state for x in statuses],
            "bench_calls_flat": BenchRunner._is_flat(None, dummy),
        }
        return result
    finally:
        engine.close()


def checkpoint_probe(root):
    filters = root / "filters.json"
    filters.write_text(json.dumps({"symbols": [{
        "symbol": SYM, "pricePrecision": 2, "quantityPrecision": 3,
        "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
            {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
            {"filterType": "MIN_NOTIONAL", "notional": "5"}]}]}))
    args = argparse.Namespace(config="configs/paper.toml",
                              checkpoint_dir=str(root / "checkpoint"),
                              engine_seed=42, filters_file=str(filters))
    runner = BenchRunner(args)
    s = runner._build_session("review")
    s.store.create_run("review", "bench", s.config.fingerprint,
                       str(s.workdir), None)
    first_ready = None
    seq = 0
    try:
        for second in range(141):
            ts = int(T0.timestamp() * 1000) + second * 1000
            for channel, payload in [
                ("bookTicker", {"bid": 99.99, "ask": 100.01,
                                "bid_qty": 5.0, "ask_qty": 5.0}),
                ("aggTrade", {"agg_id": second + 1, "price": 100.0,
                              "qty": .5, "buyer_is_maker": False})]:
                seq += 1
                event = {"channel": channel, "symbol": SYM,
                         "exchange_ts_ms": ts, "local_recv_ms": ts,
                         "seq": seq, "payload": payload}
                s._ingest(event, {}, {})  # Real ingestion, no trading strategies.
                if s._warmed and first_ready is None:
                    first_ready = second
        feed = s._feeds[SYM]
        before = {"bar_slots": len(feed.bars), "warmed": s._warmed,
                  "first_ready_elapsed_s": first_ready}
        runner._commit(s, {"day": "2026-10-01", "seq": seq})
        saved = json.loads(runner.ckpt_path.read_text())
    finally:
        s.engine.close()
        s.store.close()
    restored = runner._build_session("review")
    try:
        runner._restore(restored)
        after = {"feeds": len(restored._feeds), "warmed": restored._warmed}
        # Deliberately inconsistent crash state: the flat guard must refuse it.
        restored.ledger.record_fill("BUY", .5, 100., .05, T0, "review-orphan")
        orphan_is_flat = runner._is_flat(restored)
    finally:
        restored.engine.close()
        restored.store.close()
    # A resume must not silently change the experiment's configuration.
    changed_config = root / "changed.toml"
    changed_config.write_text(Path(args.config).read_text().replace(
        "cooldown_s = 300", "cooldown_s = 301"))
    args.config = str(changed_config)
    changed = runner._build_session("review")
    try:
        try:
            runner._restore(changed)
            changed_allowed = True
        except (ValueError, RuntimeError):
            changed_allowed = False
    finally:
        changed.engine.close()
        changed.store.close()
    return {"before_restart": before, "after_restart": after,
            "checkpoint_fields": sorted(saved),
            "orphan_ledger_qty_0_5_called_flat": orphan_is_flat,
            "changed_config_resume_allowed": changed_allowed}


def freshness_probe(root):
    cfg = load_config("configs/paper.toml")
    store = RunStore(root / "freshness.db")
    s = Session(cfg, store, root / "freshness", "fresh",
                clock=ReplayClock(T0))
    try:
        for symbol, age in [("BTCUSDT", 0), ("ETHUSDT", 60)]:
            feed = _SymbolFeed(symbol, 130)
            feed.mark = 100.
            feed.mark_ts = T0 - timedelta(seconds=age)
            s._feeds[symbol] = feed
        fresh_btc_stale_eth = s._quote_age_gate()
        s._feeds["BTCUSDT"].mark_ts = T0 - timedelta(seconds=60)
        s._feeds["ETHUSDT"].mark_ts = T0
        stale_btc_fresh_eth = s._quote_age_gate()
        return {"fresh_BTC_stale_ETH_gate": fresh_btc_stale_eth,
                "stale_BTC_fresh_ETH_gate": stale_btc_fresh_eth,
                "note": "The gate has no candidate-symbol argument; first feed wins."}
    finally:
        s.engine.close()
        store.close()


def nested_budget_probe(root):
    inner = [sys.executable, "tools/run_budget.py", "--budget-s", "30",
             "--checkpoint-dir", str(root / "inner"), "--report-out",
             str(root / "inner.json"), "--", sys.executable, "-c",
             "import time; time.sleep(8)"]
    outer = [sys.executable, "tools/run_budget.py", "--budget-s", "1",
             "--term-grace-s", ".2", "--checkpoint-dir", str(root / "outer"),
             "--report-out", str(root / "outer.json"), "--", *inner]
    start = time.monotonic()
    done = subprocess.run(outer, capture_output=True, text=True, timeout=15)
    return {"observed_elapsed_s": round(time.monotonic() - start, 3),
            "rc": done.returncode,
            "wrapper_report": json.loads((root / "outer.json").read_text()),
            "note": "Platform-sensitive: reproduce on the deployment OS."}


def main():
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="crypto-review-") as d:
        root = Path(d)
        result = {"reviewed_revision": "cdcd10cbb40c3983b78b73b3d924a00aeb62a8c5",
                  "input_class": "synthetic-offline-review",
                  "ioc": ioc_probe(),
                  "checkpoint": checkpoint_probe(root),
                  "freshness": freshness_probe(root),
                  "all_runtime_arms": [a for _, arms in STRATEGY_ARMS.values()
                                       for a in arms],
                  "nested_budget": nested_budget_probe(root)}
        result["elapsed_s"] = round(time.monotonic() - started, 3)
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
