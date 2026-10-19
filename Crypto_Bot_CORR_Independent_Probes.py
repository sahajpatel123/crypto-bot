"""Offline observations of CORR integration 0d40ad3 (not a profitability test).

Run from the reviewed repository with its Nautilus/pytest environment:
  PYTHONPATH=src python /path/to/Crypto_Bot_CORR_Independent_Probes.py

Uses the repository's existing synthetic restart tape. Observers do not alter
trading decisions. A second tape removes the later price moves that happen
to clear orphan exits. Network access is denied. No repository files change.
"""
from __future__ import annotations

import contextlib
import io
import json
import runpy
import socket
import sqlite3
import tempfile
import time
from collections import Counter
from pathlib import Path


def deny_network(*args, **kwargs):
    raise RuntimeError("Offline review: exchange/network access is forbidden")


socket.socket.connect = deny_network
socket.create_connection = deny_network

from cryptobot.app.session import Session
from cryptobot.risk.policy import RiskPolicy


def session_case(root: Path, *, remove_later_crossings: bool):
    h = runpy.run_path("tests/unit/test_bench_restart_equivalence.py")
    tape, filters = h["_write_tape"](root / "tape")
    if remove_later_crossings:
        rows = [json.loads(x) for x in (root / "tape/events.jsonl").read_text().splitlines()]
        for row in rows:
            if row["exchange_ts_ms"] < h["T0"] + 180_000:
                continue
            p = row["payload"]
            if row["channel"] == "bookTicker":
                p["bid"], p["ask"] = 100.23, 100.25
            elif row["channel"] == "aggTrade":
                p["price"] = 100.24
            elif row["channel"] == "markPrice":
                p["mark"] = 100.24
        (root / "tape/events.jsonl").write_text("\n".join(json.dumps(x) for x in rows) + "\n")

    obs = {"fills": [], "forgotten_live_legs": [], "expiry_transitions": [], "flatten_calls": []}
    original_ensure = Session._ensure_protection
    original_event = Session._on_engine_event
    original_flatten = Session._flatten
    original_expire = RiskPolicy._settle_expired

    def observe_ensure(s, pos):
        old = list(pos["legs"])
        result = original_ensure(s, pos)
        lost = set(old) - set(pos["legs"])
        if lost:
            for order in s.engine.open_orders():
                if order.client_order_id in lost and order.state in ("open", "partial"):
                    obs["forgotten_live_legs"].append({
                        "ts": s.now_utc().isoformat(), "id": order.client_order_id,
                        "state": order.state, "qty": order.qty,
                        "required_stop_qty": s.policy.required_stop_qty(pos["reservation_id"]),
                        "ledger_qty": s.ledger.position_qty(), "position_legs_after": list(pos["legs"]),
                    })
        return result

    def observe_event(s, event):
        result = original_event(s, event)
        if event.kind == "fill":
            f = event.payload
            obs["fills"].append({
                "ts": f.ts_utc.isoformat(), "side": f.side, "qty": f.qty, "price": f.price,
                "fee": f.fee, "ledger_qty": s.ledger.position_qty(),
                "policy_open_position": s.policy._state.open_position,
                "reservations": list(s.policy._state.reservations),
                "unresolved": list(s.policy._state.unresolved),
            })
        return result

    def observe_flatten(s, reason):
        if len(obs["flatten_calls"]) < 20:
            obs["flatten_calls"].append({"ts": s.now_utc().isoformat(), "reason": reason,
                                         "net": s.ledger.position_qty()})
        return original_flatten(s, reason)

    def observe_expire(p, now):
        before = set(p._state.unresolved)
        result = original_expire(p, now)
        for rid in set(p._state.unresolved) - before:
            obs["expiry_transitions"].append({"ts": now.isoformat(), "reservation_id": rid,
                                               "booked_net": p.booked_net(rid),
                                               "policy_open_position": p._state.open_position})
        return result

    Session._ensure_protection = observe_ensure
    Session._on_engine_event = observe_event
    Session._flatten = observe_flatten
    RiskPolicy._settle_expired = observe_expire
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc, report = h["_run_case"](root, "run", tape, filters)
    finally:
        Session._ensure_protection = original_ensure
        Session._on_engine_event = original_event
        Session._flatten = original_flatten
        RiskPolicy._settle_expired = original_expire
    db = sqlite3.connect(root / "run/ck/store.db")
    try:
        cps = [(kind, json.loads(payload)) for kind, payload in
               db.execute("SELECT kind, payload FROM checkpoints ORDER BY id")]
    finally:
        db.close()
    relevant = [(k, p) for k, p in cps if k.startswith("protection")]
    counts = dict(Counter(k for k, _ in relevant))
    obs.update({"returncode": rc, "status": report.get("status"),
                "booked": report.get("booked"), "protection_counts": counts,
                "protection_first": relevant[:12],
                "no_later_crossings": remove_later_crossings})
    return obs


def prior_corrections(root: Path):
    h = runpy.run_path("Crypto_Bot_cdcd10c_Review_Probes.py")
    root.mkdir()
    # The original aggregate probe no longer runs: freshness now requires
    # a symbol argument. The permanent CORR tests exercise that new API.
    return {"ioc": h["ioc_probe"](), "checkpoint": h["checkpoint_probe"](root),
            "nested_budget": h["nested_budget_probe"](root)}


def scoring_cases(root: Path):
    from cryptobot.research.scoring import score_cell
    from cryptobot.research.funnel import analyze_run
    fixture = runpy.run_path("tests/unit/test_research_scoring.py")["_mini_scored_run"]
    results = {}
    for name in ("partial_close", "funded_ist_day", "two_symbols_same_second"):
        folder = root / name
        folder.mkdir(parents=True)
        run = fixture(folder)
        ledger_path = run / "ledger.json"
        ledger = json.loads(ledger_path.read_text())
        if name == "partial_close":
            ledger["journal"][1]["qty"] = 0.005
            ledger["journal"][1]["fee"] = 0.015
            ledger_path.write_text(json.dumps(ledger))
            panel = score_cell(run)
            results[name] = {"remaining_open_qty": 0.005,
                             "reported_closed_trades": panel["closed_trades"],
                             "reported_expectancy_n": panel["expectancy"]["n"]}
        elif name == "funded_ist_day":
            ledger["journal"][0]["ts_utc"] = "2026-10-11T18:31:00+00:00"
            ledger["journal"][1]["ts_utc"] = "2026-10-11T18:32:00+00:00"
            ledger["journal"].append({"kind": "funding", "amount": -0.20,
                                       "ts_utc": "2026-10-11T18:31:30+00:00"})
            ledger_path.write_text(json.dumps(ledger))
            equity = [{"ts_utc": "2026-10-11T18:30:45+00:00", "marked_equity": 120.0},
                      {"ts_utc": "2026-10-11T18:32:45+00:00", "marked_equity": 120.74}]
            (run / "equity.jsonl").write_text("\n".join(json.dumps(x) for x in equity) + "\n")
            panel = score_cell(run)
            results[name] = {"expected_trading_day": "2026-10-12",
                             "expected_net": 0.74, "reported_booked_net": panel["booked"]["net"],
                             "reported_daily_net": panel["daily_net"],
                             "reported_trade_net": panel["trades"][0]["net"]}
        else:
            con = sqlite3.connect(run / "store.db")
            con.execute("DELETE FROM intents")
            con.commit()
            con.close()
            rows = [{"ts_utc": "2026-10-11T10:00:01+00:00", "stage": "strategy",
                     "reason": "breakout:fail|breakout:fail", "strategy": "S1",
                     "instrument": symbol, "side": "unknown"}
                    for symbol in ("BTCUSDT", "ETHUSDT")]
            (run / "rejections.jsonl").write_text("\n".join(json.dumps(x) for x in rows) + "\n")
            panel = analyze_run(run)
            results[name] = {"expected_symbol_seconds": 2,
                             "reported_strategy_eligible_seconds": panel["stages"]["strategy_eligible_seconds"],
                             "note": "The code counts clock-seconds, so dividing this numerator by symbol-seconds is invalid."}
    return results


def main():
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="corr-independent-") as d:
        root = Path(d)
        out = {"reviewed_revision": "0d40ad3b671741baad7b0ced3738b8b1549e5962",
               "input_class": "synthetic-offline-diagnostic",
               "earlier_corrections": prior_corrections(root / "prior"),
               "existing_restart_tape": session_case(root / "original", remove_later_crossings=False),
               "same_entry_without_later_price_crossings": session_case(root / "quiet", remove_later_crossings=True),
               "scoring": scoring_cases(root / "scoring")}
        out["elapsed_s"] = round(time.monotonic() - started, 3)
        print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
